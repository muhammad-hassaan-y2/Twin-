from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class ActivityLogResponse(BaseModel):
    id: int
    incident_id: int
    work_order_id: Optional[int] = None
    action: str
    actor: Optional[str] = None
    actor_type: Optional[str] = None
    description: Optional[str] = None
    details: Optional[Dict[str, Any]] = None
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True