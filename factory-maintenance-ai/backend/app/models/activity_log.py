from sqlalchemy import Column, Integer, String, Text, DateTime, JSON, ForeignKey, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    incident_id = Column(Integer, ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False, index=True)
    work_order_id = Column(Integer, ForeignKey("work_orders.id", ondelete="SET NULL"), nullable=True, index=True)
    
    # Activity details
    action = Column(String(100), nullable=False)  # e.g., "incident_created", "plan_approved", "work_order_executed"
    actor = Column(String(100), nullable=True)  # User or agent name
    actor_type = Column(String(20), nullable=True)  # "human", "agent", "system"
    description = Column(Text, nullable=True)
    details = Column(JSON, nullable=True)  # Additional structured data
    
    # State tracking
    from_status = Column(String(50), nullable=True)
    to_status = Column(String(50), nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    incident = relationship("Incident", back_populates="activity_logs")

# Composite index for common queries
Index("ix_activity_log_incident_created", "incident_id", "created_at")