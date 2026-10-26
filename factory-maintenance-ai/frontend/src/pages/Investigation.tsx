import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  AlertTriangle, 
  CheckCircle, 
  XCircle, 
  Loader2, 
  Play, 
  RefreshCw,
  Eye,
  ChevronDown,
  ChevronUp,
  AlertCircle,
  Zap,
  Search,
  Package,
  User,
  Clock,
  FileText,
  Shield,
  CheckCheck,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal } from '../components/ui';
import { incidentsApi } from '../services/api';
import { formatDate, getStatusColor, cn } from '../services/utils';
import type { AgentRun, AgentRunListResponse } from '../types/api';

const agentIcons: Record<string, typeof Zap> = {
  'Incident Intake Agent': AlertTriangle,
  'Visual Inspection Agent': Search,
  'Fault Diagnosis Agent': Zap,
  'Parts Sourcing Agent': Package,
  'Procurement Agent': FileText,
  'Technician Scheduling Agent': User,
  'Production Coordination Agent': Clock,
  'Maintenance Planning Agent': FileText,
  'Human Approval Agent': Shield,
  'Work Order Execution Agent': CheckCheck,
  'Repair Verification Agent': Eye,
};

const agentDescriptions: Record<string, string> = {
  'Incident Intake Agent': 'Validates incident data and stores details',
  'Visual Inspection Agent': 'Analyzes component photo for visual clues',
  'Fault Diagnosis Agent': 'Identifies likely fault and root cause',
  'Parts Sourcing Agent': 'Searches inventory for replacement parts',
  'Procurement Agent': 'Creates purchase requests for unavailable parts',
  'Technician Scheduling Agent': 'Matches repair to available technicians',
  'Production Coordination Agent': 'Proposes optimal downtime window',
  'Maintenance Planning Agent': 'Combines findings into repair plan',
  'Human Approval Agent': 'Pauses workflow for human approval',
  'Work Order Execution Agent': 'Creates and advances work order',
  'Repair Verification Agent': 'Verifies repair with completion photo',
};

