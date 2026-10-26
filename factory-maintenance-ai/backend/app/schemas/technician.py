from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional, List
from datetime import datetime
from enum import Enum


class TechnicianStatus(str, Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFF_DUTY = "off_duty"
    ON_LEAVE = "on_leave"


class TechnicianResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: Optional[str] = None
    skills: List[str] = []
    certifications: List[str] = []
    status: TechnicianStatus
    current_work_order_id: Optional[int] = None
    max_concurrent_jobs: int
    is_active: bool
    created_at: datetime
    updated_at: datetime

    @field_validator('skills', 'certifications', mode='before')
    @classmethod
    def default_empty_list(cls, v):
        if v is None:
            return []
        return v

    class Config:
        from_attributes = True


class TechnicianCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr
    phone: Optional[str] = Field(None, max_length=30)
    skills: List[str] = []
    certifications: List[str] = []
    max_concurrent_jobs: int = Field(2, ge=1, le=10)