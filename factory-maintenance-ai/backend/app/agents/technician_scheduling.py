from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.technician import Technician, TechnicianStatus
from app.models.work_order import WorkOrder, WorkOrderStatus


class TechnicianSchedulingAgent(BaseAgent):
    def __init__(self):
        super().__init__("Technician Scheduling Agent", 6)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Finding available technician")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get required skills from fault diagnosis
        required_skills = self._determine_required_skills(context)
        
        # Find available technicians with matching skills
        available_techs = db.query(Technician).filter(
            Technician.is_active == True,
            Technician.status.in_([TechnicianStatus.AVAILABLE, TechnicianStatus.BUSY])
        ).all()
        
        # Score technicians based on skill match and availability
        scored_techs = self._score_technicians(available_techs, required_skills, incident, db)
        
        if not scored_techs:
            self.update_status(db, agent_run, AgentStatus.FAILED, error="No suitable technicians available")
            return {"error": "No technicians available", "technician_assigned": False}
        
        best_tech = scored_techs[0][1]
        
        self.log_activity(
            db, incident_id, "technician_assigned", self.name, "agent",
            f"Technician assigned: {best_tech.name}",
            {
                "technician_id": best_tech.id,
                "technician_name": best_tech.name,
                "skills_match": scored_techs[0][0],
                "required_skills": required_skills
            }
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Technician scheduling complete")
        return {
            "recommended_technician_id": best_tech.id,
            "technician_name": best_tech.name,
            "technician_email": best_tech.email,
            "technician_skills": best_tech.skills or [],
            "skills_match_score": scored_techs[0][0],
            "required_skills": required_skills,
            "current_status": best_tech.status.value if hasattr(best_tech.status, 'value') else str(best_tech.status),
            "technician_assigned": True
        }
    
    def _determine_required_skills(self, context: Dict[str, Any]) -> List[str]:
        """Determine required skills based on fault diagnosis and part type."""
        skills = ["mechanical_repair"]
        
        failure = context.get("identified_failure", "").lower()
        root_cause = context.get("suspected_root_cause", "").lower()
        part_name = context.get("part_name", "").lower()
        
        skill_keywords = {
            "hydraulic": ["hydraulic_systems", "fluid_power"],
            "pneumatic": ["pneumatic_systems"],
            "electrical": ["electrical_systems", "plc_programming"],
            "bearing": ["precision_alignment", "vibration_analysis"],
            "pump": ["pump_maintenance", "fluid_systems"],
            "motor": ["motor_repair", "electrical_systems"],
            "valve": ["valve_maintenance", "process_control"],
            "sensor": ["instrumentation", "calibration"],
            "welding": ["welding", "fabrication"],
            "alignment": ["precision_alignment", "laser_alignment"]
        }
        
        for keyword, skill_list in skill_keywords.items():
            if keyword in failure or keyword in root_cause or keyword in part_name:
                skills.extend(skill_list)
        
        return list(set(skills))  # Remove duplicates
    
    def _score_technicians(self, technicians: List[Technician], required_skills: List[str], incident: Incident, db: Session) -> List[tuple]:
        """Score technicians based on skill match and current workload."""
        scored = []
        
        for tech in technicians:
            score = 0
            tech_skills = tech.skills or []
            
            # Skill matching
            for req_skill in required_skills:
                if req_skill in tech_skills:
                    score += 10
            
            # Availability preference
            if tech.status == TechnicianStatus.AVAILABLE:
                score += 5
            elif tech.status == TechnicianStatus.BUSY:
                # Check current workload
                active_orders = db.query(WorkOrder).filter(
                    WorkOrder.assigned_technician_id == tech.id,
                    WorkOrder.status.in_([WorkOrderStatus.IN_PROGRESS, WorkOrderStatus.SCHEDULED])
                ).count()
                if active_orders < tech.max_concurrent_jobs:
                    score += 2
                else:
                    score -= 10  # Overloaded
            
            # Certifications bonus
            if tech.certifications:
                score += len(tech.certifications)
            
            scored.append((score, tech))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        return scored