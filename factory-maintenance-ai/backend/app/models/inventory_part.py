from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Integer as SQLInteger, Boolean, JSON, Enum as SQLEnum
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base
import enum


class PartStatus(str, enum.Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    ON_ORDER = "on_order"
    DISCONTINUED = "discontinued"


class InventoryPart(Base):
    __tablename__ = "inventory_parts"

    id = Column(Integer, primary_key=True, index=True)
    part_number = Column(String(50), nullable=False, unique=True, index=True)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    category = Column(String(100), nullable=True)
    manufacturer = Column(String(100), nullable=True)
    compatible_machines = Column(JSON, nullable=True)  # List of machine IDs
    unit_cost = Column(Float, nullable=True)
    quantity_on_hand = Column(SQLInteger, default=0)
    reorder_point = Column(SQLInteger, default=5)
    reorder_quantity = Column(SQLInteger, default=20)
    lead_time_days = Column(SQLInteger, default=7)
    status = Column(SQLEnum(PartStatus), nullable=False, default=PartStatus.IN_STOCK)
    location = Column(String(100), nullable=True)  # Warehouse location
    is_critical = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    work_orders = relationship("WorkOrder", back_populates="replacement_part")