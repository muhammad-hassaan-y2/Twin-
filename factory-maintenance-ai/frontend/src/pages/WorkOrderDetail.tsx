import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  Play, 
  CheckCircle, 
  PauseCircle,
  FileText,
  User,
  Package,
  Clock,
  DollarSign,
  AlertTriangle,
  CheckCheck,
  XCircle,
  Loader2,
  AlertCircle,
  Edit,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal, ConfirmDialog, Textarea } from '../components/ui';
import { workOrdersApi } from '../services/api';
import { formatDate, getStatusColor, getPriorityColor, formatCurrency, cn } from '../services/utils';
import type { WorkOrder, WorkOrderStatus, WorkOrderExecuteRequest, WorkOrderCloseRequest } from '../types/api';

export function WorkOrderDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [workOrder, setWorkOrder] = useState<WorkOrder | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [executing, setExecuting] = useState(false);
  const [showExecuteModal, setShowExecuteModal] = useState(false);
  const [executeAction, setExecuteAction] = useState<'start' | 'complete' | 'hold'>('start');
  const [executeNotes, setExecuteNotes] = useState('');
  const [showCloseConfirm, setShowCloseConfirm] = useState(false);
  const [closing, setClosing] = useState(false);

  useEffect(() => {
    if (id) loadWorkOrder();
  }, [id]);

  const loadWorkOrder = async () => {
    try {
      setLoading(true);
      const response = await workOrdersApi.get(parseInt(id!));
      setWorkOrder(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load work order');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handleExecute = async () => {
    if (!workOrder) return;
    
    setExecuting(true);
    try {
      const request: WorkOrderExecuteRequest = {
        action: executeAction,
        notes: executeNotes,
        actor: 'Current User',
      };
      
      const response = await workOrdersApi.execute(workOrder.id, request);
      setShowExecuteModal(false);
      setExecuteNotes('');
      loadWorkOrder(); // Refresh
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to execute action');
    } finally {
      setExecuting(false);
    }
  };

  const handleCloseWorkOrder = () => {
    setShowCloseConfirm(true);
  };

  const handleCloseConfirm = async () => {
    if (!workOrder) return;
    
    setClosing(true);
    try {
      const request: WorkOrderCloseRequest = {
        actor: 'Current User',
        notes: 'Closed after successful verification',
      };
      
      await workOrdersApi.close(workOrder.id, request);
      setShowCloseConfirm(false);
      loadWorkOrder(); // Refresh
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to close work order');
    } finally {
      setClosing(false);
    }
  };

  const canStart = workOrder?.status === 'created' || workOrder?.status === 'scheduled';
  const canComplete = workOrder?.status === 'in_progress';
  const canHold = workOrder?.status === 'in_progress' || workOrder?.status === 'scheduled';
  const canVerify = workOrder?.status === 'awaiting_verification';
  const canClose = workOrder?.status === 'verified';

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

  if (error || !workOrder) {
    return (
      <PageLayout title="Error" description="">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error || 'Work order not found'}</p>
            <Button variant="primary" onClick={() => navigate('/work-orders')} className="mt-4">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Work Orders
            </Button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  const openExecuteModal = (action: 'start' | 'complete' | 'hold') => {
    setExecuteAction(action);
    setExecuteNotes('');
    setShowExecuteModal(true);
  };

  return (
    <PageLayout 
      title={workOrder.work_order_number} 
      description={`${workOrder.incident?.machine_name || 'Unknown Machine'} • ${workOrder.priority.toUpperCase()} PRIORITY`}
      actions={
        <div className="flex gap-2">
          <Link to="/work-orders">
            <Button variant="ghost">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to List
            </Button>
          </Link>
        </div>
      }
    >
      {/* Status Header */}
      <Card className="mb-6">
        <div className="card-body">
          <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
            <div>
              <div className="flex items-center gap-3 mb-2">
                <h2 className="text-xl font-bold text-surface-900">Status</h2>
                <Badge className={cn('text-lg', getStatusColor(workOrder.status))}>
                  {workOrder.status.replace(/_/g, ' ')}
                </Badge>
                <Badge variant={workOrder.priority === 'critical' ? 'danger' : workOrder.priority === 'high' ? 'warning' : workOrder.priority === 'medium' ? 'info' : 'success'}>
                  {workOrder.priority.toUpperCase()}
                </Badge>
              </div>
              <p className="text-surface-600">
                Incident #{workOrder.incident_id} • 
                {workOrder.incident?.machine_id} • 
                {formatDate(workOrder.created_at)}
              </p>
            </div>
            <div className="flex gap-2">
              {canStart && (
                <Button variant="primary" onClick={() => openExecuteModal('start')}>
                  <Play className="h-4 w-4 mr-2" />
                  Start Work
                </Button>
              )}
              {canComplete && (
                <Button variant="success" onClick={() => openExecuteModal('complete')}>
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Complete Work
                </Button>
              )}
              {canHold && (
                <Button variant="secondary" onClick={() => openExecuteModal('hold')}>
                  <PauseCircle className="h-4 w-4 mr-2" />
                  Place on Hold
                </Button>
              )}
              {canVerify && (
                <Link to={`/verification/${workOrder.id}`}>
                  <Button variant="primary">
                    <CheckCheck className="h-4 w-4 mr-2" />
                    Verify Repair
                  </Button>
                </Link>
              )}
              {canClose && (
                <Button variant="success" onClick={handleCloseWorkOrder}>
                  <CheckCheck className="h-4 w-4 mr-2" />
                  Close Work Order
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-6">
          {/* Work Order Details */}
          <Card>
            <div className="card-header">
              <h2 className="text-lg font-semibold text-surface-900">Work Order Details</h2>
            </div>
            <div className="card-body space-y-4">
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                <div>
                  <label className="text-sm text-surface-500">Assigned Technician</label>
                  <div className="flex items-center gap-2">
                    {workOrder.technician ? (
                      <>
                        <User className="h-5 w-5 text-surface-400" />
                        <span className="font-medium">{workOrder.technician.name}</span>
                        <Badge className={getStatusColor(workOrder.technician.status)}>
                          {workOrder.technician.status}
                        </Badge>
                      </>
                    ) : (
                      <span className="text-surface-400">Unassigned</span>
                    )}
                  </div>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Replacement Part</label>
                  {workOrder.part ? (
                    <>
                      <Package className="h-5 w-5 text-surface-400" />
                      <span className="font-medium">{workOrder.part.name} ({workOrder.part.part_number})</span>
                    </>
                  ) : (
                    <span className="text-surface-400">Not specified</span>
                  )}
                </div>
                <div>
                  <label className="text-sm text-surface-500">Scheduled Start</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {workOrder.scheduled_start ? formatDate(workOrder.scheduled_start) : 'Not scheduled'}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Scheduled End</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {workOrder.scheduled_end ? formatDate(workOrder.scheduled_end) : 'Not scheduled'}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Actual Start</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {workOrder.actual_start ? formatDate(workOrder.actual_start) : 'Not started'}
                  </p>
                </div>
                <div>
                  <label className="text-sm text-surface-500">Actual End</label>
                  <p className="font-medium flex items-center gap-1">
                    <Clock className="h-4 w-4 text-surface-400" />
                    {workOrder.actual_end ? formatDate(workOrder.actual_end) : 'Not completed'}
                  </p>
                </div>
              </div>

              {(workOrder.progress_notes || workOrder.completion_notes) && (
                <div className="pt-4 border-t border-surface-200 space-y-3">
                  {workOrder.progress_notes && (
                    <div>
                      <label className="text-sm text-surface-500">Progress Notes</label>
                      <p className="text-surface-700 mt-1 whitespace-pre-wrap">{workOrder.progress_notes}</p>
                    </div>
                  )}
                  {workOrder.completion_notes && (
                    <div>
                      <label className="text-sm text-surface-500">Completion Notes</label>
                      <p className="text-surface-700 mt-1 whitespace-pre-wrap">{workOrder.completion_notes}</p>
                    </div>
                  )}
                </div>
              )}
            </div>
          </Card>

          {/* Approval Info */}
          {workOrder.approved_by && (
            <Card>
              <div className="card-header">
                <h2 className="text-lg font-semibold text-surface-900">Approval</h2>
              </div>
              <div className="card-body">
                <div className="flex items-center gap-3 text-green-700 bg-green-50 p-4 rounded-lg">
                  <CheckCircle className="h-5 w-5" />
                  <div>
                    <p className="font-medium">Approved by {workOrder.approved_by}</p>
                    <p className="text-sm">{formatDate(workOrder.approved_at!)}</p>
                  </div>
                </div>
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
              {canStart && (
                <Button variant="primary" className="w-full justify-start" onClick={() => openExecuteModal('start')}>
                  <Play className="h-4 w-4 mr-2" />
                  Start Work
                </Button>
              )}
              {canComplete && (
                <Button variant="success" className="w-full justify-start" onClick={() => openExecuteModal('complete')}>
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Complete Work
                </Button>
              )}
              {canHold && (
                <Button variant="secondary" className="w-full justify-start" onClick={() => openExecuteModal('hold')}>
                  <PauseCircle className="h-4 w-4 mr-2" />
                  Place on Hold
                </Button>
              )}
              {canVerify && (
                <Link to={`/verification/${workOrder.id}`}>
                  <Button variant="primary" className="w-full justify-start">
                    <CheckCheck className="h-4 w-4 mr-2" />
                    Verify Repair
                  </Button>
                </Link>
              )}
              {canClose && (
                <Button variant="success" className="w-full justify-start" onClick={handleCloseWorkOrder}>
                  <CheckCheck className="h-4 w-4 mr-2" />
                  Close Work Order
                </Button>
              )}
              <Link to={`/incidents/${workOrder.incident_id}`}>
                <Button variant="ghost" className="w-full justify-start">
                  <ArrowLeft className="h-4 w-4 mr-2" />
                  View Incident
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
                <span className="text-surface-500">WO Number</span>
                <span className="font-mono font-medium">{workOrder.work_order_number}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Incident</span>
                <span className="font-medium">#{workOrder.incident_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Machine</span>
                <span className="font-medium">{workOrder.incident?.machine_id}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Priority</span>
                <Badge variant={workOrder.priority === 'critical' ? 'danger' : workOrder.priority === 'high' ? 'warning' : 'info'}>{workOrder.priority}</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-surface-500">Status</span>
                <Badge className={getStatusColor(workOrder.status)}>{workOrder.status.replace(/_/g, ' ')}</Badge>
              </div>
            </div>
          </Card>
        </div>
      </div>

      {/* Execute Modal */}
      <Modal
        isOpen={showExecuteModal}
        onClose={() => setShowExecuteModal(false)}
        title={executeAction === 'start' ? 'Start Work Order' : executeAction === 'complete' ? 'Complete Work Order' : 'Place on Hold'}
        size="md"
      >
        <div className="space-y-4">
          <p className="text-surface-600">
            Are you sure you want to {executeAction} work order {workOrder.work_order_number}?
          </p>
          <Textarea
            label="Notes (optional)"
            value={executeNotes}
            onChange={(e) => setExecuteNotes(e.target.value)}
            placeholder={`Enter ${executeAction} notes...`}
            rows={3}
          />
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => setShowExecuteModal(false)} disabled={executing}>
              Cancel
            </Button>
            <Button 
              variant={executeAction === 'start' ? 'primary' : executeAction === 'complete' ? 'success' : 'secondary'} 
              onClick={handleExecute} 
              loading={executing}
            >
              {executeAction === 'start' ? 'Start' : executeAction === 'complete' ? 'Complete' : 'Hold'}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Close Confirmation */}
      <ConfirmDialog
        isOpen={showCloseConfirm}
        onClose={() => setShowCloseConfirm(false)}
        onConfirm={handleCloseConfirm}
        title="Close Work Order"
        message="This will permanently close the work order. This action cannot be undone."
        confirmText="Close Work Order"
        variant="success"
        loading={closing}
      />
    </PageLayout>
  );
}