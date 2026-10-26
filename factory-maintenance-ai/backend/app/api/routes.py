from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
import os

from app.database import get_db
from app.config import settings
from app.services.file_upload import file_upload_service
from app.services.workflow import run_incident_investigation, WorkflowService
from app.services.seeder import seed_database
from app.agents import get_agent, HumanApprovalAgent, WorkOrderExecutionAgent, RepairVerificationAgent
from app.models.incident import Incident, IncidentStatus, Severity
from app.models.agent_run import AgentRun
from app.models.maintenance_plan import MaintenancePlan, PlanStatus
from app.models.technician import Technician, TechnicianStatus
from app.models.inventory_part import InventoryPart, PartStatus
from app.models.work_order import WorkOrder, WorkOrderStatus, WorkOrderPriority
from app.models.repair_verification import RepairVerification, VerificationStatus
from app.models.activity_log import ActivityLog
from app.schemas.incident import IncidentCreate, IncidentResponse, IncidentListResponse
from app.schemas.agent_run import AgentRunListResponse, AgentRunResponse
from app.schemas.maintenance_plan import MaintenancePlanResponse, PlanApprovalRequest
from app.schemas.technician import TechnicianResponse, TechnicianCreate
from app.schemas.inventory_part import InventoryPartResponse, InventoryPartCreate
from app.schemas.work_order import WorkOrderResponse, WorkOrderListResponse, WorkOrderExecuteRequest
from app.schemas.repair_verification import RepairVerificationRequest, RepairVerificationResponse, WorkOrderCloseRequest
from app.schemas.activity_log import ActivityLogResponse
from app.schemas.dashboard import DashboardMetricsResponse, HealthResponse

router = APIRouter(prefix=settings.API_V1_PREFIX)


# Health Check
@router.get("/health", response_model=HealthResponse)
def health_check():
    return HealthResponse(
        status="healthy",
        version="1.0.0",
        database="connected"
    )


# Dashboard
@router.get("/dashboard", response_model=DashboardMetricsResponse)
def get_dashboard(db: Session = Depends(get_db)):
    total_incidents = db.query(Incident).count()
    active_work_orders = db.query(WorkOrder).filter(
        WorkOrder.status.in_([WorkOrderStatus.CREATED, WorkOrderStatus.SCHEDULED, WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.AWAITING_VERIFICATION])
    ).count()
    pending_approvals = db.query(MaintenancePlan).filter(MaintenancePlan.status == PlanStatus.PROPOSED).count()
    repairs_awaiting_verification = db.query(WorkOrder).filter(WorkOrder.status == WorkOrderStatus.AWAITING_VERIFICATION).count()
    
    recent_incidents = db.query(Incident).order_by(Incident.created_at.desc()).limit(5).all()
    recent_activity = db.query(ActivityLog).order_by(ActivityLog.created_at.desc()).limit(10).all()
    
    # Agent execution summary
    agent_summary = {}
    for incident in db.query(Incident).all():
        runs = db.query(AgentRun).filter(AgentRun.incident_id == incident.id).all()
        for run in runs:
            key = run.agent_name
            if key not in agent_summary:
                agent_summary[key] = {"completed": 0, "failed": 0, "pending": 0}
            status = run.status.value if hasattr(run.status, 'value') else str(run.status)
            agent_summary[key][status] = agent_summary[key].get(status, 0) + 1
    
    return DashboardMetricsResponse(
        total_incidents=total_incidents,
        active_work_orders=active_work_orders,
        pending_approvals=pending_approvals,
        repairs_awaiting_verification=repairs_awaiting_verification,
        recent_incidents=[IncidentListResponse.model_validate(i) for i in recent_incidents],
        recent_activity=[ActivityLogResponse.model_validate(a) for a in recent_activity],
        agent_execution_summary=agent_summary
    )


# Activity Log
@router.get("/activity", response_model=List[ActivityLogResponse])
def get_activity(incident_id: Optional[int] = None, limit: int = 50, db: Session = Depends(get_db)):
    query = db.query(ActivityLog)
    if incident_id:
        query = query.filter(ActivityLog.incident_id == incident_id)
    return [ActivityLogResponse.model_validate(a) for a in query.order_by(ActivityLog.created_at.desc()).limit(limit).all()]


