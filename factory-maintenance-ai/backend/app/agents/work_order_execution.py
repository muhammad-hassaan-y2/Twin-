from typing import Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.maintenance_plan import MaintenancePlan, PlanStatus
from app.models.work_order import WorkOrder, WorkOrderStatus, WorkOrderPriority
from app.models.technician import Technician, TechnicianStatus
from app.models.inventory_part import InventoryPart


class WorkOrderExecutionAgent(BaseAgent):
    def __init__(self):
        super().__init__("Work Order Execution Agent", 10)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Creating work order")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
        if not plan:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No maintenance plan found")
            return {"error": "No maintenance plan found", "work_order_created": False}
        
        # Check if plan is approved
        if plan.status != PlanStatus.APPROVED:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="Plan not approved - cannot create work order")
            return {"error": "Maintenance plan must be approved before creating work order", "work_order_created": False}
        
        # Check if work order already exists
        existing_wo = db.query(WorkOrder).filter(WorkOrder.incident_id == incident_id).first()
        if existing_wo:
            self.update_status(db, agent_run, AgentStatus.COMPLETED, "Work order already exists")
            return {
                "work_order_created": True,
                "work_order_id": existing_wo.id,
                "work_order_number": existing_wo.work_order_number,
                "message": "Work order already exists"
            }
        
        # Create work order
        work_order = self._create_work_order(db, incident, plan)
        
        # Update incident status
        incident.status = type(incident.status).WORK_ORDER_CREATED if hasattr(type(incident.status), 'WORK_ORDER_CREATED') else "work_order_created"
        
        # Update technician status
        if work_order.assigned_technician_id:
            tech = db.query(Technician).filter(Technician.id == work_order.assigned_technician_id).first()
            if tech:
                tech.status = TechnicianStatus.BUSY
                tech.current_work_order_id = work_order.id
        
        # Update part quantity if available
        if work_order.replacement_part_id:
            part = db.query(InventoryPart).filter(InventoryPart.id == work_order.replacement_part_id).first()
            if part and part.quantity_on_hand > 0:
                part.quantity_on_hand -= 1
        
        db.commit()
        
        self.log_activity(
            db, incident_id, "work_order_created", self.name, "agent",
            f"Work order {work_order.work_order_number} created",
            {
                "work_order_id": work_order.id,
                "work_order_number": work_order.work_order_number,
                "technician_id": work_order.assigned_technician_id,
                "part_id": work_order.replacement_part_id
            },
            from_status="approved",
            to_status="work_order_created",
            work_order_id=work_order.id
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Work order created successfully")
        return {
            "work_order_created": True,
            "work_order_id": work_order.id,
            "work_order_number": work_order.work_order_number,
            "status": work_order.status.value if hasattr(work_order.status, 'value') else str(work_order.status),
            "message": "Work order created and ready for execution"
        }
    
    def _create_work_order(self, db: Session, incident: Incident, plan: MaintenancePlan) -> WorkOrder:
        """Create work order from approved maintenance plan."""
        # Generate work order number
        count = db.query(WorkOrder).count()
        wo_number = f"WO-{datetime.utcnow().strftime('%Y%m%d')}-{count + 1:04d}"
        
        work_order = WorkOrder(
            work_order_number=wo_number,
            incident_id=incident.id,
            maintenance_plan_id=plan.id,
            assigned_technician_id=plan.recommended_technician_id,
            replacement_part_id=plan.recommended_part_id,
            priority=WorkOrderPriority(plan.proposed_work_order_priority) if plan.proposed_work_order_priority else WorkOrderPriority.MEDIUM,
            status=WorkOrderStatus.CREATED,
            scheduled_start=plan.proposed_downtime_start,
            scheduled_end=plan.proposed_downtime_end,
            approved_by=plan.approved_by,
            approved_at=plan.approved_at
        )
        
        db.add(work_order)
        db.flush()  # Get the ID
        
        return work_order
    
    def advance_work_order(self, db: Session, work_order_id: int, action: str, actor: str, notes: str = None) -> Dict[str, Any]:
        """Advance work order through execution stages (called from API)."""
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        
        incident_id = work_order.incident_id
        
        if action == "start":
            if work_order.status != WorkOrderStatus.CREATED and work_order.status != WorkOrderStatus.SCHEDULED:
                raise ValueError(f"Cannot start work order in status: {work_order.status}")
            work_order.status = WorkOrderStatus.IN_PROGRESS
            work_order.actual_start = datetime.utcnow()
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident:
                incident.status = type(incident.status).IN_PROGRESS if hasattr(type(incident.status), 'IN_PROGRESS') else "in_progress"
            
            self.log_activity(
                db, incident_id, "work_order_started", actor, "human",
                f"Work order {work_order.work_order_number} started",
                {"work_order_id": work_order.id, "actor": actor, "notes": notes},
                from_status=work_order.status.value if hasattr(work_order.status, 'value') else str(work_order.status),
                to_status="in_progress",
                work_order_id=work_order.id
            )
            
        elif action == "complete":
            if work_order.status != WorkOrderStatus.IN_PROGRESS:
                raise ValueError(f"Cannot complete work order in status: {work_order.status}")
            work_order.status = WorkOrderStatus.AWAITING_VERIFICATION
            work_order.actual_end = datetime.utcnow()
            work_order.completion_notes = notes
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident:
                incident.status = type(incident.status).AWAITING_VERIFICATION if hasattr(type(incident.status), 'AWAITING_VERIFICATION') else "awaiting_verification"
            
            self.log_activity(
                db, incident_id, "work_order_completed", actor, "human",
                f"Work order {work_order.work_order_number} completed - awaiting verification",
                {"work_order_id": work_order.id, "actor": actor, "notes": notes},
                from_status="in_progress",
                to_status="awaiting_verification",
                work_order_id=work_order.id
            )
            
        elif action == "hold":
            work_order.status = WorkOrderStatus.ON_HOLD
            work_order.progress_notes = notes
            
            self.log_activity(
                db, incident_id, "work_order_on_hold", actor, "human",
                f"Work order {work_order.work_order_number} placed on hold",
                {"work_order_id": work_order.id, "actor": actor, "notes": notes},
                from_status=work_order.status.value if hasattr(work_order.status, 'value') else str(work_order.status),
                to_status="on_hold",
                work_order_id=work_order.id
            )
        
        db.commit()
        return {
            "work_order_id": work_order.id,
            "work_order_number": work_order.work_order_number,
            "new_status": work_order.status.value if hasattr(work_order.status, 'value') else str(work_order.status),
            "action": action
        }