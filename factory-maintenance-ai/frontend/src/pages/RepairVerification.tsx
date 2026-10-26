import { useEffect, useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { 
  ArrowLeft, 
  CheckCircle, 
  XCircle, 
  AlertTriangle,
  Image,
  Upload,
  Loader2,
  AlertCircle,
  CheckCheck,
  Eye,
  Shield,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal, ConfirmDialog, Textarea } from '../components/ui';
import { workOrdersApi } from '../services/api';
import { formatDate, getStatusColor, getFileUrl, cn } from '../services/utils';
import type { RepairVerification, VerificationStatus } from '../types/api';

export function RepairVerification() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const [verification, setVerification] = useState<RepairVerification | null>(null);
  const [workOrder, setWorkOrder] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [expectedComponent, setExpectedComponent] = useState('');
  const [expectedPartNumber, setExpectedPartNumber] = useState('');
  const [showOverrideModal, setShowOverrideModal] = useState(false);
  const [overrideAction, setOverrideAction] = useState<'approve' | 'reject'>('approve');
  const [overrideReason, setOverrideReason] = useState('');
  const [processingOverride, setProcessingOverride] = useState(false);
  const [verificationResult, setVerificationResult] = useState<any>(null);
  const [showResultModal, setShowResultModal] = useState(false);

  useEffect(() => {
    if (id) loadVerification();
  }, [id]);

  const loadVerification = async () => {
    try {
      setLoading(true);
      // Get work order first to get expected component info
      const woResponse = await workOrdersApi.get(parseInt(id!));
      setWorkOrder(woResponse.data);
      
      // Try to get existing verification
      // The verification is embedded in work order response
      if (woResponse.data.repair_verification) {
        setVerification(woResponse.data.repair_verification);
        setExpectedComponent(woResponse.data.repair_verification.expected_component || '');
        setExpectedPartNumber(woResponse.data.repair_verification.expected_part_number || '');
      } else if (woResponse.data.part) {
        // Use part info as expected
        setExpectedComponent(woResponse.data.part.name);
        setExpectedPartNumber(woResponse.data.part.part_number);
      }
      
      setError(null);
    } catch (err) {
      setError('Failed to load verification');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      const validTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!validTypes.includes(file.type)) {
        alert('Invalid file type. Please upload JPG or PNG.');
        return;
      }
      if (file.size > 10 * 1024 * 1024) {
        alert('File too large. Maximum size is 10MB.');
        return;
      }
      
      setPhoto(file);
      setPhotoPreview(URL.createObjectURL(file));
    }
  };

  const removePhoto = () => {
    setPhoto(null);
    setPhotoPreview(null);
  };

  const handleVerify = async () => {
    if (!photo || !workOrder) return;
    if (!expectedComponent.trim()) {
      alert('Please enter the expected component name');
      return;
    }
    
    setUploading(true);
    try {
      const result = await workOrdersApi.verify(workOrder.id, {
        expected_component: expectedComponent,
        expected_part_number: expectedPartNumber || undefined,
      }, photo);
      
      setVerificationResult(result.data);
      setShowResultModal(true);
      loadVerification(); // Refresh
    } catch (err: any) {
      alert(err.response?.data?.detail || 'Failed to verify repair');
    } finally {
      setUploading(false);
    }
  };

  const handleOverride = async () => {
    if (!verification) return;
    
    setProcessingOverride(true);
    try {
      // This would need a new API endpoint for human override
      // For now, we'll just close the modal and show a message
      alert(`Override ${overrideAction === 'approve' ? 'approved' : 'rejected'}: ${overrideReason}`);
      setShowOverrideModal(false);
      setOverrideReason('');
      loadVerification();
    } catch (err: any) {
      alert('Failed to process override');
    } finally {
      setProcessingOverride(false);
    }
  };

  const canUpload = workOrder?.status === 'awaiting_verification';
  const canOverride = verification && (verification.status === 'failed' || verification.status === 'inconclusive');
  const isVerified = verification?.status === 'verified';
  const isFailed = verification?.status === 'failed';
  const isInconclusive = verification?.status === 'inconclusive';

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

  if (error) {
    return (
      <PageLayout title="Error" description="">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error}</p>
            <Button variant="primary" onClick={() => navigate('/work-orders')} className="mt-4">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Work Orders
            </Button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  const photoUrl = getFileUrl(verification?.repair_photo_path);
  const workOrderPhotoUrl = getFileUrl(workOrder?.incident?.photo_path);

  return (
    <PageLayout 
      title="Repair Verification" 
      description={workOrder ? `${workOrder.work_order_number} • ${workOrder.incident?.machine_name}` : ''}
      actions={
        <div className="flex gap-2">
          <Link to={`/work-orders/${workOrder?.id}`}>
            <Button variant="ghost">
              <ArrowLeft className="h-4 w-4 mr-2" />
              Back to Work Order
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
                <h2 className="text-xl font-bold text-surface-900">Verification Status</h2>
                {verification && (
                  <Badge className={cn('text-lg', getStatusColor(verification.status))}>
                    {verification.status.toUpperCase()}
                  </Badge>
                )}
                {!verification && workOrder && workOrder.status === 'awaiting_verification' && (
                  <Badge className="text-lg" variant="warning">
                    PENDING
                  </Badge>
                )}
              </div>
              <p className="text-surface-600">
                Work Order: {workOrder?.work_order_number} • 
                Machine: {workOrder?.incident?.machine_id}
              </p>
            </div>
            <div className="flex gap-2">
              {canUpload && (
                <Button variant="primary" onClick={() => document.getElementById('photo-input')?.click()}>
                  <Upload className="h-4 w-4 mr-2" />
                  Upload Photo
                </Button>
              )}
              {isVerified && (
                <Button variant="success" disabled>
                  <CheckCircle className="h-4 w-4 mr-2" />
                  Verified
                </Button>
              )}
              {canOverride && !showOverrideModal && (
                <Button variant="secondary" onClick={() => { setOverrideAction('approve'); setShowOverrideModal(true); }}>
                  <Shield className="h-4 w-4 mr-2" />
                  Human Override
                </Button>
              )}
            </div>
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Expected Component */}
        <Card>
          <div className="card-header flex items-center gap-2">
            <Package className="h-5 w-5 text-blue-600" />
            <h2 className="text-lg font-semibold text-surface-900">Expected Component</h2>
          </div>
          <div className="card-body space-y-4">
            <div>
              <label className="text-sm text-surface-500">Component Name</label>
              <input
                type="text"
                value={expectedComponent}
                onChange={(e) => setExpectedComponent(e.target.value)}
                className="input"
                placeholder="e.g., Deep Groove Ball Bearing 6205-2RS"
              />
            </div>
            <div>
              <label className="text-sm text-surface-500">Part Number</label>
              <input
                type="text"
                value={expectedPartNumber}
                onChange={(e) => setExpectedPartNumber(e.target.value)}
                className="input"
                placeholder="e.g., BRG-6205-2RS"
              />
            </div>
            
            {workOrder?.part && (
              <div className="p-4 bg-surface-50 rounded-lg">
                <p className="text-sm text-surface-600">From Work Order:</p>
                <p className="font-medium">{workOrder.part.name}</p>
                <p className="text-sm font-mono text-surface-500">{workOrder.part.part_number}</p>
              </div>
            )}
          </div>
        </Card>

        {/* Original Failure Photo */}
        <Card>
          <div className="card-header flex items-center gap-2">
            <AlertTriangle className="h-5 w-5 text-orange-600" />
            <h2 className="text-lg font-semibold text-surface-900">Original Failure</h2>
          </div>
          <div className="card-body p-0">
            {workOrderPhotoUrl ? (
              <img src={workOrderPhotoUrl} alt="Original failure photo" className="w-full h-auto max-h-[400px] object-contain" />
            ) : (
              <div className="h-64 flex items-center justify-center text-surface-400">
                No original photo available
              </div>
            )}
          </div>
        </Card>
      </div>

      {/* Repair Photo Upload / Display */}
      <Card className="mb-6">
        <div className="card-header flex items-center gap-2">
          <Image className="h-5 w-5 text-green-600" />
          <h2 className="text-lg font-semibold text-surface-900">Repair Completion Photo</h2>
        </div>
        <div className="card-body">
          {photoPreview ? (
            <div className="relative max-w-2xl mx-auto">
              <img src={photoPreview} alt="Repair photo preview" className="w-full h-auto max-h-[500px] object-contain rounded-lg shadow" />
              <button
                type="button"
                onClick={removePhoto}
                className="absolute top-2 right-2 p-1 bg-red-500 text-white rounded-full hover:bg-red-600 transition-colors"
                aria-label="Remove photo"
              >
                <XCircle className="h-4 w-4" />
              </button>
            </div>
          ) : photoUrl ? (
            <div className="relative max-w-2xl mx-auto">
              <img src={photoUrl} alt="Uploaded repair photo" className="w-full h-auto max-h-[500px] object-contain rounded-lg shadow" />
              {canOverride && (
                <div className="mt-4 p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
                  <p className="text-yellow-800">Verification result: {verification?.status}</p>
                  <Button variant="secondary" className="mt-2" onClick={() => { setOverrideAction('approve'); setShowOverrideModal(true); }}>
                    <Shield className="h-4 w-4 mr-2" />
                    Request Human Override
                  </Button>
                </div>
              )}
            </div>
          ) : canUpload ? (
            <div className="relative">
              <input
                id="photo-input"
                type="file"
                accept="image/jpeg,image/jpg,image/png"
                onChange={handlePhotoChange}
                className="sr-only"
              />
              <label 
                htmlFor="photo-input"
                className="border-2 border-dashed border-surface-300 rounded-xl p-12 text-center cursor-pointer hover:border-primary-500 hover:bg-surface-50 transition-colors"
              >
                <div className="flex flex-col items-center gap-3">
                  <div className="p-3 bg-primary-100 rounded-full">
                    <Upload className="h-8 w-8 text-primary-600" />
                  </div>
                  <div>
                    <p className="text-surface-900 font-medium">Click to upload repair completion photo</p>
                    <p className="text-sm text-surface-500">JPG or PNG, max 10MB</p>
                  </div>
                </div>
              </label>
            </div>
          ) : (
            <div className="text-center py-8 text-surface-500">
              Work order must be in "Awaiting Verification" status to upload repair photo
            </div>
          )}

          {canUpload && photo && (
            <div className="mt-4 flex justify-center">
              <Button variant="primary" onClick={handleVerify} loading={uploading} size="lg">
                <CheckCheck className="h-4 w-4 mr-2" />
                {uploading ? 'Verifying...' : 'Verify Repair'}
              </Button>
            </div>
          )}
        </div>
      </Card>

      {/* Verification Results */}
      {verification && (isVerified || isFailed || isInconclusive) && (
        <Card className="mb-6">
          <div className="card-header flex items-center gap-2">
            <Eye className="h-5 w-5 text-purple-600" />
            <h2 className="text-lg font-semibold text-surface-900">Verification Results</h2>
          </div>
          <div className="card-body space-y-4">
            <div className={cn('p-4 rounded-lg', 
              isVerified ? 'bg-green-50 border border-green-200' :
              isFailed ? 'bg-red-50 border border-red-200' :
              'bg-yellow-50 border border-yellow-200'
            )}>
              <div className="flex items-start gap-3">
                {isVerified && <CheckCircle className="h-5 w-5 text-green-600 flex-shrink-0" />}
                {isFailed && <XCircle className="h-5 w-5 text-red-600 flex-shrink-0" />}
                {isInconclusive && <AlertTriangle className="h-5 w-5 text-yellow-600 flex-shrink-0" />}
                <div className="flex-1">
                  <p className="font-medium text-surface-900">
                    {isVerified ? 'Repair Verified Successfully' : isFailed ? 'Verification Failed' : 'Verification Inconclusive'}
                  </p>
                  <p className="text-sm text-surface-600 mt-1">
                    Confidence Score: {verification.confidence_score ? Math.round(verification.confidence_score * 100) + '%' : 'N/A'}
                  </p>
                </div>
              </div>
            </div>

            {verification.verification_details && (
              <div>
                <label className="text-sm text-surface-500">Details</label>
                <pre className="mt-2 text-xs bg-surface-100 p-3 rounded border border-surface-200 overflow-x-auto text-surface-700 max-h-64">
                  {JSON.stringify(verification.verification_details, null, 2)}
                </pre>
              </div>
            )}

            {verification.mismatch_reasons && verification.mismatch_reasons.length > 0 && (
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <label className="text-sm font-medium text-red-800 mb-2 block">Mismatch Reasons:</label>
                <ul className="text-sm text-red-700 space-y-1">
                  {verification.mismatch_reasons.map((reason: string, i: number) => (
                    <li key={i} className="flex items-start gap-2">
                      <XCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                      {reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </Card>
      )}

      {/* Verification Result Modal */}
      {showResultModal && verificationResult && (
        <Modal
          isOpen={showResultModal}
          onClose={() => setShowResultModal(false)}
          title="Verification Complete"
          size="md"
        >
          <div className="space-y-4">
            <div className={cn('p-4 rounded-lg text-center',
              verificationResult.verified ? 'bg-green-50 border border-green-200' :
              'bg-red-50 border border-red-200'
            )}>
              {verificationResult.verified ? (
                <CheckCircle className="h-12 w-12 text-green-500 mx-auto mb-2" />
              ) : (
                <XCircle className="h-12 w-12 text-red-500 mx-auto mb-2" />
              )}
              <h3 className="text-lg font-semibold text-surface-900">
                {verificationResult.verified ? 'Repair Verified' : 'Verification Failed'}
              </h3>
              <p className="text-sm text-surface-600 mt-1">
                Confidence: {Math.round((verificationResult.confidence_score || 0) * 100)}%
              </p>
            </div>
            
            {verificationResult.mismatch_reasons && verificationResult.mismatch_reasons.length > 0 && (
              <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
                <label className="text-sm font-medium text-red-800 mb-2 block">Mismatch Reasons:</label>
                <ul className="text-sm text-red-700 space-y-1">
                  {verificationResult.mismatch_reasons.map((reason: string, i: number) => (
                    <li key={i} className="flex items-start gap-2">
                      <XCircle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                      {reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex justify-end gap-3 pt-4">
              <Button variant="secondary" onClick={() => setShowResultModal(false)}>
                Close
              </Button>
              {verificationResult.verified && (
                <Link to={`/work-orders/${workOrder?.id}`}>
                  <Button variant="success">
                    <CheckCheck className="h-4 w-4 mr-2" />
                    Close Work Order
                  </Button>
                </Link>
              )}
            </div>
          </div>
        </Modal>
      )}

      {/* Human Override Modal */}
      {showOverrideModal && (
        <Modal
          isOpen={showOverrideModal}
          onClose={() => { setShowOverrideModal(false); setOverrideReason(''); }}
          title={overrideAction === 'approve' ? 'Approve Despite Failed Verification' : 'Reject Verification'}
          size="md"
        >
          <div className="space-y-4">
            <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
              <p className="font-medium text-yellow-800">Human Override</p>
              <p className="text-sm text-yellow-700 mt-1">
                You are overriding the AI verification result. This should only be done when you have visually confirmed the repair.
              </p>
            </div>
            
            <div className="flex gap-3 mb-4">
              <Button 
                variant={overrideAction === 'approve' ? 'success' : 'secondary'} 
                onClick={() => setOverrideAction('approve')}
                className="flex-1"
              >
                <CheckCircle className="h-4 w-4 mr-2" />
                Approve Repair
              </Button>
              <Button 
                variant={overrideAction === 'reject' ? 'danger' : 'secondary'} 
                onClick={() => setOverrideAction('reject')}
                className="flex-1"
              >
                <XCircle className="h-4 w-4 mr-2" />
                Reject Repair
              </Button>
            </div>
            
            <Textarea
              label="Override Reason (required)"
              value={overrideReason}
              onChange={(e) => setOverrideReason(e.target.value)}
              placeholder="Explain why you are overriding the AI verification..."
              rows={3}
              required
            />
            
            <div className="flex justify-end gap-3 pt-4">
              <Button variant="secondary" onClick={() => { setShowOverrideModal(false); setOverrideReason(''); }} disabled={processingOverride}>
                Cancel
              </Button>
              <Button 
                variant={overrideAction === 'approve' ? 'success' : 'danger'} 
                onClick={handleOverride} 
                loading={processingOverride}
                disabled={!overrideReason.trim()}
              >
                {overrideAction === 'approve' ? 'Approve Repair' : 'Reject Repair'}
              </Button>
            </div>
          </div>
        </Modal>
      )}
    </PageLayout>
  );
}