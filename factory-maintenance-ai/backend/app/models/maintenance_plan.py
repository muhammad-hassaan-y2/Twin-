from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class PlanStatus(str, enum.Enum):
    DRAFT = "draft"
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    status = Column(SQLEnum(PlanStatus), nullable=False, default=PlanStatus.DRAFT)
    
    # Fault diagnosis results
    identified_failure = Column(Text, nullable=True)
    suspected_root_cause = Column(Text, nullable=True)
    
    # Parts information
    recommended_part_id = Column(Integer, ForeignKey("inventory_parts.id", ondelete="SET NULL"), nullable=True)
    part_availability = Column(String(50), nullable=True)  # available, unavailable, partial
    estimated_part_cost = Column(Float, nullable=True)
    
    # Technician information
    recommended_technician_id = Column(Integer, ForeignKey("technicians.id", ondelete="SET NULL"), nullable=True)
    estimated_repair_duration_hours = Column(Float, nullable=True)
    
    # Production coordination
    proposed_downtime_start = Column(DateTime(timezone=True), nullable=True)
    proposed_downtime_end = Column(DateTime(timezone=True), nullable=True)
    
    # Risk assessment
    risk_level = Column(String(20), nullable=True)  # low, medium, high
    risk_assessment = Column(Text, nullable=True)
    
    # Work order proposal
    proposed_work_order_priority = Column(String(20), nullable=True)
    proposed_work_order_notes = Column(Text, nullable=True)
    
    # Human approval
    approved_by = Column(String(100), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    rejection_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    incident = relationship("Incident", back_populates="maintenance_plan")
    recommended_part = relationship("InventoryPart", foreign_keys=[recommended_part_id])
    recommended_technician = relationship("Technician", foreign_keys=[recommended_technician_id])