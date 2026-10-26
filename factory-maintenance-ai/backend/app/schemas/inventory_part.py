from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class PartStatus(str, Enum):
    IN_STOCK = "in_stock"
    LOW_STOCK = "low_stock"
    OUT_OF_STOCK = "out_of_stock"
    ON_ORDER = "on_order"
    DISCONTINUED = "discontinued"


class InventoryPartResponse(BaseModel):
    id: int
    part_number: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    manufacturer: Optional[str] = None
    compatible_machines: List[str] = []
    unit_cost: Optional[float] = None
    quantity_on_hand: int
    reorder_point: int
    reorder_quantity: int
    lead_time_days: int
    status: PartStatus
    location: Optional[str] = None
    is_critical: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class InventoryPartCreate(BaseModel):
    part_number: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=1, max_length=200)
    description: Optional[str] = None
    category: Optional[str] = Field(None, max_length=100)
    manufacturer: Optional[str] = Field(None, max_length=100)
    compatible_machines: List[str] = []
    unit_cost: Optional[float] = Field(None, ge=0)
    quantity_on_hand: int = Field(0, ge=0)
    reorder_point: int = Field(5, ge=0)
    reorder_quantity: int = Field(20, ge=1)
    lead_time_days: int = Field(7, ge=0)
    location: Optional[str] = Field(None, max_length=100)
    is_critical: bool = False