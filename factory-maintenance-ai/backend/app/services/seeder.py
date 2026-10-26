from sqlalchemy.orm import Session
from app.models.incident import Incident, IncidentStatus, Severity
from app.models.technician import Technician, TechnicianStatus
from app.models.inventory_part import InventoryPart, PartStatus
from app.models.work_order import WorkOrder, WorkOrderStatus, WorkOrderPriority
from app.models.activity_log import ActivityLog
from datetime import datetime, timedelta
import random


def seed_database(db: Session) -> Dict[str, int]:
    """Seed database with sample data for MVP demonstration."""
    counts = {
        "technicians": 0,
        "parts": 0,
        "incidents": 0,
        "work_orders": 0
    }
    
    # Seed Technicians
    if db.query(Technician).count() == 0:
        technicians = [
            Technician(
                name="John Smith",
                email="john.smith@factory.com",
                phone="+1-555-0101",
                skills=["mechanical_repair", "hydraulic_systems", "precision_alignment", "vibration_analysis", "pump_maintenance"],
                certifications=["CMRP", "CMRT", "Vibration Analysis Cat II"],
                status=TechnicianStatus.AVAILABLE,
                max_concurrent_jobs=2
            ),
            Technician(
                name="Maria Garcia",
                email="maria.garcia@factory.com",
                phone="+1-555-0102",
                skills=["mechanical_repair", "electrical_systems", "plc_programming", "motor_repair", "instrumentation", "calibration"],
                certifications=["CMRP", "Electrician License", "PLC Programming Cert"],
                status=TechnicianStatus.AVAILABLE,
                max_concurrent_jobs=2
            ),
            Technician(
                name="Robert Chen",
                email="robert.chen@factory.com",
                phone="+1-555-0103",
                skills=["mechanical_repair", "pneumatic_systems", "valve_maintenance", "process_control", "welding", "fabrication"],
                certifications=["CMRP", "Welding Cert", "Process Control Cert"],
                status=TechnicianStatus.BUSY,
                max_concurrent_jobs=2
            ),
            Technician(
                name="Sarah Johnson",
                email="sarah.johnson@factory.com",
                phone="+1-555-0104",
                skills=["mechanical_repair", "hydraulic_systems", "fluid_power", "bearing_installation", "laser_alignment"],
                certifications=["CMRP", "Hydraulic Specialist", "Laser Alignment Cert"],
                status=TechnicianStatus.AVAILABLE,
                max_concurrent_jobs=3
            ),
            Technician(
                name="David Wilson",
                email="david.wilson@factory.com",
                phone="+1-555-0105",
                skills=["mechanical_repair", "preventive_maintenance", "lubrication_management", "root_cause_analysis", "rcm"],
                certifications=["CMRP", "CMRT", "RCM Practitioner"],
                status=TechnicianStatus.AVAILABLE,
                max_concurrent_jobs=2
            )
        ]
        db.add_all(technicians)
        db.commit()
        counts["technicians"] = len(technicians)
    
    # Seed Inventory Parts
    if db.query(InventoryPart).count() == 0:
        parts = [
            InventoryPart(
                part_number="BRG-6205-2RS",
                name="Deep Groove Ball Bearing 6205-2RS",
                description="25x52x15mm sealed ball bearing for motor applications",
                category="Bearings",
                manufacturer="SKF",
                compatible_machines=["CNC-001", "CNC-002", "LATHE-001", "MILL-001"],
                unit_cost=45.50,
                quantity_on_hand=12,
                reorder_point=5,
                reorder_quantity=20,
                lead_time_days=3,
                status=PartStatus.IN_STOCK,
                location="Aisle A, Shelf 3",
                is_critical=True
            ),
            InventoryPart(
                part_number="SEAL-VITON-45x60x8",
                name="Viton Shaft Seal 45x60x8mm",
                description="High-temperature Viton lip seal for hydraulic pumps",
                category="Seals",
                manufacturer="Trelleborg",
                compatible_machines=["CNC-001", "PRESS-001", "PUMP-001"],
                unit_cost=28.75,
                quantity_on_hand=8,
                reorder_point=4,
                reorder_quantity=15,
                lead_time_days=5,
                status=PartStatus.IN_STOCK,
                location="Aisle B, Shelf 1",
                is_critical=True
            ),
            InventoryPart(
                part_number="FLTR-HYD-10MIC",
                name="Hydraulic Filter Element 10 Micron",
                description="10 micron hydraulic filter element for main system",
                category="Filters",
                manufacturer="Parker",
                compatible_machines=["CNC-001", "CNC-002", "PRESS-001", "PRESS-002"],
                unit_cost=35.00,
                quantity_on_hand=25,
                reorder_point=10,
                reorder_quantity=30,
                lead_time_days=2,
                status=PartStatus.IN_STOCK,
                location="Aisle C, Shelf 2",
                is_critical=False
            ),
            InventoryPart(
                part_number="PUMP-GEAR-25CC",
                name="Gear Pump 25cc/rev",
                description="External gear pump 25cc/rev for hydraulic power unit",
                category="Pumps",
                manufacturer="Bosch Rexroth",
                compatible_machines=["PRESS-001", "PRESS-002"],
                unit_cost=1250.00,
                quantity_on_hand=2,
                reorder_point=1,
                reorder_quantity=3,
                lead_time_days=14,
                status=PartStatus.LOW_STOCK,
                location="Aisle D, Shelf 1",
                is_critical=True
            ),
            InventoryPart(
                part_number="MOTOR-AC-15KW",
                name="AC Induction Motor 15kW 4-pole",
                description="15kW 4-pole IE3 efficiency AC motor",
                category="Motors",
                manufacturer="Siemens",
                compatible_machines=["CNC-001", "CNC-002", "MILL-001", "FAN-001"],
                unit_cost=2800.00,
                quantity_on_hand=1,
                reorder_point=1,
                reorder_quantity=2,
                lead_time_days=21,
                status=PartStatus.LOW_STOCK,
                location="Aisle E, Shelf 1",
                is_critical=True
            ),
            InventoryPart(
                part_number="BELT-TIMING-8M-640",
                name="Timing Belt 8M-640",
                description="8mm pitch timing belt 640mm length",
                category="Belts",
                manufacturer="Gates",
                compatible_machines=["LATHE-001", "MILL-001", "GRIND-001"],
                unit_cost=85.00,
                quantity_on_hand=0,
                reorder_point=3,
                reorder_quantity=10,
                lead_time_days=7,
                status=PartStatus.OUT_OF_STOCK,
                location="Aisle F, Shelf 2",
                is_critical=False
            ),
            InventoryPart(
                part_number="CPLG-JAW-L095",
                name="Jaw Coupling L095",
                description="L095 jaw coupling with spider element",
                category="Couplings",
                manufacturer="Lovejoy",
                compatible_machines=["PUMP-001", "PUMP-002", "FAN-001", "COMP-001"],
                unit_cost=42.00,
                quantity_on_hand=15,
                reorder_point=5,
                reorder_quantity=20,
                lead_time_days=3,
                status=PartStatus.IN_STOCK,
                location="Aisle A, Shelf 5",
                is_critical=False
            ),
            InventoryPart(
                part_number="VLV-SOL-24VDC",
                name="Solenoid Valve 24VDC 3/2-way",
                description="3/2-way solenoid valve 24VDC for pneumatic control",
                category="Valves",
                manufacturer="Festo",
                compatible_machines=["CNC-001", "CNC-002", "ASM-001"],
                unit_cost=95.00,
                quantity_on_hand=6,
                reorder_point=3,
                reorder_quantity=10,
                lead_time_days=5,
                status=PartStatus.IN_STOCK,
                location="Aisle B, Shelf 3",
                is_critical=False
            ),
            InventoryPart(
                part_number="SNSR-PRESS-0-100BAR",
                name="Pressure Sensor 0-100 Bar",
                description="Industrial pressure transmitter 0-100 bar 4-20mA",
                category="Sensors",
                manufacturer="IFM",
                compatible_machines=["PRESS-001", "PRESS-002", "PUMP-001"],
                unit_cost=180.00,
                quantity_on_hand=4,
                reorder_point=2,
                reorder_quantity=5,
                lead_time_days=7,
                status=PartStatus.IN_STOCK,
                location="Aisle C, Shelf 4",
                is_critical=True
            ),
            InventoryPart(
                part_number="GSKT-SPIRAL-300MM",
                name="Spiral Wound Gasket 300mm",
                description="300mm spiral wound gasket SS316/Graphite for flange",
                category="Gaskets",
                manufacturer="Flexitallic",
                compatible_machines=["PRESS-001", "PRESS-002", "VES-001"],
                unit_cost=65.00,
                quantity_on_hand=10,
                reorder_point=4,
                reorder_quantity=15,
                lead_time_days=5,
                status=PartStatus.IN_STOCK,
                location="Aisle B, Shelf 2",
                is_critical=False
            )
        ]
        db.add_all(parts)
        db.commit()
        counts["parts"] = len(parts)
    
    # Seed Historical Incidents
    if db.query(Incident).count() == 0:
        incidents = [
            Incident(
                machine_id="CNC-001",
                machine_name="CNC Machining Center #1",
                location="Production Line A, Station 3",
                failure_description="Spindle bearing overheating and unusual vibration detected during operation",
                severity=Severity.HIGH,
                status=IncidentStatus.CLOSED,
                photo_path=None,
                created_at=datetime.utcnow() - timedelta(days=30),
                updated_at=datetime.utcnow() - timedelta(days=25)
            ),
            Incident(
                machine_id="PRESS-001",
                machine_name="Hydraulic Press 500T",
                location="Production Line B, Station 1",
                failure_description="Hydraulic cylinder seal failure causing oil leak and pressure loss",
                severity=Severity.CRITICAL,
                status=IncidentStatus.CLOSED,
                photo_path=None,
                created_at=datetime.utcnow() - timedelta(days=15),
                updated_at=datetime.utcnow() - timedelta(days=10)
            ),
            Incident(
                machine_id="PUMP-001",
                machine_name="Coolant Pump Station",
                location="Utility Room",
                failure_description="Pump coupling wear causing misalignment and vibration",
                severity=Severity.MEDIUM,
                status=IncidentStatus.CLOSED,
                photo_path=None,
                created_at=datetime.utcnow() - timedelta(days=7),
                updated_at=datetime.utcnow() - timedelta(days=3)
            ),
            Incident(
                machine_id="CNC-002",
                machine_name="CNC Machining Center #2",
                location="Production Line A, Station 4",
                failure_description="Tool changer pneumatic valve stuck, unable to change tools",
                severity=Severity.HIGH,
                status=IncidentStatus.INVESTIGATING,
                photo_path=None,
                created_at=datetime.utcnow() - timedelta(hours=2),
                updated_at=datetime.utcnow() - timedelta(hours=1)
            )
        ]
        db.add_all(incidents)
        db.commit()
        counts["incidents"] = len(incidents)
        
        # Add activity logs for historical incidents
        for inc in incidents:
            if inc.status == IncidentStatus.CLOSED:
                logs = [
                    ActivityLog(incident_id=inc.id, action="incident_created", actor="Operator", actor_type="human", description=f"Incident reported for {inc.machine_name}", from_status=None, to_status="submitted", created_at=inc.created_at),
                    ActivityLog(incident_id=inc.id, action="investigation_complete", actor="Agent System", actor_type="agent", description="All 11 agents completed investigation", from_status="investigating", to_status="plan_proposed", created_at=inc.created_at + timedelta(hours=1)),
                    ActivityLog(incident_id=inc.id, action="plan_approved", actor="Maintenance Manager", actor_type="human", description="Maintenance plan approved", from_status="plan_proposed", to_status="approved", created_at=inc.created_at + timedelta(hours=2)),
                    ActivityLog(incident_id=inc.id, action="work_order_created", actor="Agent System", actor_type="agent", description="Work order created and assigned", from_status="approved", to_status="work_order_created", created_at=inc.created_at + timedelta(hours=3)),
                    ActivityLog(incident_id=inc.id, action="work_order_started", actor="Technician", actor_type="human", description="Repair work started", from_status="work_order_created", to_status="in_progress", created_at=inc.created_at + timedelta(hours=4)),
                    ActivityLog(incident_id=inc.id, action="work_order_completed", actor="Technician", actor_type="human", description="Repair completed, awaiting verification", from_status="in_progress", to_status="awaiting_verification", created_at=inc.created_at + timedelta(hours=8)),
                    ActivityLog(incident_id=inc.id, action="verification_passed", actor="Agent System", actor_type="agent", description="Repair verified successfully", from_status="awaiting_verification", to_status="verified", created_at=inc.created_at + timedelta(hours=9)),
                    ActivityLog(incident_id=inc.id, action="work_order_closed", actor="Maintenance Manager", actor_type="human", description="Work order closed", from_status="verified", to_status="closed", created_at=inc.updated_at),
                ]
                db.add_all(logs)
        db.commit()
    
    return counts


def reset_database(db: Session) -> Dict[str, int]:
    """Reset database by clearing all data and re-seeding."""
    from app.models import Incident, AgentRun, MaintenancePlan, Technician, InventoryPart, WorkOrder, RepairVerification, ActivityLog
    from app.database import Base
    from app.database import engine
    
    # Drop all tables and recreate
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    return seed_database(db)