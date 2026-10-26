from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.inventory_part import InventoryPart, PartStatus


class PartsSourcingAgent(BaseAgent):
    def __init__(self):
        super().__init__("Parts Sourcing Agent", 4)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Searching inventory for replacement part")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get fault diagnosis to understand what part is needed
        diagnosis = context.get("identified_failure", "")
        root_cause = context.get("suspected_root_cause", "")
        
        # Find compatible parts for this machine
        compatible_parts = db.query(InventoryPart).filter(
            InventoryPart.compatible_machines.contains([incident.machine_id])
        ).all()
        
        if not compatible_parts:
            # Fallback: search by name/description matching
            compatible_parts = db.query(InventoryPart).filter(
                InventoryPart.name.ilike(f"%{incident.machine_name.split()[0]}%")
            ).all()
        
        # Select best matching part based on failure type
        recommended_part = self._select_best_part(compatible_parts, diagnosis, root_cause)
        
        if not recommended_part:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No compatible parts found in inventory")
            return {"error": "No compatible parts found", "part_availability": "none"}
        
        # Check availability
        availability = self._check_availability(recommended_part)
        
        self.log_activity(
            db, incident_id, "parts_sourcing_complete", self.name, "agent",
            f"Recommended part: {recommended_part.name} ({recommended_part.part_number}) - {availability}",
            {
                "part_id": recommended_part.id,
                "part_number": recommended_part.part_number,
                "availability": availability,
                "quantity_on_hand": recommended_part.quantity_on_hand
            }
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Parts sourcing complete")
        return {
            "recommended_part_id": recommended_part.id,
            "part_number": recommended_part.part_number,
            "part_name": recommended_part.name,
            "description": recommended_part.description,
            "unit_cost": recommended_part.unit_cost,
            "quantity_on_hand": recommended_part.quantity_on_hand,
            "part_availability": availability,
            "lead_time_days": recommended_part.lead_time_days,
            "location": recommended_part.location,
            "is_critical": recommended_part.is_critical
        }
    
    def _select_best_part(self, parts: List[InventoryPart], diagnosis: str, root_cause: str) -> InventoryPart:
        """Select the best matching part based on failure diagnosis."""
        if not parts:
            return None
        
        # Score parts based on relevance to failure
        scored_parts = []
        diagnosis_lower = (diagnosis + " " + root_cause).lower()
        
        for part in parts:
            score = 0
            part_text = f"{part.name} {part.description or ''}".lower()
            
            # Keyword matching
            keywords = ["bearing", "seal", "gasket", "filter", "pump", "motor", "valve", "sensor", "belt", "coupling"]
            for kw in keywords:
                if kw in diagnosis_lower and kw in part_text:
                    score += 10
            
            # Prefer in-stock parts
            if part.status == PartStatus.IN_STOCK:
                score += 5
            elif part.status == PartStatus.LOW_STOCK:
                score += 2
            
            # Prefer critical parts for critical failures
            if part.is_critical and "critical" in diagnosis_lower:
                score += 3
            
            scored_parts.append((score, part))
        
        scored_parts.sort(key=lambda x: x[0], reverse=True)
        return scored_parts[0][1] if scored_parts else parts[0]
    
    def _check_availability(self, part: InventoryPart) -> str:
        if part.quantity_on_hand <= 0:
            return "unavailable"
        elif part.quantity_on_hand <= part.reorder_point:
            return "low_stock"
        return "available"