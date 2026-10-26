from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Float, Boolean
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class IncidentStatus(str, enum.Enum):
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


class Severity(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, index=True)
    machine_id = Column(String(100), nullable=False, index=True)
    machine_name = Column(String(200), nullable=False)
    location = Column(String(200), nullable=False)
    failure_description = Column(Text, nullable=False)
    severity = Column(SQLEnum(Severity), nullable=False, default=Severity.MEDIUM)
    status = Column(SQLEnum(IncidentStatus), nullable=False, default=IncidentStatus.SUBMITTED)
    photo_path = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Relationships
    agent_runs = relationship("AgentRun", back_populates="incident", cascade="all, delete-orphan")
    maintenance_plan = relationship("MaintenancePlan", back_populates="incident", uselist=False, cascade="all, delete-orphan")
    work_orders = relationship("WorkOrder", back_populates="incident", cascade="all, delete-orphan")
    activity_logs = relationship("ActivityLog", back_populates="incident", cascade="all, delete-orphan")