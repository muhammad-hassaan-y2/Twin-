from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum


class PlanStatus(str, Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class PartInfo(BaseModel):
    id: int
    part_number: str
    name: str
    description: Optional[str] = None
    unit_cost: Optional[float] = None
    quantity_on_hand: int
    status: str
    lead_time_days: int


class TechnicianInfo(BaseModel):
    id: int
    name: str
    email: str
    skills: List[str] = []
    status: str


class MaintenancePlanResponse(BaseModel):
    id: int
    incident_id: int
    status: PlanStatus
    
    # Fault diagnosis
    identified_failure: Optional[str] = None
    suspected_root_cause: Optional[str] = None
    
    # Parts
    recommended_part: Optional[PartInfo] = None
    part_availability: Optional[str] = None
    estimated_part_cost: Optional[float] = None
    
    # Technician
    recommended_technician: Optional[TechnicianInfo] = None
    estimated_repair_duration_hours: Optional[float] = None
    
    # Production
    proposed_downtime_start: Optional[datetime] = None
    proposed_downtime_end: Optional[datetime] = None
    
    # Risk
    risk_level: Optional[str] = None
    risk_assessment: Optional[str] = None
    
    # Work order proposal
    proposed_work_order_priority: Optional[str] = None
    proposed_work_order_notes: Optional[str] = None
    
    # Approval
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None
    
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PlanApprovalRequest(BaseModel):
    approve: bool
    reviewer: str = Field(..., min_length=1, max_length=100)
    rejection_reason: Optional[str] = None