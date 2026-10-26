from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, ForeignKey, Boolean, Float, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class VerificationStatus(str, enum.Enum):
    PENDING = "pending"
    VERIFIED = "verified"
    FAILED = "failed"
    INCONCLUSIVE = "inconclusive"


class RepairVerification(Base):
    __tablename__ = "repair_verifications"

    id = Column(Integer, primary_key=True, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    # Expected vs Actual
    expected_component = Column(String(200), nullable=False)
    expected_part_number = Column(String(50), nullable=True)
    
    # Uploaded photo
    repair_photo_path = Column(String(500), nullable=True)
    
    # Verification results
    status = Column(SQLEnum(VerificationStatus), nullable=False, default=VerificationStatus.PENDING)
    confidence_score = Column(Float, nullable=True)
    verification_details = Column(JSON, nullable=True)  # Detailed comparison results
    mismatch_reasons = Column(JSON, nullable=True)  # List of mismatch reasons if failed
    
    # Human review
    reviewed_by = Column(String(100), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    human_override = Column(Boolean, default=False)
    override_reason = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    work_order = relationship("WorkOrder", back_populates="repair_verification")