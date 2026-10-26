from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident, IncidentStatus


class IncidentIntakeAgent(BaseAgent):
    def __init__(self):
        super().__init__("Incident Intake Agent", 1)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Validating incident data")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Validate required fields
        validation_errors = []
        if not incident.machine_id:
            validation_errors.append("Machine ID is required")
        if not incident.machine_name:
            validation_errors.append("Machine name is required")
        if not incident.location:
            validation_errors.append("Location is required")
        if not incident.failure_description:
            validation_errors.append("Failure description is required")
        if not incident.photo_path:
            validation_errors.append("Component photo is required")
        
        if validation_errors:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="; ".join(validation_errors))
            return {"valid": False, "errors": validation_errors}
        
        # Update incident status
        incident.status = IncidentStatus.INVESTIGATING
        db.commit()
        
        self.log_activity(
            db, incident_id, "incident_validated", self.name, "agent",
            f"Incident validated and moved to investigation phase",
            {"validation_errors": validation_errors},
            from_status=IncidentStatus.SUBMITTED.value,
            to_status=IncidentStatus.INVESTIGATING.value
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Incident validation complete")
        return {
            "valid": True,
            "incident_id": incident_id,
            "machine_id": incident.machine_id,
            "severity": incident.severity.value,
            "message": "Incident validated successfully"
        }