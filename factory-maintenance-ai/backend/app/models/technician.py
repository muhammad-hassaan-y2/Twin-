from sqlalchemy import Column, Integer, String, Text, DateTime, Enum as SQLEnum, Boolean, JSON
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class TechnicianStatus(str, enum.Enum):
    AVAILABLE = "available"
    BUSY = "busy"
    OFF_DUTY = "off_duty"
    ON_LEAVE = "on_leave"


class Technician(Base):
    __tablename__ = "technicians"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    email = Column(String(150), nullable=False, unique=True)
    phone = Column(String(30), nullable=True)
    skills = Column(JSON, nullable=True)  # List of skill names
    certifications = Column(JSON, nullable=True)  # List of certifications
    status = Column(SQLEnum(TechnicianStatus), nullable=False, default=TechnicianStatus.AVAILABLE)
    current_work_order_id = Column(Integer, nullable=True)
    max_concurrent_jobs = Column(Integer, default=2)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    work_orders = relationship("WorkOrder", back_populates="assigned_technician")