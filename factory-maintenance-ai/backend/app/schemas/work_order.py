from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class WorkOrderStatus(str, Enum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    CLOSED = "closed"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


class WorkOrderPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrderResponse(BaseModel):
    id: int
    work_order_number: str
    incident_id: int
    maintenance_plan_id: Optional[int] = None
    assigned_technician_id: Optional[int] = None
    replacement_part_id: Optional[int] = None
    priority: WorkOrderPriority
    status: WorkOrderStatus
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    actual_start: Optional[datetime] = None
    actual_end: Optional[datetime] = None
    progress_notes: Optional[str] = None
    completion_notes: Optional[str] = None
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    # Related data (populated via joins)
    incident: Optional[dict] = None
    technician: Optional[dict] = None
    part: Optional[dict] = None

    class Config:
        from_attributes = True


class WorkOrderListResponse(BaseModel):
    id: int
    work_order_number: str
    incident_id: int
    machine_id: str
    machine_name: str
    assigned_technician: Optional[str] = None
    replacement_part: Optional[str] = None
    priority: WorkOrderPriority
    status: WorkOrderStatus
    scheduled_start: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None

    class Config:
        from_attributes = True


class WorkOrderExecuteRequest(BaseModel):
    action: str = Field(..., pattern="^(start|complete|hold)$")
    notes: Optional[str] = None
    actor: str = Field(..., min_length=1, max_length=100)