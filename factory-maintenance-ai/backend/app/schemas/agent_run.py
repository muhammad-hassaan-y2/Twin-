from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class AgentStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentRunResponse(BaseModel):
    id: int
    incident_id: int
    agent_name: str
    agent_order: int
    status: AgentStatus
    current_task: Optional[str] = None
    input_data: Optional[Dict[str, Any]] = None
    output_data: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AgentRunListResponse(BaseModel):
    agents: List[AgentRunResponse]
    overall_status: str  # "pending", "in_progress", "completed", "failed"
    completed_count: int
    total_count: int