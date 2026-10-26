from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class WorkOrderStatus(str, enum.Enum):
    CREATED = "created"
    SCHEDULED = "scheduled"
    IN_PROGRESS = "in_progress"
    AWAITING_VERIFICATION = "awaiting_verification"
    VERIFIED = "verified"
    CLOSED = "closed"
    REJECTED = "rejected"
    ON_HOLD = "on_hold"


class WorkOrderPriority(str, enum.Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(Integer, primary_key=True, index=True)
    work_order_number = Column(String(50), nullable=False, unique=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    maintenance_plan_id = Column(Integer, ForeignKey("maintenance_plans.id", ondelete="SET NULL"), nullable=True)
    
    # Assignment
    assigned_technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True)
    replacement_part_id = Column(Integer, ForeignKey("inventory_parts.id", ondelete="SET NULL"), nullable=True)
    
    # Details
    priority = Column(SQLEnum(WorkOrderPriority), nullable=False, default=WorkOrderPriority.MEDIUM)
    status = Column(SQLEnum(WorkOrderStatus), nullable=False, default=WorkOrderStatus.CREATED)
    
    # Scheduling
    scheduled_start = Column(DateTime(timezone=True), nullable=True)
    scheduled_end = Column(DateTime(timezone=True), nullable=True)
    actual_start = Column(DateTime(timezone=True), nullable=True)
    actual_end = Column(DateTime(timezone=True), nullable=True)
    
    # Progress
    progress_notes = Column(Text, nullable=True)
    completion_notes = Column(Text, nullable=True)
    
    # Approval tracking
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    incident = relationship("Incident", back_populates="work_orders")
    assigned_technician = relationship("Technician", back_populates="work_orders")
    replacement_part = relationship("InventoryPart", back_populates="work_orders")
    repair_verification = relationship("RepairVerification", back_populates="work_order", uselist=False, cascade="all, delete-orphan")