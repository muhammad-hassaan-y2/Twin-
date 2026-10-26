import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { 
  ClipboardList, 
  Clock, 
  AlertTriangle,
  CheckCircle,
  XCircle,
  FileText,
  User,
  Package,
  DollarSign,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal, ConfirmDialog, Textarea } from '../components/ui';
import { incidentsApi } from '../services/api';
import { formatDate, getStatusColor, getSeverityColor, formatCurrency, cn } from '../services/utils';
import type { MaintenancePlan, PlanStatus, PlanApprovalRequest } from '../types/api';

const statusOrder: PlanStatus[] = ['draft', 'proposed', 'approved', 'rejected'];

export function MaintenancePlans() {
  const [plans, setPlans] = useState<MaintenancePlan[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const pageSize = 10;
  const [selectedPlan, setSelectedPlan] = useState<MaintenancePlan | null>(null);
  const [showApproveModal, setShowApproveModal] = useState(false);
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject'>('approve');
  const [rejectionReason, setRejectionReason] = useState('');
  const [processing, setProcessing] = useState(false);

  useEffect(() => {
    loadPlans();
  }, []);

  const loadPlans = async () => {
    try {
      setLoading(true);
      // Get all incidents and their plans
      const incidentsResponse = await incidentsApi.list({ limit: 100 });
      const plansData: MaintenancePlan[] = [];
      
      for (const incident of incidentsResponse.data) {
        try {
          const planResponse = await incidentsApi.getPlan(incident.id);
          plansData.push(planResponse.data);
        } catch {
          // No plan yet for this incident
        }
      }
      
      // Sort by status priority and date
      plansData.sort((a, b) => {
        const statusA = statusOrder.indexOf(a.status);
        const statusB = statusOrder.indexOf(b.status);
        if (statusA !== statusB) return statusA - statusB;
        return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
      });
      
      setPlans(plansData);
      setError(null);
    } catch (err) {
      setError('Failed to load maintenance plans');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleApproveClick = (plan: MaintenancePlan, action: 'approve' | 'reject') => {
    setSelectedPlan(plan);
    setApprovalAction(action);
    setRejectionReason('');
    setShowApproveModal(true);
  };

  const handleApproveConfirm = async () => {
    if (!selectedPlan) return;
    
    setProcessing(true);
    try {
      const request: PlanApprovalRequest = {
        approve: approvalAction === 'approve',
        reviewer: 'Current User', // TODO: get from auth
        rejection_reason: approvalAction === 'reject' ? rejectionReason : undefined,
      };
      
      await incidentsApi.approve(selectedPlan.incident_id, request);
      setShowApproveModal(false);
      loadPlans(); // Refresh
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to process approval');
    } finally {
      setProcessing(false);
    }
  };

  const paginatedPlans = plans.slice((page - 1) * pageSize, page * pageSize);
  const totalPages = Math.ceil(plans.length / pageSize) || 1;

  if (loading) {
    return (
      <PageLayout title="Maintenance Plans" description="Review and approve AI-generated maintenance plans">
        <Card>
          <div className="animate-pulse space-y-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-24 bg-surface-200 rounded" />
            ))}
          </div>
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Maintenance Plans" description="Review and approve AI-generated maintenance plans">
      {error && (
        <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg text-red-700">{error}</div>
      )}

      <div className="space-y-4">
        {plans.length === 0 ? (
          <Card>
            <div className="text-center py-12">
              <ClipboardList className="h-12 w-12 text-surface-300 mx-auto mb-4" />
              <h3 className="text-lg font-medium text-surface-900 mb-2">No Maintenance Plans</h3>
              <p className="text-surface-500 mb-6">Plans will appear here after AI investigation completes</p>
            </div>
          </Card>
        ) : (
          plans.map((plan) => (
            <Card key={plan.id} className="overflow-hidden">
              <div className="p-6">
                <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
                  {/* Header Info */}
                  <div className="flex items-start gap-4 flex-1">
                    <div className={cn('p-3 rounded-xl', 
                      plan.status === 'approved' ? 'bg-green-100 text-green-600' :
                      plan.status === 'rejected' ? 'bg-red-100 text-red-600' :
                      plan.status === 'proposed' ? 'bg-yellow-100 text-yellow-600' :
                      'bg-surface-100 text-surface-600'
                    )}>
                      <ClipboardList className="h-6 w-6" />
                    </div>
                    <div>
                      <div className="flex items-center gap-3 mb-1">
                        <h3 className="font-semibold text-surface-900">Plan #{plan.id}</h3>
                        <Badge className={getStatusColor(plan.status)}>
                          {plan.status}
                        </Badge>
                        {plan.risk_level && (
                          <Badge variant={plan.risk_level === 'high' ? 'danger' : plan.risk_level === 'medium' ? 'warning' : 'success'}>
                            {plan.risk_level.toUpperCase()} RISK
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-surface-500">Incident #{plan.incident_id} • {formatDate(plan.created_at)}</p>
                    </div>
                  </div>

                  {/* Key Details */}
                  <div className="flex flex-wrap gap-6 text-sm text-surface-600">
                    {plan.identified_failure && (
                      <div className="flex items-center gap-1">
                        <AlertTriangle className="h-4 w-4" />
                        <span className="truncate max-w-xs">{plan.identified_failure}</span>
                      </div>
                    )}
                    {plan.recommended_part && (
                      <div className="flex items-center gap-1">
                        <Package className="h-4 w-4" />
                        <span>{plan.recommended_part.name}</span>
                        <Badge variant="gray">{plan.part_availability}</Badge>
                      </div>
                    )}
                    {plan.recommended_technician && (
                      <div className="flex items-center gap-1">
                        <User className="h-4 w-4" />
                        <span>{plan.recommended_technician.name}</span>
                      </div>
                    )}
                    {plan.estimated_repair_duration_hours && (
                      <div className="flex items-center gap-1">
                        <Clock className="h-4 w-4" />
                        <span>{plan.estimated_repair_duration_hours}h</span>
                      </div>
                    )}
                    {plan.estimated_part_cost && (
                      <div className="flex items-center gap-1">
                        <DollarSign className="h-4 w-4" />
                        <span>{formatCurrency(plan.estimated_part_cost)}</span>
                      </div>
                    )}
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2">
                    <Link to={`/plans/${plan.id}`}>
                      <Button variant="ghost" size="sm">
                        <FileText className="h-4 w-4 mr-1" />
                        Details
                      </Button>
                    </Link>
                    
                    {plan.status === 'proposed' && (
                      <>
                        <Button 
                          variant="success" 
                          size="sm"
                          onClick={() => handleApproveClick(plan, 'approve')}
                        >
                          <CheckCircle className="h-4 w-4 mr-1" />
                          Approve
                        </Button>
                        <Button 
                          variant="danger" 
                          size="sm"
                          onClick={() => handleApproveClick(plan, 'reject')}
                        >
                          <XCircle className="h-4 w-4 mr-1" />
                          Reject
                        </Button>
                      </>
                    )}
                    
                    {plan.status === 'approved' && (
                      <Button variant="primary" size="sm">
                        <CheckCircle className="h-4 w-4 mr-1" />
                        Approved
                      </Button>
                    )}
                    
                    {plan.status === 'rejected' && (
                      <Button variant="secondary" size="sm" disabled>
                        <XCircle className="h-4 w-4 mr-1" />
                        Rejected
                      </Button>
                    )}
                  </div>
                </div>

                {/* Downtime Window */}
                {plan.proposed_downtime_start && plan.proposed_downtime_end && (
                  <div className="mt-4 pt-4 border-t border-surface-200 flex flex-wrap gap-6 text-sm">
                    <div className="flex items-center gap-2 text-surface-600">
                      <Clock className="h-4 w-4" />
                      <span>Downtime: {formatDate(plan.proposed_downtime_start)} – {formatDate(plan.proposed_downtime_end)}</span>
                    </div>
                    {plan.proposed_work_order_priority && (
                      <div className="flex items-center gap-2">
                        <AlertCircle className="h-4 w-4" />
                        <Badge variant={plan.proposed_work_order_priority === 'critical' ? 'danger' : plan.proposed_work_order_priority === 'high' ? 'warning' : 'info'}>
                          {plan.proposed_work_order_priority.toUpperCase()} PRIORITY
                        </Badge>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </Card>
          ))
        )}

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2">
            <Button 
              variant="secondary" 
              size="sm"
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              <ChevronLeft className="h-4 w-4" />
            </Button>
            <span className="px-3 py-1 text-sm text-surface-600">
              Page {page} of {totalPages}
            </span>
            <Button 
              variant="secondary" 
              size="sm"
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>

      {/* Approval Modal */}
      <Modal
        isOpen={showApproveModal}
        onClose={() => { setShowApproveModal(false); setSelectedPlan(null); }}
        title={approvalAction === 'approve' ? 'Approve Maintenance Plan' : 'Reject Maintenance Plan'}
        size="md"
      >
        <div className="space-y-4">
          {selectedPlan && (
            <div className="p-4 bg-surface-50 rounded-lg">
              <p className="font-medium text-surface-900">Plan #{selectedPlan.id} for Incident #{selectedPlan.incident_id}</p>
              <p className="text-sm text-surface-500 mt-1">{selectedPlan.identified_failure}</p>
            </div>
          )}
          
          {approvalAction === 'reject' && (
            <Textarea
              label="Rejection Reason (required)"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              placeholder="Explain why this plan should be rejected..."
              rows={3}
              required
            />
          )}
          
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => { setShowApproveModal(false); setSelectedPlan(null); }} disabled={processing}>
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