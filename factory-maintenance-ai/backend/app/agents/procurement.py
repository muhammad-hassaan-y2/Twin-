from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.inventory_part import InventoryPart, PartStatus


class ProcurementAgent(BaseAgent):
    def __init__(self):
        super().__init__("Procurement Agent", 5)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Checking if procurement is needed")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get recommended part from parts sourcing
        part_id = context.get("recommended_part_id")
        if not part_id:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No part ID provided")
            return {"error": "No part ID provided", "procurement_needed": False}
        
        part = db.query(InventoryPart).filter(InventoryPart.id == part_id).first()
        if not part:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="Part not found")
            return {"error": "Part not found", "procurement_needed": False}
        
        availability = context.get("part_availability", "unknown")
        
        if availability in ["available", "low_stock"]:
            # Part is available, no procurement needed
            self.update_status(db, agent_run, AgentStatus.COMPLETED, "Part available - no procurement needed")
            return {
                "procurement_needed": False,
                "part_available": True,
                "message": "Part is in stock, no purchase request required"
            }
        
        # Part unavailable - create purchase request
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Creating purchase request")
        
        purchase_request = self._create_purchase_request(part, incident)
        
        # Update part status to ON_ORDER
        part.status = PartStatus.ON_ORDER
        db.commit()
        
        self.log_activity(
            db, incident_id, "purchase_request_created", self.name, "agent",
            f"Purchase request created for {part.name} ({part.part_number})",
            {
                "purchase_request": purchase_request,
                "part_id": part.id,
                "estimated_cost": part.unit_cost * part.reorder_quantity if part.unit_cost else 0
            }
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Purchase request created")
        return {
            "procurement_needed": True,
            "part_available": False,
            "purchase_request": purchase_request,
            "estimated_lead_time_days": part.lead_time_days,
            "estimated_cost": part.unit_cost * part.reorder_quantity if part.unit_cost else 0,
            "reorder_quantity": part.reorder_quantity,
            "note": "Procurement initiated. Part will be available after lead time."
        }
    
    def _create_purchase_request(self, part: InventoryPart, incident: Incident) -> Dict[str, Any]:
        """Generate a purchase request for the unavailable part."""
        return {
            "request_id": f"PR-{incident.id}-{part.id}",
            "part_number": part.part_number,
            "part_name": part.name,
            "quantity": part.reorder_quantity,
            "unit_cost": part.unit_cost,
            "total_estimated_cost": part.unit_cost * part.reorder_quantity if part.unit_cost else 0,
            "urgency": "high" if part.is_critical else "normal",
            "requested_for_machine": incident.machine_id,
            "requested_by": "Maintenance Planning System",
            "preferred_vendor": part.manufacturer or "Primary Vendor",
            "delivery_required_by": "ASAP",
            "status": "submitted"
        }