export function Investigation() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [agentData, setAgentData] = useState<AgentRunListResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedAgent, setExpandedAgent] = useState<string | null>(null);
  const [incidentId, setIncidentId] = useState<number | null>(null);

  useEffect(() => {
    if (id) {
      setIncidentId(parseInt(id));
      loadAgentStatus();
    }
  }, [id]);

  const loadAgentStatus = async () => {
    if (!incidentId) return;
    try {
      setLoading(true);
      const response = await incidentsApi.getAgents(incidentId);
      setAgentData(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load agent status');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const startInvestigation = async () => {
    if (!incidentId) return;
    try {
      setRunning(true);
      setError(null);
      const response = await incidentsApi.investigate(incidentId);
      setAgentData(response.data);
    } catch (err: any) {
      setError(err.response?.data?.detail || 'Failed to start investigation');
    } finally {
      setRunning(false);
    }
  };

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed': return <CheckCircle className="h-5 w-5 text-green-500" />;
      case 'running': return <Loader2 className="h-5 w-5 text-primary-500 animate-spin" />;
      case 'failed': return <XCircle className="h-5 w-5 text-red-500" />;
      default: return <span className="h-5 w-5 text-surface-300" />;
    }
  };

  const getStatusBadge = (status: string) => {
    return <Badge className={getStatusColor(status)}>{status}</Badge>;
  };

  if (loading) {
    return (
      <PageLayout title="AI Investigation" description="Agent workflow execution status">
        <Card>
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        </Card>
      </PageLayout>
    );
  }

  if (error && !agentData) {
    return (
      <PageLayout title="AI Investigation" description="Agent workflow execution status">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error}</p>
            <Button variant="primary" onClick={loadAgentStatus} className="mt-4">
              <RefreshCw className="h-4 w-4 mr-2" />
              Retry
            </Button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  const agents = agentData?.agents || [];
  const overallStatus = agentData?.overall_status || 'pending';
  const completedCount = agentData?.completed_count || 0;
  const totalCount = agentData?.total_count || 11;

  return (
    <PageLayout 
      title="AI Investigation" 
      description="Real-time status of 11 AI agents coordinating maintenance response"
      actions={
        <div className="flex gap-2">
          {incidentId && (
            <Link to={`/incidents/${incidentId}`}>
              <Button variant="ghost">
                <ArrowLeft className="h-4 w-4 mr-2" />
                Back to Incident
              </Button>
            </Link>
          )}
          {overallStatus === 'pending' || overallStatus === 'failed' ? (
            <Button variant="primary" onClick={startInvestigation} loading={running}>
              {running ? 'Starting...' : overallStatus === 'pending' ? 'Start Investigation' : 'Retry Investigation'}
            </Button>
          ) : overallStatus === 'in_progress' ? (
            <Button variant="secondary" disabled>
              <Loader2 className="h-4 w-4 animate-spin mr-2" />
              Investigation Running
            </Button>
          ) : (
            <Button variant="success" disabled>
              <CheckCircle className="h-4 w-4 mr-2" />
              Investigation Complete
            </Button>
          )}
        </div>
      }
    >
      {/* Progress Header */}
      <Card className="mb-6">
        <div className="card-body">
          <div className="flex items-center justify-between mb-4">
            <div>
              <p className="text-sm text-surface-600">Overall Progress</p>
              <p className="text-2xl font-bold text-surface-900">{completedCount} / {totalCount} agents completed</p>
            </div>
            <Badge className={cn('text-lg px-4 py-2', getStatusColor(overallStatus))}>
              {overallStatus.replace(/_/g, ' ')}
            </Badge>
          </div>
          <div className="h-3 bg-surface-200 rounded-full overflow-hidden">
            <div 
              className="h-full bg-primary-600 rounded-full transition-all duration-500"
              style={{ width: `${(completedCount / totalCount) * 100}%` }}
            />
          </div>
        </div>
      </Card>

      {/* Agent List */}
      <div className="space-y-4">
        {agents.map((agent, index) => {
          const Icon = agentIcons[agent.agent_name] || Zap;
          const isExpanded = expandedAgent === agent.agent_name;
          
          return (
            <Card key={agent.id} className="overflow-hidden">
              <div 
                className="p-4 cursor-pointer hover:bg-surface-50 transition-colors"
                onClick={() => setExpandedAgent(isExpanded ? null : agent.agent_name)}
              >
                <div className="flex items-center gap-4">
                  <div className={cn(
                    'p-2 rounded-lg flex-shrink-0',
                    agent.status === 'completed' ? 'bg-green-100 text-green-600' :
                    agent.status === 'running' ? 'bg-primary-100 text-primary-600' :
                    agent.status === 'failed' ? 'bg-red-100 text-red-600' :
                    'bg-surface-100 text-surface-600'
                  )}>
                    <Icon className="h-6 w-6" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3">
                      <h3 className="font-semibold text-surface-900 truncate">{agent.agent_name}</h3>
                      <span className="text-xs text-surface-500 font-mono">#{agent.agent_order}</span>
                    </div>
                    <p className="text-sm text-surface-500 truncate">{agentDescriptions[agent.agent_name]}</p>
                    {agent.current_task && (
                      <p className="text-xs text-primary-600 mt-1 flex items-center gap-1">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        {agent.current_task}
                      </p>
                    )}
                  </div>
                  <div className="flex items-center gap-3">
                    {getStatusIcon(agent.status)}
                    {getStatusBadge(agent.status)}
                    <button
                      onClick={(e) => { e.stopPropagation(); setExpandedAgent(isExpanded ? null : agent.agent_name); }}
                      className="p-1 text-surface-400 hover:text-surface-600"
                      aria-label={isExpanded ? 'Collapse' : 'Expand'}
                    >
                      {isExpanded ? <ChevronUp className="h-5 w-5" /> : <ChevronDown className="h-5 w-5" />}
                    </button>
                  </div>
                </div>
              </div>
              
              {isExpanded && (
                <div className="border-t border-surface-200 bg-surface-50 p-4 space-y-4">
                  {/* Input Data */}
                  {agent.input_data && Object.keys(agent.input_data).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-surface-700 mb-2">Input Data</h4>
                      <pre className="text-xs bg-white p-3 rounded border border-surface-200 overflow-x-auto text-surface-700">
                        {JSON.stringify(agent.input_data, null, 2)}
                      </pre>
                    </div>
                  )}
                  
                  {/* Output Data */}
                  {agent.output_data && Object.keys(agent.output_data).length > 0 && (
                    <div>
                      <h4 className="text-sm font-medium text-surface-700 mb-2">Output Data</h4>
                      <pre className="text-xs bg-white p-3 rounded border border-surface-200 overflow-x-auto text-surface-700">
                        {JSON.stringify(agent.output_data, null, 2)}
                      </pre>
                    </div>
                  )}
                  
                  {/* Error */}
                  {agent.error_message && (
                    <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">
                      <strong>Error:</strong> {agent.error_message}
                    </div>
                  )}
                  
                  {/* Timestamps */}
                  <div className="grid grid-cols-2 gap-4 text-sm text-surface-600 pt-2 border-t border-surface-200">
                    <div>
                      <span className="text-surface-500">Started:</span> {agent.started_at ? formatDate(agent.started_at) : '—'}
                    </div>
                    <div>
                      <span className="text-surface-500">Completed:</span> {agent.completed_at ? formatDate(agent.completed_at) : '—'}
                    </div>
                  </div>
                </div>
              )}
            </Card>
          );
        })}
      </div>

      {agents.length === 0 && (
        <Card>
          <div className="text-center py-12">
            <AlertTriangle className="h-12 w-12 text-surface-300 mx-auto mb-4" />
            <h3 className="text-lg font-medium text-surface-900 mb-2">No Investigation Started</h3>
            <p className="text-surface-500 mb-6">Click "Start Investigation" to run all 11 AI agents</p>
            <Button variant="primary" onClick={startInvestigation} loading={running}>
              <Play className="h-4 w-4 mr-2" />
              Start Investigation
            </Button>
          </div>
        </Card>
      )}
    </PageLayout>
  );
}