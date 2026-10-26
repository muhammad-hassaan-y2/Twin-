from typing import Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.maintenance_plan import MaintenancePlan, PlanStatus


class HumanApprovalAgent(BaseAgent):
    def __init__(self):
        super().__init__("Human Approval Agent", 9)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Awaiting human approval")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
        if not plan:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No maintenance plan found")
            return {"error": "No maintenance plan found", "awaiting_approval": False}
        
        # This agent pauses the workflow - the actual approval happens via API
        # We just record that we're waiting for approval
        plan.status = PlanStatus.PROPOSED
        db.commit()
        
        self.log_activity(
            db, incident_id, "awaiting_human_approval", self.name, "agent",
            "Maintenance plan submitted for human approval",
            {
                "plan_id": plan.id,
                "proposed_priority": plan.proposed_work_order_priority,
                "risk_level": plan.risk_level
            }
        )
        
        # This agent completes but the workflow pauses here
        # The workflow continues only after approval via API endpoint
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Plan submitted for approval - awaiting human decision")
        
        return {
            "awaiting_approval": True,
            "plan_id": plan.id,
            "message": "Maintenance plan proposed. Awaiting human approval before proceeding.",
            "plan_summary": {
                "identified_failure": plan.identified_failure,
                "recommended_part": context.get("part_name"),
                "recommended_technician": context.get("technician_name"),
                "estimated_duration": plan.estimated_repair_duration_hours,
                "downtime_window": {
                    "start": plan.proposed_downtime_start.isoformat() if plan.proposed_downtime_start else None,
                    "end": plan.proposed_downtime_end.isoformat() if plan.proposed_downtime_end else None
                },
                "risk_level": plan.risk_level,
                "estimated_cost": plan.estimated_part_cost
            }
        }
    
    def process_approval(self, db: Session, incident_id: int, approved: bool, reviewer: str, rejection_reason: str = None) -> Dict[str, Any]:
        """Process human approval decision (called from API)."""
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
        
        if not incident or not plan:
            raise ValueError("Incident or plan not found")
        
        if approved:
            plan.status = PlanStatus.APPROVED
            plan.approved_by = reviewer
            plan.approved_at = datetime.utcnow()
            incident.status = type(incident.status).APPROVED if hasattr(type(incident.status), 'APPROVED') else "approved"
            
            self.log_activity(
                db, incident_id, "plan_approved", reviewer, "human",
                f"Maintenance plan approved by {reviewer}",
                {"plan_id": plan.id, "reviewer": reviewer},
                from_status="plan_proposed",
                to_status="approved"
            )
            
            return {"approved": True, "message": "Plan approved. Work order creation can proceed."}
        else:
            plan.status = PlanStatus.REJECTED
            plan.rejection_reason = rejection_reason or "No reason provided"
            incident.status = type(incident.status).REJECTED if hasattr(type(incident.status), 'REJECTED') else "rejected"
            
            self.log_activity(
                db, incident_id, "plan_rejected", reviewer, "human",
                f"Maintenance plan rejected by {reviewer}: {rejection_reason}",
                {"plan_id": plan.id, "reviewer": reviewer, "reason": rejection_reason},
                from_status="plan_proposed",
                to_status="rejected"
            )
            
            return {"approved": False, "message": f"Plan rejected: {rejection_reason}"}