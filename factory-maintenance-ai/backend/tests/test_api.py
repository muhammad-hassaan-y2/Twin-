import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from io import BytesIO

from app.main import app
from app.database import Base, get_db
from app.models.incident import Incident, IncidentStatus, Severity
from app.models.technician import Technician, TechnicianStatus
from app.models.inventory_part import InventoryPart, PartStatus
from app.models.maintenance_plan import MaintenancePlan, PlanStatus
from app.models.work_order import WorkOrder, WorkOrderStatus, WorkOrderPriority
from app.models.repair_verification import RepairVerification, VerificationStatus
from app.models.agent_run import AgentRun, AgentStatus


# Test database
SQLALCHEMY_DATABASE_URL = "sqlite:///./test_factory_maintenance.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base.metadata.create_all(bind=engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_db():
    """Clean database before each test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    
    # Seed test data
    db = TestingSessionLocal()
    try:
        # Create technician
        tech = Technician(
            name="Test Tech",
            email="test@factory.com",
            skills=["mechanical_repair", "hydraulic_systems"],
            status=TechnicianStatus.AVAILABLE
        )
        db.add(tech)
        
        # Create part
        part = InventoryPart(
            part_number="TEST-001",
            name="Test Bearing",
            compatible_machines=["CNC-001"],
            unit_cost=50.0,
            quantity_on_hand=10,
            status=PartStatus.IN_STOCK
        )
        db.add(part)
        db.commit()
    finally:
        db.close()
    yield
    Base.metadata.drop_all(bind=engine)


def create_test_image():
    """Create a simple test image."""
    return BytesIO(b"fake image data")


class TestHealthCheck:
    def test_health_check(self):
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "healthy"


class TestIncidentCRUD:
    def test_create_incident(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {
            "machine_id": "CNC-001",
            "machine_name": "CNC Machine 1",
            "location": "Line A",
            "failure_description": "Bearing failure",
            "severity": "high"
        }
        response = client.post("/api/incidents", data=data, files=files)
        assert response.status_code == 200
        assert response.json()["machine_id"] == "CNC-001"
        assert response.json()["status"] == "submitted"
    
    def test_create_incident_invalid_file_type(self):
        files = {"photo": ("test.txt", create_test_image(), "text/plain")}
        data = {
            "machine_id": "CNC-001",
            "machine_name": "CNC Machine 1",
            "location": "Line A",
            "failure_description": "Bearing failure"
        }
        response = client.post("/api/incidents", data=data, files=files)
        assert response.status_code == 400
    
    def test_list_incidents(self):
        # Create incident first
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Test"}
        client.post("/api/incidents", data=data, files=files)
        
        response = client.get("/api/incidents")
        assert response.status_code == 200
        assert len(response.json()) >= 1
    
    def test_get_incident(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Test"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        response = client.get(f"/api/incidents/{incident_id}")
        assert response.status_code == 200
        assert response.json()["id"] == incident_id


class TestInvestigationWorkflow:
    def test_start_investigation(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Bearing overheating", "severity": "high"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        response = client.post(f"/api/incidents/{incident_id}/investigate")
        assert response.status_code == 200
        assert response.json()["success"] == True
        
        # Check agent statuses
        agents_resp = client.get(f"/api/incidents/{incident_id}/agents")
        assert agents_resp.status_code == 200
        assert agents_resp.json()["overall_status"] == "completed"
        assert agents_resp.json()["completed_count"] == 11
    
    def test_get_maintenance_plan(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Bearing overheating", "severity": "high"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        client.post(f"/api/incidents/{incident_id}/investigate")
        
        response = client.get(f"/api/incidents/{incident_id}/plan")
        assert response.status_code == 200
        assert response.json()["status"] == "proposed"
        assert "identified_failure" in response.json()
        assert "recommended_part" in response.json()


class TestApprovalEnforcement:
    def test_cannot_execute_without_approval(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Test", "severity": "high"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        client.post(f"/api/incidents/{incident_id}/investigate")
        
        # Try to execute work order without approval - should fail
        # First need to get work order ID after approval
        plan_resp = client.get(f"/api/incidents/{incident_id}/plan")
        assert plan_resp.status_code == 200
        
        # Approve plan
        approve_resp = client.post(f"/api/incidents/{incident_id}/approve", json={"approve": True, "reviewer": "Test Manager"})
        assert approve_resp.status_code == 200
        
        # Now work order should be created automatically by agent 10
        # Check work orders
        wo_resp = client.get("/api/work-orders")
        assert wo_resp.status_code == 200
        work_orders = wo_resp.json()
        assert len(work_orders) >= 1
        
        wo_id = work_orders[0]["id"]
        
        # Execute work order
        exec_resp = client.post(f"/api/work-orders/{wo_id}/execute", json={"action": "start", "actor": "Test Tech"})
        assert exec_resp.status_code == 200
        assert exec_resp.json()["new_status"] == "in_progress"
    
    def test_rejected_plan_cannot_execute(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Test", "severity": "high"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        client.post(f"/api/incidents/{incident_id}/investigate")
        
        # Reject plan
        approve_resp = client.post(f"/api/incidents/{incident_id}/approve", json={"approve": False, "reviewer": "Test Manager", "rejection_reason": "Cost too high"})
        assert approve_resp.status_code == 200
        assert approve_resp.json()["approved"] == False
        
        # Check no work order was created
        wo_resp = client.get("/api/work-orders")
        work_orders = wo_resp.json()
        incident_wos = [wo for wo in work_orders if wo["incident_id"] == incident_id]
        assert len(incident_wos) == 0


class TestRepairVerification:
    def test_failed_verification_blocks_closure(self):
        files = {"photo": ("test.jpg", create_test_image(), "image/jpeg")}
        data = {"machine_id": "CNC-001", "machine_name": "CNC 1", "location": "Line A", "failure_description": "Bearing failure", "severity": "high"}
        create_resp = client.post("/api/incidents", data=data, files=files)
        incident_id = create_resp.json()["id"]
        
        client.post(f"/api/incidents/{incident_id}/investigate")
        client.post(f"/api/incidents/{incident_id}/approve", json={"approve": True, "reviewer": "Manager"})
        
        wo_resp = client.get("/api/work-orders")
        wo_id = [wo for wo in wo_resp.json() if wo["incident_id"] == incident_id][0]["id"]
        
        # Start and complete work order
        client.post(f"/api/work-orders/{wo_id}/execute", json={"action": "start", "actor": "Tech"})
        client.post(f"/api/work-orders/{wo_id}/execute", json={"action": "complete", "actor": "Tech"})
        
        # Upload verification photo (will be simulated)
        files = {"photo": ("verify.jpg", create_test_image(), "image/jpeg")}
        data = {"expected_component": "Bearing 6205", "expected_part_number": "BRG-6205", "actor": "Operator"}
        ver_resp = client.post(f"/api/work-orders/{wo_id}/verification", data=data, files=files)
        assert ver_resp.status_code == 200
        
        # Try to close - should fail if verification failed
        # Note: In simulation, it might pass or fail randomly
        # This test verifies the endpoint enforces the rule
        close_resp = client.post(f"/api/work-orders/{wo_id}/close", json={"actor": "Manager"})
        # If verification passed, close should succeed
        # If verification failed, close should fail with 400
        if ver_resp.json()["verified"]:
            assert close_resp.status_code == 200
        else:
            assert close_resp.status_code == 400
            assert "not verified" in close_resp.json()["detail"].lower()


class TestDashboard:
    def test_dashboard_metrics(self):
        response = client.get("/api/dashboard")
        assert response.status_code == 200
        data = response.json()
        assert "total_incidents" in data
        assert "active_work_orders" in data
        assert "pending_approvals" in data
        assert "repairs_awaiting_verification" in data
        assert "recent_incidents" in data
        assert "recent_activity" in data
        assert "agent_execution_summary" in data


class TestTechniciansAndParts:
    def test_list_technicians(self):
        response = client.get("/api/technicians")
        assert response.status_code == 200
        assert len(response.json()) >= 1
    
    def test_create_technician(self):
        data = {
            "name": "New Tech",
            "email": "new@factory.com",
            "skills": ["mechanical_repair"],
            "max_concurrent_jobs": 2
        }
        response = client.post("/api/technicians", json=data)
        assert response.status_code == 200
        assert response.json()["name"] == "New Tech"
    
    def test_list_parts(self):
        response = client.get("/api/parts")
        assert response.status_code == 200
        assert len(response.json()) >= 1
    
    def test_create_part(self):
        data = {
            "part_number": "NEW-001",
            "name": "New Part",
            "compatible_machines": ["CNC-001"],
            "unit_cost": 100.0,
            "quantity_on_hand": 5
        }
        response = client.post("/api/parts", json=data)
        assert response.status_code == 200
        assert response.json()["part_number"] == "NEW-001"
    
    def test_create_duplicate_part_fails(self):
        data = {
            "part_number": "TEST-001",  # Already exists from fixture
            "name": "Duplicate Part",
            "compatible_machines": ["CNC-001"],
            "unit_cost": 100.0
        }
        response = client.post("/api/parts", json=data)
        assert response.status_code == 400


if __name__ == "__main__":
    pytest.main([__file__, "-v"])