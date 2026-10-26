from typing import Dict, Any
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident


class FaultDiagnosisAgent(BaseAgent):
    def __init__(self):
        super().__init__("Fault Diagnosis Agent", 3)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Diagnosing fault from visual clues")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get visual inspection results
        visual_clues = context.get("visual_clues", {})
        if not visual_clues:
            # Try to get from previous agent run
            from app.models.agent_run import AgentRun as AgentRunModel
            prev_run = db.query(AgentRunModel).filter(
                AgentRunModel.incident_id == incident_id,
                AgentRunModel.agent_name == "Visual Inspection Agent"
            ).first()
            if prev_run and prev_run.output_data:
                visual_clues = prev_run.output_data.get("visual_clues", {})
        
        # SIMULATED: Fault diagnosis based on visual clues and failure description
        diagnosis = self._simulate_fault_diagnosis(incident, visual_clues)
        
        self.log_activity(
            db, incident_id, "fault_diagnosis_complete", self.name, "agent",
            f"Fault diagnosis completed: {diagnosis['identified_failure']}",
            {"diagnosis": diagnosis, "simulated": True}
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Fault diagnosis complete")
        return {
            **diagnosis,
            "simulated": True,
            "note": "This is a simulated fault diagnosis. Replace with real diagnostic model in production."
        }
    
    def _simulate_fault_diagnosis(self, incident: Incident, visual_clues: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate fault diagnosis based on visual clues and description."""
        damage_type = visual_clues.get("damage_type", "unknown")
        corrosion = visual_clues.get("corrosion_level", "unknown")
        leakage = visual_clues.get("leakage_signs", "none")
        
        # Map damage types to likely failures
        failure_map = {
            "surface_degradation": {
                "failure": "Bearing surface degradation due to inadequate lubrication",
                "root_cause": "Lubrication schedule not followed or incorrect lubricant type used",
                "confidence": 0.82
            },
            "mechanical_wear": {
                "failure": "Premature mechanical wear on rotating component",
                "root_cause": "Misalignment or imbalance causing excessive vibration",
                "confidence": 0.78
            },
            "structural_fracture": {
                "failure": "Structural fracture in load-bearing component",
                "root_cause": "Fatigue failure from cyclic loading beyond design limits",
                "confidence": 0.85
            },
            "complete_failure": {
                "failure": "Catastrophic component failure",
                "root_cause": "Combined fatigue, corrosion, and overload conditions",
                "confidence": 0.90
            }
        }
        
        base_diagnosis = failure_map.get(damage_type, {
            "failure": "Unknown component failure",
            "root_cause": "Insufficient data for diagnosis",
            "confidence": 0.50
        })
        
        # Adjust based on corrosion and leakage
        if corrosion in ["severe", "critical"]:
            base_diagnosis["root_cause"] += "; accelerated by severe corrosion"
            base_diagnosis["confidence"] = min(base_diagnosis["confidence"] + 0.05, 0.95)
        
        if leakage in ["active_leak", "major_leak"]:
            base_diagnosis["failure"] += " with seal failure"
            base_diagnosis["root_cause"] += "; seal degradation allowed contamination"
        
        return {
            "identified_failure": base_diagnosis["failure"],
            "suspected_root_cause": base_diagnosis["root_cause"],
            "diagnosis_confidence": base_diagnosis["confidence"],
            "contributing_factors": self._get_contributing_factors(visual_clues),
            "recommended_tests": ["vibration_analysis", "oil_analysis", "alignment_check"]
        }
    
    def _get_contributing_factors(self, visual_clues: Dict[str, Any]) -> list:
        factors = []
        if visual_clues.get("corrosion_level") in ["moderate", "severe", "critical"]:
            factors.append("Corrosion damage")
        if visual_clues.get("wear_pattern") in ["accelerated", "abnormal", "catastrophic"]:
            factors.append("Abnormal wear pattern")
        if visual_clues.get("foreign_objects"):
            factors.append("Contamination/foreign object damage")
        if visual_clues.get("leakage_signs") in ["minor_oil_seepage", "active_leak", "major_leak"]:
            factors.append("Fluid leakage")
        return factors if factors else ["Normal wear and tear"]