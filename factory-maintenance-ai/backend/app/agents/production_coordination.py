from typing import Dict, Any
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from app.agents.base import BaseAgent
from app.models.agent_run import AgentStatus
from app.models.incident import Incident, Severity


class ProductionCoordinationAgent(BaseAgent):
    def __init__(self):
        super().__init__("Production Coordination Agent", 7)

    async def execute(self, db: Session, incident_id: int, agent_run: AgentRun, context: Dict[str, Any]) -> Dict[str, Any]:
        self.update_status(db, agent_run, AgentStatus.RUNNING, "Coordinating production downtime window")
        
        incident = db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Get estimated repair duration
        estimated_duration = context.get("estimated_repair_duration_hours", 4)
        severity = incident.severity
        
        # Determine optimal downtime window based on severity and production schedule
        downtime_window = self._calculate_downtime_window(severity, estimated_duration)
        
        # Calculate production impact
        impact = self._calculate_production_impact(incident, downtime_window, estimated_duration)
        
        self.log_activity(
            db, incident_id, "downtime_window_proposed", self.name, "agent",
            f"Downtime window proposed: {downtime_window['start']} to {downtime_window['end']}",
            {
                "downtime_window": downtime_window,
                "production_impact": impact,
                "severity": severity.value if hasattr(severity, 'value') else str(severity)
            }
        )
        
        self.update_status(db, agent_run, AgentStatus.COMPLETED, "Production coordination complete")
        return {
            "proposed_downtime_start": downtime_window["start"],
            "proposed_downtime_end": downtime_window["end"],
            "downtime_duration_hours": downtime_window["duration_hours"],
            "production_impact": impact,
            "severity_based_priority": self._get_severity_priority(severity),
            "requires_immediate_shutdown": severity in [Severity.HIGH, Severity.CRITICAL],
            "alternative_windows": self._get_alternative_windows(downtime_window)
        }
    
    def _calculate_downtime_window(self, severity: Severity, estimated_duration: float) -> Dict[str, Any]:
        """Calculate optimal downtime window based on severity."""
        now = datetime.utcnow()
        
        # For critical/high severity, schedule ASAP
        if severity in [Severity.CRITICAL, Severity.HIGH]:
            start = now + timedelta(hours=1)  # Allow 1 hour for preparation
        elif severity == Severity.MEDIUM:
            # Schedule at next shift change or planned break
            start = self._get_next_shift_change(now)
        else:  # LOW
            # Schedule at next planned maintenance window
            start = self._get_next_maintenance_window(now)
        
        end = start + timedelta(hours=estimated_duration + 1)  # Add 1 hour buffer
        
        return {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_hours": estimated_duration + 1,
            "scheduled_for": start.strftime("%Y-%m-%d %H:%M"),
            "window_type": "emergency" if severity in [Severity.CRITICAL, Severity.HIGH] else "planned"
        }
    
    def _get_next_shift_change(self, now: datetime) -> datetime:
        """Get next shift change (simplified: 6AM, 2PM, 10PM)."""
        shift_hours = [6, 14, 22]
        for hour in shift_hours:
            candidate = now.replace(hour=hour, minute=0, second=0, microsecond=0)
            if candidate > now:
                return candidate
        # Next day 6AM
        return (now + timedelta(days=1)).replace(hour=6, minute=0, second=0, microsecond=0)
    
    def _get_next_maintenance_window(self, now: datetime) -> datetime:
        """Get next planned maintenance window (simplified: weekends)."""
        days_ahead = 5 - now.weekday()  # Saturday = 5
        if days_ahead <= 0:
            days_ahead += 7
        return (now + timedelta(days=days_ahead)).replace(hour=8, minute=0, second=0, microsecond=0)
    
    def _calculate_production_impact(self, incident: Incident, window: Dict, duration: float) -> Dict[str, Any]:
        """Calculate estimated production impact."""
        severity = incident.severity
        
        impact_levels = {
            Severity.CRITICAL: {"units_lost_per_hour": 100, "revenue_loss_per_hour": 50000},
            Severity.HIGH: {"units_lost_per_hour": 50, "revenue_loss_per_hour": 25000},
            Severity.MEDIUM: {"units_lost_per_hour": 20, "revenue_loss_per_hour": 10000},
            Severity.LOW: {"units_lost_per_hour": 5, "revenue_loss_per_hour": 2000}
        }
        
        base = impact_levels.get(severity, impact_levels[Severity.MEDIUM])
        total_hours = window["duration_hours"]
        
        return {
            "estimated_units_lost": int(base["units_lost_per_hour"] * total_hours),
            "estimated_revenue_loss": base["revenue_loss_per_hour"] * total_hours,
            "impact_level": severity.value if hasattr(severity, 'value') else str(severity),
            "affected_lines": [incident.machine_id],
            "can_be_mitigated": severity in [Severity.LOW, Severity.MEDIUM]
        }
    
    def _get_severity_priority(self, severity: Severity) -> int:
        priorities = {Severity.CRITICAL: 1, Severity.HIGH: 2, Severity.MEDIUM: 3, Severity.LOW: 4}
        return priorities.get(severity, 3)
    
    def _get_alternative_windows(self, primary: Dict) -> List[Dict]:
        """Provide alternative downtime windows."""
        start = datetime.fromisoformat(primary["start"])
        alternatives = []
        
        for i, hours_offset in enumerate([4, 12, 24]):
            alt_start = start + timedelta(hours=hours_offset)
            alt_end = alt_start + timedelta(hours=primary["duration_hours"])
            alternatives.append({
                "option": i + 1,
                "start": alt_start.isoformat(),
                "end": alt_end.isoformat(),
                "description": f"Delay by {hours_offset} hours"
            })
        
        return alternatives