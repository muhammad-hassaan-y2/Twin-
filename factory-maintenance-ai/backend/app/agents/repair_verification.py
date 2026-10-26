from typing import Dict, Any
import os
import random
from datetime import datetime
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.work_order import WorkOrder, WorkOrderStatus
from app.models.repair_verification import RepairVerification, VerificationStatus
from app.models.incident import Incident
from app.models.inventory_part import InventoryPart


class RepairVerificationAgent(BaseAgent):
    def __init__(self):
        super().__init__("Repair Verification Agent", 11)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        """This agent is triggered via API when repair photo is uploaded."""
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Verifying repair completion")
        
        work_order_id = context.get("work_order_id")
        if not work_order_id:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No work order ID provided")
            return {"error": "Work order ID required", "verified": False}
        
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        if not work_order:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="Work order not found")
            return {"error": "Work order not found", "verified": False}
        
        # Get verification record
        verification = db.query(RepairVerification).filter(RepairVerification.work_order_id == work_order_id).first()
        if not verification:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No verification record found")
            return {"error": "No verification record found", "verified": False}
        
        # SIMULATED: Verify repair by comparing photo with expected component
        verification_result = self._simulate_verification(work_order, verification, context)
        
        # Update verification record
        verification.status = verification_result["status"]
        verification.confidence_score = verification_result["confidence_score"]
        verification.verification_details = verification_result["details"]
        verification.mismatch_reasons = verification_result.get("mismatch_reasons")
        
        # Update work order and incident status based on verification
        if verification_result["status"] == VerificationStatus.VERIFIED:
            work_order.status = WorkOrderStatus.VERIFIED
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident:
                incident.status = type(incident.status).VERIFIED if hasattr(type(incident.status), 'VERIFIED') else "verified"
        else:
            work_order.status = WorkOrderStatus.AWAITING_VERIFICATION
            incident = db.query(Incident).filter(Incident.id == incident_id).first()
            if incident:
                incident.status = type(incident.status).FAILED_VERIFICATION if hasattr(type(incident.status), 'FAILED_VERIFICATION') else "failed_verification"
        
        db.commit()
        
        self.log_activity(
            db, incident_id, "repair_verification_complete", self.name, "agent",
            f"Repair verification {verification_result['status'].value if hasattr(verification_result['status'], 'value') else str(verification_result['status'])}",
            {
                "work_order_id": work_order_id,
                "verification_id": verification.id,
                "status": verification_result["status"].value if hasattr(verification_result["status"], 'value') else str(verification_result["status"]),
                "confidence": verification_result["confidence_score"]
            },
            from_status="awaiting_verification",
            to_status=verification_result["status"].value if hasattr(verification_result["status"], 'value') else str(verification_result["status"]),
            work_order_id=work_order_id
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Repair verification complete")
        return {
            "verified": verification_result["status"] == VerificationStatus.VERIFIED,
            "verification_status": verification_result["status"].value if hasattr(verification_result["status"], 'value') else str(verification_result["status"]),
            "confidence_score": verification_result["confidence_score"],
            "details": verification_result["details"],
            "mismatch_reasons": verification_result.get("mismatch_reasons"),
            "simulated": True,
            "note": "This is a simulated verification. Replace with real vision model in production."
        }
    
    def run_verification(self, db: Session, work_order_id: int, expected_component: str, expected_part_number: str, photo_path: str, actor: str) -> Dict[str, Any]:
        """Run verification when photo is uploaded (called from API)."""
        work_order = db.query(WorkOrder).filter(WorkOrder.id == work_order_id).first()
        if not work_order:
            raise ValueError(f"Work order {work_order_id} not found")
        
        # Create or update verification record
        verification = db.query(RepairVerification).filter(RepairVerification.work_order_id == work_order_id).first()
        if not verification:
            verification = RepairVerification(
                work_order_id=work_order_id,
                expected_component=expected_component,
                expected_part_number=expected_part_number,
                repair_photo_path=photo_path,
                status=VerificationStatus.PENDING
            )
            db.add(verification)
        else:
            verification.expected_component = expected_component
            verification.expected_part_number = expected_part_number
            verification.repair_photo_path = photo_path
            verification.status = VerificationStatus.PENDING
        
        db.commit()
        
        # Run simulated verification
        context = {"work_order_id": work_order_id}
        # We need to create a dummy agent run for logging
        from app.models.agent_run import AgentRun, AgentStatus
        agent_run = AgentRun(
            incident_id=work_order.incident_id,
            agent_name=self.name,
            agent_order=self.order,
            status=AgentStatus.RUNNING,
            current_task="Verifying repair completion"
        )
        db.add(agent_run)
        db.commit()
        
        result = self._simulate_verification(work_order, verification, context, db)
        
        # Update records
        verification.status = result["status"]
        verification.confidence_score = result["confidence_score"]
        verification.verification_details = result["details"]
        verification.mismatch_reasons = result.get("mismatch_reasons")
        
        agent_run.status = AgentStatus.COMPLETED
        agent_run.completed_at = datetime.utcnow()
        agent_run.output_data = result
        
        # Update work order and incident
        if result["status"] == VerificationStatus.VERIFIED:
            work_order.status = WorkOrderStatus.VERIFIED
            incident = db.query(Incident).filter(Incident.id == work_order.incident_id).first()
            if incident:
                incident.status = type(incident.status).VERIFIED if hasattr(type(incident.status), 'VERIFIED') else "verified"
        else:
            work_order.status = WorkOrderStatus.AWAITING_VERIFICATION
            incident = db.query(Incident).filter(Incident.id == work_order.incident_id).first()
            if incident:
                incident.status = type(incident.status).FAILED_VERIFICATION if hasattr(type(incident.status), 'FAILED_VERIFICATION') else "failed_verification"
        
        db.commit()
        
        return {
            "verified": result["status"] == VerificationStatus.VERIFIED,
            "verification_status": result["status"].value if hasattr(result["status"], 'value') else str(result["status"]),
            "confidence_score": result["confidence_score"],
            "details": result["details"],
            "mismatch_reasons": result.get("mismatch_reasons"),
            "simulated": True
        }
    
    def _simulate_verification(self, work_order: WorkOrder, verification: RepairVerification, context: Dict, db: Session) -> Dict[str, Any]:
        """Simulate repair verification (replace with real vision model in production)."""
        # In a real system, this would use computer vision to:
        # 1. Detect components in the repair photo
        # 2. Compare with expected component
        # 3. Check for correct installation
        # 4. Identify any anomalies
        
        # For simulation, we'll randomly succeed/fail based on some logic
        import random
        
        # Get expected part info
        expected_part = None
        if work_order.replacement_part_id:
            expected_part = db.query(InventoryPart).filter(InventoryPart.id == work_order.replacement_part_id).first()
        
        # Simulate verification logic
        # Higher confidence if part was available and correct technician was assigned
        base_confidence = 0.75
        
        if work_order.replacement_part_id and expected_part:
            base_confidence += 0.1
        
        # Add some randomness
        confidence = min(base_confidence + random.uniform(-0.1, 0.15), 0.98)
        
        # Determine result
        if confidence > 0.7:
            status = VerificationStatus.VERIFIED
            mismatch_reasons = None
        elif confidence > 0.5:
            status = VerificationStatus.INCONCLUSIVE
            mismatch_reasons = ["Image quality insufficient for definitive verification", "Component partially obscured"]
        else:
            status = VerificationStatus.FAILED
            mismatch_reasons = [
                "Expected component not visible in photo",
                "Different component detected",
                "Installation appears incorrect"
            ]
        
        details = {
            "expected_component": verification.expected_component,
            "expected_part_number": verification.expected_part_number,
            "actual_part_number": expected_part.part_number if expected_part else "Unknown",
            "analysis_method": "simulated_computer_vision",
            "checks_performed": [
                "component_presence",
                "part_number_match",
                "installation_orientation",
                "connection_integrity"
            ],
            "photo_analyzed": verification.repair_photo_path is not None
        }
        
        return {
            "status": status,
            "confidence_score": round(confidence, 2),
            "details": details,
            "mismatch_reasons": mismatch_reasons
        }
    
    def process_human_override(self, db: Session, verification_id: int, reviewer: str, override: bool, reason: str) -> Dict[str, Any]:
        """Process human override of verification result."""
        from datetime import datetime
        
        verification = db.query(RepairVerification).filter(RepairVerification.id == verification_id).first()
        if not verification:
            raise ValueError(f"Verification {verification_id} not found")
        
        verification.human_override = override
        verification.override_reason = reason
        verification.reviewed_by = reviewer
        verification.reviewed_at = datetime.utcnow()
        
        if override and verification.status == VerificationStatus.FAILED:
            # Human says it's actually correct despite failed verification
            verification.status = VerificationStatus.VERIFIED
            work_order = db.query(WorkOrder).filter(WorkOrder.id == verification.work_order_id).first()
            if work_order:
                work_order.status = WorkOrderStatus.VERIFIED
                incident = db.query(Incident).filter(Incident.id == work_order.incident_id).first()
                if incident:
                    incident.status = type(incident.status).VERIFIED if hasattr(type(incident.status), 'VERIFIED') else "verified"
        
        db.commit()
        
        return {
            "verification_id": verification_id,
            "new_status": verification.status.value if hasattr(verification.status, 'value') else str(verification.status),
            "human_override": override,
            "message": "Human override processed"
        }