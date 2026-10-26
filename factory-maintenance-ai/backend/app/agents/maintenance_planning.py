from typing import Dict, Any
from datetime import datetime
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident
from app.models.maintenance_plan import MaintenancePlan, PlanStatus
from app.models.inventory_part import InventoryPart
from app.models.technician import Technician


class MaintenancePlanningAgent(BaseAgent):
    def __init__(self):
        super().__init__("Maintenance Planning Agent", 8)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Creating comprehensive maintenance plan")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get or create maintenance plan
        plan = db.query(MaintenancePlan).filter(MaintenancePlan.incident_id == incident_id).first()
        if not plan:
            plan = MaintenancePlan(incident_id=incident_id)
            db.add(plan)
        
        # Populate plan with all gathered information
        self._populate_plan(plan, context)
        
        # Calculate risk assessment
        risk_assessment = self._calculate_risk_assessment(context, incident)
        plan.risk_level = risk_assessment["level"]
        plan.risk_assessment = risk_assessment["details"]
        
        # Propose work order
        plan.proposed_work_order_priority = self._determine_priority(incident, context)
        plan.proposed_work_order_notes = self._generate_work_order_notes(context)
        
        plan.status = PlanStatus.PROPOSED
        incident.status = type(incident.status).PLAN_PROPOSED if hasattr(type(incident.status), 'PLAN_PROPOSED') else "plan_proposed"
        
        db.commit()
        
        self.log_activity(
            db, incident_id, "maintenance_plan_proposed", self.name, "agent",
            f"Maintenance plan proposed with {plan.risk_level} risk level",
            {
                "plan_id": plan.id,
                "risk_level": plan.risk_level,
                "proposed_priority": plan.proposed_work_order_priority
            },
            from_status="investigating",
            to_status="plan_proposed"
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Maintenance plan created")
        
        # Return plan summary for response
        return {
            "plan_id": plan.id,
            "identified_failure": plan.identified_failure,
            "suspected_root_cause": plan.suspected_root_cause,
            "recommended_part_id": plan.recommended_part_id,
            "part_availability": plan.part_availability,
            "estimated_part_cost": plan.estimated_part_cost,
            "recommended_technician_id": plan.recommended_technician_id,
            "estimated_repair_duration_hours": plan.estimated_repair_duration_hours,
            "proposed_downtime_start": plan.proposed_downtime_start.isoformat() if plan.proposed_downtime_start else None,
            "proposed_downtime_end": plan.proposed_downtime_end.isoformat() if plan.proposed_downtime_end else None,
            "risk_level": plan.risk_level,
            "risk_assessment": plan.risk_assessment,
            "proposed_work_order_priority": plan.proposed_work_order_priority,
            "proposed_work_order_notes": plan.proposed_work_order_notes,
            "status": plan.status.value if hasattr(plan.status, 'value') else str(plan.status)
        }
    
    def _populate_plan(self, plan: MaintenancePlan, context: Dict[str, Any]):
        """Populate maintenance plan with all agent outputs."""
        plan.identified_failure = context.get("identified_failure")
        plan.suspected_root_cause = context.get("suspected_root_cause")
        plan.recommended_part_id = context.get("recommended_part_id")
        plan.part_availability = context.get("part_availability")
        plan.estimated_part_cost = context.get("estimated_part_cost") or context.get("unit_cost")
        plan.recommended_technician_id = context.get("recommended_technician_id")
        plan.estimated_repair_duration_hours = context.get("estimated_repair_duration_hours", 4)
        plan.proposed_downtime_start = self._parse_datetime(context.get("proposed_downtime_start"))
        plan.proposed_downtime_end = self._parse_datetime(context.get("proposed_downtime_end"))
    
    def _parse_datetime(self, dt_str: str):
        """Parse datetime string to datetime object."""
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return None
    
    def _calculate_risk_assessment(self, context: Dict, incident: Incident) -> Dict[str, Any]:
        """Calculate risk level and assessment details."""
        risk_factors = []
        risk_score = 0
        
        # Severity factor
        severity_risk = {"critical": 40, "high": 25, "medium": 15, "low": 5}
        sev = incident.severity.value if hasattr(incident.severity, 'value') else str(incident.severity).lower()
        risk_score += severity_risk.get(sev, 15)
        if sev in ["critical", "high"]:
            risk_factors.append(f"High severity incident ({sev})")
        
        # Part availability
        availability = context.get("part_availability", "unknown")
        if availability == "unavailable":
            risk_score += 30
            risk_factors.append("Required part not in stock - procurement delay expected")
        elif availability == "low_stock":
            risk_score += 15
            risk_factors.append("Low stock on required part - limited supply")
        
        # Technician availability
        tech_status = context.get("current_status", "unknown")
        if tech_status == "busy":
            risk_score += 10
            risk_factors.append("Assigned technician currently busy")
        
        # Production impact
        impact = context.get("production_impact", {})
        if impact.get("impact_level") in ["critical", "high"]:
            risk_score += 20
            risk_factors.append("Significant production impact expected")
        
        # Determine risk level
        if risk_score >= 70:
            level = "high"
        elif risk_score >= 40:
            level = "medium"
        else:
            level = "low"
        
        details = "Risk Assessment:\n" + "\n".join([f"• {f}" for f in risk_factors]) if risk_factors else "Risk Assessment: No significant risk factors identified."
        details += f"\n\nOverall Risk Score: {risk_score}/100"
        details += f"\nRisk Level: {level.upper()}"
        
        if level == "high":
            details += "\n\nRECOMMENDATION: Requires management approval and contingency planning."
        elif level == "medium":
            details += "\n\nRECOMMENDATION: Standard approval process. Monitor part delivery and technician schedule."
        else:
            details += "\n\nRECOMMENDATION: Low risk. Proceed with standard maintenance workflow."
        
        return {"level": level, "details": details, "score": risk_score}
    
    def _determine_priority(self, incident: Incident, context: Dict) -> str:
        """Determine work order priority."""
        sev = incident.severity.value if hasattr(incident.severity, 'value') else str(incident.severity).lower()
        priority_map = {"critical": "critical", "high": "high", "medium": "medium", "low": "low"}
        return priority_map.get(sev, "medium")
    
    def _generate_work_order_notes(self, context: Dict) -> str:
        """Generate comprehensive work order notes."""
        notes = "MAINTENANCE WORK ORDER NOTES\n"
        notes += "=" * 40 + "\n\n"
        
        notes += "FAULT DIAGNOSIS:\n"
        notes += f"  Failure: {context.get('identified_failure', 'Not specified')}\n"
        notes += f"  Root Cause: {context.get('suspected_root_cause', 'Not specified')}\n\n"
        
        notes += "PARTS REQUIRED:\n"
        notes += f"  Part: {context.get('part_name', 'TBD')} ({context.get('part_number', 'TBD')})\n"
        notes += f"  Availability: {context.get('part_availability', 'Unknown')}\n"
        notes += f"  Estimated Cost: ${context.get('estimated_part_cost', 0):.2f}\n\n"
        
        notes += "TECHNICIAN ASSIGNMENT:\n"
        notes += f"  Technician: {context.get('technician_name', 'TBD')}\n"
        notes += f"  Skills Match: {context.get('skills_match_score', 0)}%\n\n"
        
        notes += "SCHEDULING:\n"
        notes += f"  Estimated Duration: {context.get('estimated_repair_duration_hours', 4)} hours\n"
        notes += f"  Downtime Window: {context.get('proposed_downtime_start', 'TBD')} to {context.get('proposed_downtime_end', 'TBD')}\n\n"
        
        notes += "RISK ASSESSMENT:\n"
        notes += f"  Level: {context.get('risk_level', 'Unknown').upper()}\n"
        
        return notes