import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  CheckCircle, 
  XCircle, 
  AlertTriangle,
  Package,
  User,
  Clock,
  DollarSign,
  MapPin,
  AlertCircle,
  Shield,
  FileText,
  Loader2,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal } from '../components/ui';
import { incidentsApi } from '../services/api';
import { formatDate, getStatusColor, getSeverityColor, formatCurrency, cn } from '../services/utils';
import type { MaintenancePlan, PlanStatus, PlanApprovalRequest } from '../types/api';

export function PlanDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [plan, setPlan] = useState<MaintenancePlan | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject'>('approve');
  const [rejectionReason, setRejectionReason] = useState('');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    if (id) loadPlan();
  }, [id]);

  const loadPlan = async () => {
    try {
      setLoading(true);
      const response = await incidentsApi.getPlan(parseInt(id!));
      setPlan(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load maintenance plan');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveClick = (action: 'approve' | 'reject') => {
    setApprovalAction(action);
    setRejectionReason('');
    setShowApproveModal(true);
  };

  const handleApproveConfirm = async () => {
    if (!plan) return;
    
    setProcessing(true);
    try {
      const request: PlanApprovalRequest = {
        approve: approvalAction === 'approve',
        reviewer: 'Current User',
        rejection_reason: approvalAction === 'reject' ? rejectionReason : undefined,
      };
      
      await incidentsApi.approve(plan.incident_id, request);
      setShowApproveModal(false);
      loadPlan();
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to process approval');
    } finally {
      setProcessing(false);
    }
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

  if (error || !plan) {
    return (
      <PageLayout title="Error" description="">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error || 'Plan not found'}</p>
            <Button variant="primary" onClick={() => navigate('/plans')} className="mt-4">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Plans
            </Button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout 
      title={`Maintenance Plan #${plan.id}`} 
      description={`Incident #${plan.incident_id} • ${plan.status.toUpperCase()}`}
      actions={
        <div className="flex gap-2">
          <Link to={`/incidents/${plan.incident_id}`}>
            <Button variant="ghost">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Incident
            </Button>
          </Link>
          {plan.status === 'proposed' && (
            <>
              <Button variant="success" onClick={() => handleApproveClick('approve')}>
                <CheckCircle className="h-4 w-4 mr-2" />
                Approve
              </Button>
              <Button variant="danger" onClick={() => handleApproveClick('reject')}>
                <XCircle className="h-4 w-4 mr-2" />
                Reject
              </Button>
            </>
          )}
        </div>
      }
    >
      {/* Status Header */}
      <Card className="mb-6">
        <div className="card-body">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h2 className="text-xl font-bold text-surface-900">Plan Status</h2>
                <Badge className={cn('text-lg', getStatusColor(plan.status))}>
                  {plan.status}
                </Badge>
                {plan.risk_level && (
                  <Badge variant={plan.risk_level === 'high' ? 'danger' : plan.risk_level === 'medium' ? 'warning' : 'success'}>
                    {plan.risk_level.toUpperCase()} RISK
                  </Badge>
                )}
              </div>
              <p className="text-surface-600">Created: {formatDate(plan.created_at)} • Updated: {formatDate(plan.updated_at)}</p>
            </div>
            {plan.approved_by && (
              <div className="flex items-center gap-2 text-sm text-green-700 bg-green-50 px-4 py-2 rounded-lg">
                <CheckCircle className="h-4 w-4" />
                <span>Approved by {plan.approved_by} on {formatDate(plan.approved_at!)}</span>
              </div>
            )}
            {plan.rejection_reason && (
              <div className="flex items-center gap-2 text-sm text-red-700 bg-red-50 px-4 py-2 rounded-lg">
                <XCircle className="h-4 w-4" />
                <span>Rejected: {plan.rejection_reason}</span>
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Fault Diagnosis */}
          <Card>
            <div className="card-header flex items-center gap-2">
              <AlertTriangle className="h-5 w-5 text-orange-600" />
              <h2 className="text-lg font-semibold text-surface-900">Fault Diagnosis</h2>
            </div>
            <div className="card-body space-y-4">
              {plan.identified_failure && (
                <div>
                  <label className="text-sm text-surface-500">Identified Failure</label>
                  <p className="text-surface-700 mt-1">{plan.identified_failure}</p>
                </div>
              )}
              {plan.suspected_root_cause && (
                <div>
                  <label className="text-sm text-surface-500">Suspected Root Cause</label>
                  <p className="text-surface-700 mt-1">{plan.suspected_root_cause}</p>
                </div>
              )}
            </div>
          </Card>

          {/* Recommended Part */}
          {plan.recommended_part && (
            <Card>
              <div className="card-header flex items-center gap-2">
                <Package className="h-5 w-5 text-blue-600" />
                <h2 className="text-lg font-semibold text-surface-900">Recommended Replacement Part</h2>
              </div>
              <div className="card-body">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm text-surface-500">Part Number</label>
                    <p className="font-mono font-medium text-lg">{plan.recommended_part.part_number}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Name</label>
                    <p className="font-medium">{plan.recommended_part.name}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Availability</label>
                    <Badge variant={plan.part_availability === 'available' ? 'success' : plan.part_availability === 'low_stock' ? 'warning' : 'danger'}>
                      {plan.part_availability?.replace('_', ' ').toUpperCase()}
                    </Badge>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Estimated Cost</label>
                    <p className="font-medium">{formatCurrency(plan.estimated_part_cost)}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Stock on Hand</label>
                    <p className="font-medium">{plan.recommended_part.quantity_on_hand}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Lead Time</label>
                    <p className="font-medium">{plan.recommended_part.lead_time_days} days</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Location</label>
                    <p className="font-medium">{plan.recommended_part.location || 'N/A'}</p>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Recommended Technician */}
          {plan.recommended_technician && (
            <Card>
              <div className="card-header flex items-center gap-2">
                <User className="h-5 w-5 text-green-600" />
                <h2 className="text-lg font-semibold text-surface-900">Recommended Technician</h2>
              </div>
              <div className="card-body">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <label className="text-sm text-surface-500">Name</label>
                    <p className="font-medium text-lg">{plan.recommended_technician.name}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Email</label>
                    <p className="font-medium">{plan.recommended_technician.email}</p>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Status</label>
                    <Badge className={getStatusColor(plan.recommended_technician.status)}>
                      {plan.recommended_technician.status}
                    </Badge>
                  </div>
                  <div>
                    <label className="text-sm text-surface-500">Skills</label>
                    <div className="flex flex-wrap gap-1 mt-1">
                      {plan.recommended_technician.skills?.map((skill: string) => (
                        <Badge key={skill} variant="gray" className="text-xs">{skill}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Production Coordination */}
          {(plan.proposed_downtime_start || plan.proposed_downtime_end) && (
            <Card>
              <div className="card-header flex items-center gap-2">
                <Clock className="h-5 w-5 text-purple-600" />
                <h2 className="text-lg font-semibold text-surface-900">Production Coordination</h2>
              </div>
              <div className="card-body">
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {plan.proposed_downtime_start && (
                    <div>
                      <label className="text-sm text-surface-500">Downtime Start</label>
                      <p className="font-medium flex items-center gap-1">
                        <MapPin className="h-4 w-4 text-surface-400" />
                        {formatDate(plan.proposed_downtime_start)}
                      </p>
                    </div>
                  )}
                  {plan.proposed_downtime_end && (
                    <div>
                      <label className="text-sm text-surface-500">Downtime End</label>
                      <p className="font-medium flex items-center gap-1">
                        <MapPin className="h-4 w-4 text-surface-400" />
                        {formatDate(plan.proposed_downtime_end)}
                      </p>
                    </div>
                  )}
                  {plan.estimated_repair_duration_hours && (
                    <div>
                      <label className="text-sm text-surface-500">Estimated Duration</label>
                      <p className="font-medium">{plan.estimated_repair_duration_hours} hours</p>
                    </div>
                  )}
                  {plan.proposed_work_order_priority && (
                    <div>
                      <label className="text-sm text-surface-500">Work Order Priority</label>
                      <Badge variant={plan.proposed_work_order_priority === 'critical' ? 'danger' : plan.proposed_work_order_priority === 'high' ? 'warning' : 'info'}>
                        {plan.proposed_work_order_priority.toUpperCase()}
                      </Badge>
                    </div>
                  )}
                </div>
              </div>
            </Card>
          )}

          {/* Risk Assessment */}
          {plan.risk_assessment && (
            <Card>
              <div className="card-header flex items-center gap-2">
                <Shield className="h-5 w-5 text-red-600" />
                <h2 className="text-lg font-semibold text-surface-900">Risk Assessment</h2>
              </div>
              <div className="card-body">
                <div className={cn('p-4 rounded-lg', plan.risk_level === 'high' ? 'bg-red-50 border border-red-200' : plan.risk_level === 'medium' ? 'bg-yellow-50 border border-yellow-200' : 'bg-green-50 border border-green-200')}>
                  <div className="flex items-start gap-3">
                    <Badge variant={plan.risk_level === 'high' ? 'danger' : plan.risk_level === 'medium' ? 'warning' : 'success'}>
                      {plan.risk_level?.toUpperCase()} RISK
                    </Badge>
                    <div className="flex-1 whitespace-pre-wrap text-sm text-surface-700">{plan.risk_assessment}</div>
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* Proposed Work Order */}
          {(plan.proposed_work_order_notes || plan.proposed_work_order_priority) && (
            <Card>
              <div className="card-header flex items-center gap-2">
                <FileText className="h-5 w-5 text-primary-600" />
                <h2 className="text-lg font-semibold text-surface-900">Proposed Work Order</h2>
              </div>
              <div className="card-body">
                {plan.proposed_work_order_priority && (
                  <div className="mb-4">
                    <label className="text-sm text-surface-500">Priority</label>
                    <Badge variant={plan.proposed_work_order_priority === 'critical' ? 'danger' : plan.proposed_work_order_priority === 'high' ? 'warning' : 'info'}>
                      {plan.proposed_work_order_priority.toUpperCase()}
                    </Badge>
                  </div>
                )}
                {plan.proposed_work_order_notes && (
                  <div className="bg-surface-50 p-4 rounded-lg font-mono text-sm whitespace-pre-wrap text-surface-700">
                    {plan.proposed_work_order_notes}
                  </div>
                )}
              </div>
            </Card>
          )}
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Quick Actions */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Actions</h2>
            </div>
            <div className="card-body space-y-3">
              {plan.status === 'proposed' && (
                <>
                  <Button variant="success" className="w-full justify-start" onClick={() => handleApproveClick('approve')}>
                    <CheckCircle className="h-4 w-4 mr-2" />
                    Approve Plan
                  </Button>
                  <Button variant="danger" className="w-full justify-start" onClick={() => handleApproveClick('reject')}>
                    <XCircle className="h-4 w-4 mr-2" />
                    Reject Plan
                  </Button>
                </>
              )}
              {plan.status === 'approved' && (
                <Link to="/work-orders">
                  <Button variant="primary" className="w-full justify-start">
                    <FileText className="h-4 w-4 mr-2" />
                    Create Work Order
                  </Button>
                </Link>
              )}
              <Link to={`/incidents/${plan.incident_id}`}>
                <Button variant="secondary" className="w-full justify-start">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  View Incident
                </Button>
              </Link>
              <Link to={`/investigation/${plan.incident_id}`}>
                <Button variant="ghost" className="w-full justify-start">
                  View Investigation
                </Button>
              </Link>
            </div>
          </Card>

          {/* Summary */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Summary</h2>
            </div>
            <div className="card-body space-y-3 text-sm">
              <div className="flex justify-between">
                <span className="text-surface-500">Plan ID</span>
                <span className="font-medium">#{plan.id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Incident</span>
                <span className="font-medium">#{plan.incident_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Status</span>
                <Badge className={getStatusColor(plan.status)}>{plan.status}</Badge>
              </div>
              {plan.estimated_part_cost && (
                <div className="flex justify-between">
                  <span className="text-surface-500">Est. Part Cost</span>
                  <span className="font-medium">{formatCurrency(plan.estimated_part_cost)}</span>
                </div>
              )}
              {plan.estimated_repair_duration_hours && (
                <div className="flex justify-between">
                  <span className="text-surface-500">Est. Duration</span>
                  <span className="font-medium">{plan.estimated_repair_duration_hours}h</span>
                </div>
              )}
            </div>
          </Card>
        </div>
      </div>

      {/* Approval Modal */}
      <Modal
        isOpen={showApproveModal}
        onClose={() => setShowApproveModal(false)}
        title={approvalAction === 'approve' ? 'Approve Maintenance Plan' : 'Reject Maintenance Plan'}
        size="md"
      >
        <div className="space-y-4">
          <div className="p-4 bg-surface-50 rounded-lg">
            <p className="font-medium text-surface-900">Plan #{plan.id} for Incident #{plan.incident_id}</p>
            <p className="text-sm text-surface-500 mt-1">{plan.identified_failure}</p>
          </div>
          
          {approvalAction === 'reject' && (
            <div>
              <label className="label">Rejection Reason (required)</label>
              <textarea
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                placeholder="Explain why this plan should be rejected..."
                rows={3}
                className="input min-h-[100px] resize-y"
                required
              />
            </div>
          )}
          
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => setShowApproveModal(false)} disabled={processing}>
              Cancel
            </Button>
            <Button 
              variant={approvalAction === 'approve' ? 'success' : 'danger'} 
              onClick={handleApproveConfirm} 
              loading={processing}
              disabled={approvalAction === 'reject' && !rejectionReason.trim()}
            >
              {approvalAction === 'approve' ? 'Approve Plan' : 'Reject Plan'}
            </Button>
          </div>
        </div>
      </Modal>
    </PageLayout>
  );
}