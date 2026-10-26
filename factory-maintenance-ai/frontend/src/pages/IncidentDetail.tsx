import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  AlertTriangle, 
  MapPin, 
  Clock, 
  Tag,
  Image,
  Loader2,
  AlertCircle
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal } from '../components/ui';
import { incidentsApi } from '../services/api';
import { formatDate, getStatusColor, getSeverityColor, getFileUrl, cn } from '../services/utils';
import type { Incident, IncidentStatus } from '../types/api';

const statusFlow: IncidentStatus[] = [
  'submitted',
  'investigating',
  'plan_proposed',
  'approved',
  'work_order_created',
  'in_progress',
  'awaiting_verification',
  'verified',
  'closed',
];

export function IncidentDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [incident, setIncident] = useState<Incident | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showDeleteModal, setShowDeleteModal] = useState(false);

  useEffect(() => {
    if (id) loadIncident();
  }, [id]);

  const loadIncident = async () => {
    try {
      setLoading(true);
      const response = await incidentsApi.get(parseInt(id!));
      setIncident(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load incident');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const getCurrentStepIndex = (status: IncidentStatus) => {
    return statusFlow.indexOf(status);
  };

  if (loading) {
    return (
      <PageLayout title="Loading..." description="">
        <Card>
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-primary-600" />
          </div>
        </Card>
      </PageLayout>
    );
  }

  if (error || !incident) {
    return (
      <PageLayout title="Error" description="">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error || 'Incident not found'}</p>
            <Button variant="primary" onClick={() => navigate('/incidents')} className="mt-4">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Incidents
            </Button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  const currentStep = getCurrentStepIndex(incident.status);
  const photoUrl = getFileUrl(incident.photo_path);

  return (
    <PageLayout 
      title={incident.machine_name} 
      description={`${incident.machine_id} • ${incident.location}`}
      actions={
        <div className="flex gap-2">
          <Link to={`/investigation/${incident.id}`}>
            <Button variant="primary">
              <AlertTriangle className="h-4 w-4 mr-2" />
              View Investigation
            </Button>
          </Link>
          <Link to={`/plans/${incident.id}`}>
            <Button variant="secondary">
              View Plan
            </Button>
          </Link>
        </div>
      }
    >
      {/* Status Timeline */}
      <Card className="mb-6">
        <div className="card-header">
          <h2 className="text-lg font-semibold text-surface-900">Workflow Progress</h2>
        </div>
        <div className="card-body p-0">
          <div className="relative">
            <div className="absolute left-8 top-0 bottom-0 w-0.5 bg-surface-200" />
            <div className="flex items-start justify-between px-8 py-4">
              {statusFlow.map((step, index) => {
                const isCompleted = index < currentStep;
                const isCurrent = index === currentStep;
                const isFuture = index > currentStep;
                
                return (
                  <div key={step} className="flex flex-col items-center flex-1 relative">
                    <div className={cn(
                      'relative z-10 w-10 h-10 rounded-full flex items-center justify-center transition-all',
                      isCompleted ? 'bg-green-500 text-white' :
                      isCurrent ? 'bg-primary-500 text-white ring-4 ring-primary-500/20' :
                      'bg-surface-200 text-surface-400'
                    )}>
                      {isCompleted ? (
                        <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={3} d="M5 13l4 4L19 7" />
                        </svg>
                      ) : (
                        <span className="text-xs font-bold">{index + 1}</span>
                      )}
                    </div>
                    <span className={cn(
                      'mt-2 text-xs font-medium text-center max-w-[100px]',
                      isCompleted ? 'text-green-700' :
                      isCurrent ? 'text-primary-700' :
                      'text-surface-500'
                    )}>
                      {step.replace(/_/g, ' ')}
                    </span>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Info */}
        <div className="lg:col-span-2 space-y-6">
          {/* Details */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Incident Details</h2>
            </div>
            <div className="card-body space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-surface-500">Machine ID</label>
                  <p className="font-mono font-medium text-lg">{incident.machine_id}</p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Location</label>
                  <p className="font-medium flex items-center gap-1">
                    <MapPin className="h-4 w-4 text-surface-400" />
                    {incident.location}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Severity</label>
                  <Badge variant={incident.severity === 'critical' ? 'danger' : incident.severity === 'high' ? 'warning' : incident.severity === 'medium' ? 'info' : 'success'} className="text-sm">
                    {incident.severity.toUpperCase()}
                  </Badge>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Status</label>
                  <Badge className={getStatusColor(incident.status)}>
                    {incident.status.replace(/_/g, ' ')}
                  </Badge>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Created</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {formatDate(incident.created_at)}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Last Updated</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {formatDate(incident.updated_at)}
                  </p>
                </div>
              </div>
              
              <div className="pt-4 border-t border-surface-200">
                <label className="text-sm text-surface-500">Failure Description</label>
                <p className="mt-2 text-surface-700 whitespace-pre-wrap">{incident.failure_description}</p>
              </div>
            </div>
          </Card>

          {/* Photo */}
          {photoUrl && (
            <Card>
              <div className="card-header">
                <h2 className="text-lg font-semibold text-surface-900 flex items-center gap-2">
                  <Image className="h-5 w-5" />
                  Component Photo
                </h2>
              </div>
              <div className="card-body p-0">
                <img src={photoUrl} alt="Failed component" className="w-full h-auto max-h-[500px] object-contain" />
              </div>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Quick Actions */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Quick Actions</h2>
            </div>
            <div className="card-body space-y-3">
              <Link to={`/investigation/${incident.id}`}>
                <Button variant="primary" className="w-full justify-start">
                  <AlertTriangle className="h-4 w-4 mr-2" />
                  Run AI Investigation
                </Button>
              </Link>
              {incident.status === 'plan_proposed' && (
                <Link to={`/plans/${incident.id}`}>
                  <Button variant="secondary" className="w-full justify-start">
                    Review Maintenance Plan
                  </Button>
                </Link>
              )}
              {incident.status === 'approved' && (
                <Link to={`/work-orders`}>
                  <Button variant="success" className="w-full justify-start">
                    View Work Orders
                  </Button>
                </Link>
              )}
            </div>
          </Card>

          {/* Related Links */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Related</h2>
            </div>
            <div className="card-body space-y-2">
              <Link to={`/investigation/${incident.id}`} className="block p-3 rounded-lg hover:bg-surface-50 transition-colors">
                <p className="font-medium text-surface-900">AI Investigation</p>
                <p className="text-sm text-surface-500">View agent execution details</p>
              </Link>
              <Link to={`/plans/${incident.id}`} className="block p-3 rounded-lg hover:bg-surface-50 transition-colors">
                <p className="font-medium text-surface-900">Maintenance Plan</p>
                <p className="text-sm text-surface-500">Review proposed plan</p>
              </Link>
              <Link to={`/work-orders`} className="block p-3 rounded-lg hover:bg-surface-50 transition-colors">
                <p className="font-medium text-surface-900">Work Orders</p>
                <p className="text-sm text-surface-500">View associated work orders</p>
              </Link>
            </div>
          </Card>
        </div>
      </div>
    </PageLayout>
  );
}