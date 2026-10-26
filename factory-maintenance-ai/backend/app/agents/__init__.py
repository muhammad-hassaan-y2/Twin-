from .base import BaseAgent
from .incident_intake import IncidentIntakeAgent
from .visual_inspection import VisualInspectionAgent
from .fault_diagnosis import FaultDiagnosisAgent
from .parts_sourcing import PartsSourcingAgent
from .procurement import ProcurementAgent
from .technician_scheduling import TechnicianSchedulingAgent
from .production_coordination import ProductionCoordinationAgent
from .maintenance_planning import MaintenancePlanningAgent
from .human_approval import HumanApprovalAgent
from .work_order_execution import WorkOrderExecutionAgent
from .repair_verification import RepairVerificationAgent

__all__ = [
    "BaseAgent",
    "IncidentIntakeAgent",
    "VisualInspectionAgent",
    "FaultDiagnosisAgent",
    "PartsSourcingAgent",
    "ProcurementAgent",
    "TechnicianSchedulingAgent",
    "ProductionCoordinationAgent",
    "MaintenancePlanningAgent",
    "HumanApprovalAgent",
    "WorkOrderExecutionAgent",
    "RepairVerificationAgent",
]

# Agent registry for workflow orchestration
AGENT_REGISTRY = {
    1: IncidentIntakeAgent(),
    2: VisualInspectionAgent(),
    3: FaultDiagnosisAgent(),
    4: PartsSourcingAgent(),
    5: ProcurementAgent(),
    6: TechnicianSchedulingAgent(),
    7: ProductionCoordinationAgent(),
    8: MaintenancePlanningAgent(),
    9: HumanApprovalAgent(),
    10: WorkOrderExecutionAgent(),
    11: RepairVerificationAgent(),
}

def get_agent(order: int) -> BaseAgent:
    """Get agent by execution order."""
    return AGENT_REGISTRY.get(order)

def get_all_agents() -> list:
    """Get all agents in execution order."""
    return [AGENT_REGISTRY[i] for i in sorted(AGENT_REGISTRY.keys())]