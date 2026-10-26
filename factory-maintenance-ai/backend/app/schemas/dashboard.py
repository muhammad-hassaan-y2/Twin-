from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from .incident import IncidentListResponse
from .work_order import WorkOrderListResponse
from .activity_log import ActivityLogResponse


class DashboardMetricsResponse(BaseModel):
    total_incidents: int
    active_work_orders: int
    pending_approvals: int
    repairs_awaiting_verification: int
    recent_incidents: List[IncidentListResponse]
    recent_activity: List[ActivityLogResponse]
    agent_execution_summary: dict


class HealthResponse(BaseModel):
    status: str
    version: str
    database: str