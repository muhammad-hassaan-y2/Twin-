from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class VerificationStatus(str, Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class RepairVerificationRequest(BaseModel):
    expected_component: str = Field(..., min_length=1, max_length=200)
    expected_part_number: Optional[str] = Field(None, max_length=50)
    actor: str = Field(..., min_length=1, max_length=100)


class RepairVerificationResponse(BaseModel):
    id: int
    work_order_id: int
    expected_component: str
    expected_part_number: Optional[str] = None
    repair_photo_path: Optional[str] = None
    status: VerificationStatus
    confidence_score: Optional[float] = None
    verification_details: Optional[Dict[str, Any]] = None
    mismatch_reasons: Optional[List[str]] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    human_override: bool = False
    override_reason: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class WorkOrderCloseRequest(BaseModel):
    actor: str = Field(..., min_length=1, max_length=100)
    notes: Optional[str] = None