from pydantic import BaseModel, Field, HttpUrl
from typing import Optional, List
from datetime import datetime
from enum import Enum


class Severity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class IncidentStatus(str, Enum):
    SUBMITTED = "submitted"
    INVESTIGATING = "investigating"
    PLAN_PROPOSED = "plan_proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    WORK_ORDER_CREATED = "work_order_created"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    CLOSED = "closed"
    FAILED_VERIFICATION = "failed_verification"


class IncidentCreate(BaseModel):
    machine_id: str = Field(..., min_length=1, max_length=100)
    machine_name: str = Field(..., min_length=1, max_length=200)
    location: str = Field(..., min_length=1, max_length=200)
    failure_description: str = Field(..., min_length=1)
    severity: Severity = Severity.MEDIUM


class IncidentResponse(BaseModel):
    id: int
    machine_id: str
    machine_name: str
    location: str
    failure_description: str
    severity: Severity
    status: IncidentStatus
    photo_path: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class IncidentListResponse(BaseModel):
    id: int
    machine_id: str
    machine_name: str
    location: str
    severity: Severity
    status: IncidentStatus
    created_at: datetime

    class Config:
        from_attributes = True