# Incidents
@router.post("/incidents", response_model=IncidentResponse)
async def create_incident(
    machine_id: str = Form(...),
    machine_name: str = Form(...),
    location: str = Form(...),
    failure_description: str = Form(...),
    severity: Severity = Form(Severity.MEDIUM),
    photo: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    # Validate and save photo
    photo_path = await file_upload_service.save_file(photo, prefix="incident_")
    
    # Create incident
    incident = Incident(
        machine_id=machine_id,
        machine_name=machine_name,
        location=location,
        failure_description=failure_description,
        severity=severity,
        photo_path=photo_path,
        status=IncidentStatus.SUBMITTED
    )
    db.add(incident)
    db.commit()
    db.refresh(incident)
    
    # Log activity
    log = ActivityLog(
        incident_id=incident.id,
        action="incident_created",
        actor="Operator",
        actor_type="human",
        description=f"New incident reported for {machine_name}",
        from_status=None,
        to_status="submitted"
    )
    db.add(log)
    db.commit()
    
    return IncidentResponse.model_validate(incident)


@router.get("/incidents", response_model=List[IncidentListResponse])
def list_incidents(
    status: Optional[IncidentStatus] = None,
    severity: Optional[Severity] = None,
    machine_id: Optional[str] = None,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    query = db.query(Incident)
    if status:
        query = query.filter(Incident.status == status)
    if severity:
        query = query.filter(Incident.severity == severity)
    if machine_id:
        query = query.filter(Incident.machine_id == machine_id)
    return [IncidentListResponse.model_validate(i) for i in query.order_by(Incident.created_at.desc()).limit(limit).all()]


@router.get("/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    return IncidentResponse.model_validate(incident)


@router.post("/incidents/{incident_id}/investigate")
async def start_investigation(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    if incident.status not in [IncidentStatus.SUBMITTED, IncidentStatus.INVESTIGATING]:
        raise HTTPException(status_code=400, detail=f"Cannot investigate incident in status: {incident.status}")
    
    result = await run_incident_investigation(db, incident_id)
    return result


@router.get("/incidents/{incident_id}/agents", response_model=AgentRunListResponse)
def get_agent_statuses(incident_id: int, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    runs = db.query(AgentRun).filter(AgentRun.incident_id == incident_id).order_by(AgentRun.agent_order).all()
    
    service = WorkflowService(db)
    summary = service.get_workflow_summary(incident_id)
    
    return AgentRunListResponse(
        agents=[AgentRunResponse.model_validate(r) for r in runs],
        overall_status=summary["overall_status"],
        completed_count=summary["completed"],
        total_count=summary["total_agents"]
    )


@router.get("/incidents/{incident_id}/plan", response_model=MaintenancePlanResponse)
def get_maintenance_plan(incident_id: int, db: Session = Depends(get_db)):
    plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Maintenance plan not found")
    
    # Build response dict manually to handle nested objects properly
    part_info = None
    if plan.recommended_part:
        part_info = {
            "id": plan.recommended_part.id,
            "part_number": plan.recommended_part.part_number,
            "name": plan.recommended_part.name,
            "description": plan.recommended_part.description,
            "unit_cost": plan.recommended_part.unit_cost,
            "quantity_on_hand": plan.recommended_part.quantity_on_hand,
            "status": plan.recommended_part.status.value if hasattr(plan.recommended_part.status, 'value') else str(plan.recommended_part.status),
            "lead_time_days": plan.recommended_part.lead_time_days
        }
    
    tech_info = None
    if plan.recommended_technician:
        tech_info = {
            "id": plan.recommended_technician.id,
            "name": plan.recommended_technician.name,
            "email": plan.recommended_technician.email,
            "skills": plan.recommended_technician.skills or [],
            "status": plan.recommended_technician.status.value if hasattr(plan.recommended_technician.status, 'value') else str(plan.recommended_technician.status)
        }
    
    # Create response dict
    response_data = {
        "id": plan.id,
        "incident_id": plan.incident_id,
        "status": plan.status,
        "identified_failure": plan.identified_failure,
        "suspected_root_cause": plan.suspected_root_cause,
        "recommended_part": part_info,
        "part_availability": plan.part_availability,
        "estimated_part_cost": plan.estimated_part_cost,
        "recommended_technician": tech_info,
        "estimated_repair_duration_hours": plan.estimated_repair_duration_hours,
        "proposed_downtime_start": plan.proposed_downtime_start,
        "proposed_downtime_end": plan.proposed_downtime_end,
        "risk_level": plan.risk_level,
        "risk_assessment": plan.risk_assessment,
        "proposed_work_order_priority": plan.proposed_work_order_priority,
        "proposed_work_order_notes": plan.proposed_work_order_notes,
        "approved_by": plan.approved_by,
        "approved_at": plan.approved_at,
        "rejection_reason": plan.rejection_reason,
        "created_at": plan.created_at,
        "updated_at": plan.updated_at,
    }
    
    return MaintenancePlanResponse.model_validate(response_data)


@router.post("/incidents/{incident_id}/approve")
def approve_plan(incident_id: int, request: PlanApprovalRequest, db: Session = Depends(get_db)):
    incident = db.query(Incident).filter(Incident.id == incident_id).first()
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    
    plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Maintenance plan not found")
    
    if plan.status != PlanStatus.PROPOSED:
        raise HTTPException(status_code=400, detail=f"Plan is not in proposed status: {plan.status}")
    
    approval_agent = HumanApprovalAgent()
    approval_result = approval_agent.process_approval(db, incident_id, request.approve, request.reviewer, request.rejection_reason)
    
    if request.approve and approval_result.get("approved"):
        # Auto-create work order after approval
        # Check if work order already exists
        existing_wo = db.query(WorkOrder).filter(WorkOrder.incident_id == incident_id).first()
        if existing_wo:
            return approval_result
        
        # Determine technician and part from plan
        tech_id = plan.recommended_technician_id
        part_id = plan.recommended_part_id
        
        # Generate work order number
        wo_count = db.query(WorkOrder).count()
        wo_number = f"WO-{datetime.now().strftime('%Y%m%d')}-{wo_count + 1:04d}"
        
        # Determine priority from plan
        priority = WorkOrderPriority.MEDIUM
        if plan.proposed_work_order_priority:
            try:
                priority = WorkOrderPriority(plan.proposed_work_order_priority)
            except ValueError:
                priority = WorkOrderPriority.MEDIUM
        
        # Create work order
        work_order = WorkOrder(
            work_order_number=wo_number,
            incident_id=incident_id,
            maintenance_plan_id=plan.id,
            assigned_technician_id=tech_id,
            replacement_part_id=part_id,
            priority=priority,
            status=WorkOrderStatus.CREATED,
            approved_by=plan.approved_by,
            approved_at=plan.approved_at
        )
        
        db.add(work_order)
        db.commit()
        
        # Update technician status if assigned
        if tech_id:
            tech = db.query(Technician).filter(Technician.id == tech_id).first()
            if tech:
                tech.status = TechnicianStatus.BUSY
                db.commit()
        
        # Update part status if part is available
        if part_id:
            part = db.query(InventoryPart).filter(InventoryPart.id == part_id).first()
            if part and part.quantity_on_hand > 0:
                part.quantity_on_hand -= 1
                part.status = PartStatus.LOW_STOCK if part.quantity_on_hand <= part.reorder_point else PartStatus.IN_STOCK
                db.commit()
    
    return approval_result


# Technicians
@router.get("/technicians", response_model=List[TechnicianResponse])
def list_technicians(active_only: bool = True, db: Session = Depends(get_db)):
    query = db.query(Technician)
    if active_only:
        query = query.filter(Technician.is_active == True)
    return [TechnicianResponse.model_validate(t) for t in query.all()]


@router.post("/technicians", response_model=TechnicianResponse)
def create_technician(technician: TechnicianCreate, db: Session = Depends(get_db)):
    db_tech = Technician(**technician.model_dump())
    db.add(db_tech)
    db.commit()
    db.refresh(db_tech)
    return TechnicianResponse.model_validate(db_tech)


# Inventory Parts
@router.get("/parts", response_model=List[InventoryPartResponse])
def list_parts(
    status: Optional[str] = None,
    machine_id: Optional[str] = None,
    critical_only: bool = False,
    db: Session = Depends(get_db)
):
    query = db.query(InventoryPart)
    if status:
        query = query.filter(InventoryPart.status == status)
    if machine_id:
        query = query.filter(InventoryPart.compatible_machines.contains([machine_id]))
    if critical_only:
        query = query.filter(InventoryPart.is_critical == True)
    return [InventoryPartResponse.model_validate(p) for p in query.all()]


@router.post("/parts", response_model=InventoryPartResponse)
def create_part(part: InventoryPartCreate, db: Session = Depends(get_db)):
    # Check for duplicate part number
    existing = db.query(InventoryPart).filter(InventoryPart.part_number == part.part_number).first()
    if existing:
        raise HTTPException(status_code=400, detail="Part number already exists")
    
    db_part = InventoryPart(**part.model_dump())
    db.add(db_part)
    db.commit()
    db.refresh(db_part)
    return InventoryPartResponse.model_validate(db_part)


# Work Orders
@router.get("/work-orders", response_model=List[WorkOrderListResponse])
def list_work_orders(
    status: Optional[WorkOrderStatus] = None,
    priority: Optional[WorkOrderPriority] = None,
    technician_id: Optional[int] = None,
    db: Session = Depends(get_db)
):
    query = db.query(WorkOrder)
    if status:
        query = query.filter(WorkOrder.status == status)
    if priority:
        query = query.filter(WorkOrder.priority == priority)
    if technician_id:
        query = query.filter(WorkOrder.assigned_technician_id == technician_id)
    
    work_orders = query.order_by(WorkOrder.created_at.desc()).all()
    
    result = []
    for wo in work_orders:
        # Build response manually to handle relationship data
        wo_dict = {
            "id": wo.id,
            "work_order_number": wo.work_order_number,
            "incident_id": wo.incident_id,
            "machine_id": wo.incident.machine_id if wo.incident else "",
            "machine_name": wo.incident.machine_name if wo.incident else "",
            "assigned_technician": wo.assigned_technician.name if wo.assigned_technician else "",
            "replacement_part": wo.replacement_part.part_number if wo.replacement_part else "",
            "priority": wo.priority,
            "status": wo.status,
            "scheduled_start": wo.scheduled_start,
            "scheduled_end": wo.scheduled_end,
        }
        result.append(WorkOrderListResponse(**wo_dict))
    
    return result


@router.get("/work-orders/{work_order_id}", response_model=WorkOrderResponse)
def get_work_order(work_order_id: int, db: Session = Depends(get_db)):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    response = WorkOrderResponse.model_validate(wo)
    if wo.incident:
        response.incident = {"id": wo.incident.id, "machine_id": wo.incident.machine_id, "machine_name": wo.incident.machine_name}
    if wo.assigned_technician:
        response.technician = {"id": wo.assigned_technician.id, "name": wo.assigned_technician.name, "email": wo.assigned_technician.email}
    if wo.replacement_part:
        response.part = {"id": wo.replacement_part.id, "part_number": wo.replacement_part.part_number, "name": wo.replacement_part.name}
    
    return response


@router.post("/work-orders/{work_order_id}/execute")
def execute_work_order(work_order_id: int, request: WorkOrderExecuteRequest, db: Session = Depends(get_db)):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    execution_agent = WorkOrderExecutionAgent()
    try:
        result = execution_agent.advance_work_order(db, work_order_id, request.action, request.actor, request.notes)
        return result
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# Repair Verification
@router.post("/work-orders/{work_order_id}/verification")
async def upload_verification_photo(
    work_order_id: int,
    expected_component: str = Form(...),
    expected_part_number: str = Form(None),
    photo: UploadFile = File(...),
    actor: str = Form(...),
    db: Session = Depends(get_db)
):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    if wo.status != WorkOrderStatus.AWAITING_VERIFICATION:
        raise HTTPException(status_code=400, detail=f"Work order not awaiting verification. Current status: {wo.status}")
    
    # Save photo
    photo_path = await file_upload_service.save_file(photo, prefix=f"verification_wo{work_order_id}_")
    
    # Run verification
    verification_agent = RepairVerificationAgent()
    result = verification_agent.run_verification(
        db, work_order_id, expected_component, expected_part_number, photo_path, actor
    )
    
    return result


@router.post("/work-orders/{work_order_id}/close")
def close_work_order(work_order_id: int, request: WorkOrderCloseRequest, db: Session = Depends(get_db)):
    wo = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
    if not wo:
        raise HTTPException(status_code=404, detail="Work order not found")
    
    verification = db.query(RepairVerification).filter(RepairVerification.work_order_id == work_order_id).first()
    if not verification or verification.status != VerificationStatus.VERIFIED:
        raise HTTPException(status_code=400, detail="Work order cannot be closed - repair not verified")
    
    wo.status = WorkOrderStatus.CLOSED
    incident = db.query(Incident).filter(Incident.id == wo.incident_id).first()
    if incident:
        incident.status = IncidentStatus.CLOSED
    
    log = ActivityLog(
        incident_id=wo.incident_id,
        work_order_id=work_order_id,
        action="work_order_closed",
        actor=request.actor,
        actor_type="human",
        description=f"Work order {wo.work_order_number} closed after successful verification",
        details={"notes": request.notes},
        from_status="verified",
        to_status="closed"
    )
    db.add(log)
    db.commit()
    
    return {"message": "Work order closed successfully", "work_order_id": work_order_id}


# Admin/Utility
@router.post("/admin/seed")
def seed_db(db: Session = Depends(get_db)):
    counts = seed_database(db)
    return {"message": "Database seeded successfully", "counts": counts}


@router.post("/admin/reset")
def reset_db(db: Session = Depends(get_db)):
    from app.services.seeder import reset_database
    counts = reset_database(db)
    return {"message": "Database reset and seeded successfully", "counts": counts}


# File serving
@router.get("/files/{filename}")
def serve_file(filename: str):
    file_path = os.path.join(settings.UPLOAD_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    from fastapi.responses import FileResponse
    return FileResponse(file_path)