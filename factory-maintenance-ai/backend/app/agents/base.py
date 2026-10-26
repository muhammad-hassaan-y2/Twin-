from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from sqlalchemy.orm import Session
from app.models.agent_run import AgentRun, AgentStatus
from app.models.activity_log import ActivityLog


class BaseAgent(ABC):
    def __init__(self, name: str, order: int):
        self.name = name
        self.order = order

    @abstractmethod
    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute the agent's logic and return output data."""
        pass

    def update_status(self, db: Session, agent_run: AgentRun, status: AgentStatus, task: Optional[str] = None, error: Optional[str] = None):
        agent_run.status = status
        if task:
            agent_run.current_task = task
        if error:
            agent_run.error_message = error
        if status == AgentStatus.RUNNING and not agent_run.started_at:
            agent_run.started_at = datetime.utcnow()
        if status in (AgentStatus.COMPLETED, AgentStatus.FAILED):
            agent_run.completed_at = datetime.utcnow()
        db.commit()

    def log_activity(self, db: Session, incident_id: int, action: str, actor: str, actor_type: str, description: str, details: Optional[Dict] = None, from_status: Optional[str] = None, to_status: Optional[str] = None, work_order_id: Optional[int] = None):
        log = ActivityLog(
            incident_id=incident_id,
            work_order_id=work_order_id,
            action=action,
            actor=actor,
            actor_type=actor_type,
            description=description,
            details=details,
            from_status=from_status,
            to_status=to_status
        )
        db.add(log)
        db.commit()