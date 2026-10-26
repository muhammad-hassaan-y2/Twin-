from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.agents import get_all_agents, get_agent
from app.models.incident import Incident, IncidentStatus
from app.models.agent_run import AgentRun, AgentStatus
from app.models.activity_log import ActivityLog


class WorkflowService:
    def __init__(self, db: Session):
        self.db = db
        self.agents = get_all_agents()
    
    async def run_investigation(self, incident_id: int) -> Dict[str, Any]:
        """Run the complete agent investigation workflow for an incident."""
        incident = self.db.query(Incident).filter(Incident.id == incident_id).first()
        if not incident:
            raise ValueError(f"Incident {incident_id} not found")
        
        # Create agent runs for all agents
        agent_runs = []
        for agent in self.agents:
            run = AgentRun(
                incident_id=incident_id,
                agent_name=agent.name,
                agent_order=agent.order,
                status=AgentStatus.PENDING
            )
            self.db.add(run)
            agent_runs.append(run)
        
        self.db.commit()
        
        # Execute agents in sequence
        context = {}
        failed_agent = None
        
        for agent in self.agents:
            agent_run = next(r for r in agent_runs if r.agent_name == agent.name)
            
            try:
                # Execute agent
                result = await agent.execute(self.db, incident_id, agent_run, context)
                agent_run.output_data = result
                agent_run.status = AgentStatus.COMPLETED
                agent_run.completed_at = agent_run.completed_at or __import__('datetime').datetime.utcnow()
                
                # Merge result into context for next agents
                context.update(result)
                
                self.db.commit()
                
            except Exception as e:
                agent_run.status = AgentStatus.FAILED
                agent_run.error_message = str(e)
                agent_run.completed_at = __import__('datetime').datetime.utcnow()
                self.db.commit()
                
                failed_agent = agent.name
                break
        
        # Update incident status based on result
        if failed_agent:
            incident.status = IncidentStatus.SUBMITTED  # Reset to allow retry
            return {
                "success": False,
                "failed_agent": failed_agent,
                "message": f"Investigation failed at {failed_agent}",
                "agent_runs": [self._agent_run_to_dict(r) for r in agent_runs]
            }
        else:
            # All agents completed successfully - workflow pauses at human approval
            return {
                "success": True,
                "message": "Investigation complete. Awaiting human approval.",
                "agent_runs": [self._agent_run_to_dict(r) for r in agent_runs],
                "context": context
            }
    
    def get_agent_statuses(self, incident_id: int) -> List[Dict[str, Any]]:
        """Get status of all agent runs for an incident."""
        runs = self.db.query(AgentRun).filter(AgentRun.incident_id == incident_id).order_by(AgentRun.agent_order).all()
        return [self._agent_run_to_dict(r) for r in runs]
    
    def _agent_run_to_dict(self, run: AgentRun) -> Dict[str, Any]:
        return {
            "id": run.id,
            "incident_id": run.incident_id,
            "agent_name": run.agent_name,
            "agent_order": run.agent_order,
            "status": run.status.value if hasattr(run.status, 'value') else str(run.status),
            "current_task": run.current_task,
            "input_data": run.input_data,
            "output_data": run.output_data,
            "error_message": run.error_message,
            "started_at": run.started_at.isoformat() if run.started_at else None,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "created_at": run.created_at.isoformat() if run.created_at else None,
        }
    
    def get_workflow_summary(self, incident_id: int) -> Dict[str, Any]:
        """Get overall workflow status summary."""
        runs = self.db.query(AgentRun).filter(AgentRun.incident_id == incident_id).all()
        
        total = len(runs)
        completed = sum(1 for r in runs if r.status == AgentStatus.COMPLETED)
        failed = sum(1 for r in runs if r.status == AgentStatus.FAILED)
        running = sum(1 for r in runs if r.status == AgentStatus.RUNNING)
        pending = sum(1 for r in runs if r.status == AgentStatus.PENDING)
        
        if failed > 0:
            overall = "failed"
        elif running > 0:
            overall = "in_progress"
        elif completed == total:
            overall = "completed"
        else:
            overall = "pending"
        
        return {
            "overall_status": overall,
            "total_agents": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "pending": pending,
            "progress_percent": int((completed / total) * 100) if total > 0 else 0
        }


async def run_incident_investigation(db: Session, incident_id: int) -> Dict[str, Any]:
    """Convenience function to run investigation."""
    service = WorkflowService(db)
    return await service.run_investigation(incident_id)