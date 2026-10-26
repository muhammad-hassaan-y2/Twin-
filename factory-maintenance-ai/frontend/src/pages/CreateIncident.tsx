import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { 
  Upload, 
  FileImage, 
  X, 
  Loader2,
  AlertCircle,
  CheckCircle
} from 'lucide-react';
import { PageLayout, Card, Button, Input, Select, Textarea, Badge } from '../components/ui';
import { incidentsApi } from '../services/api';
import { getSeverityColor, cn } from '../services/utils';
import type { Severity } from '../types/api';

const severityOptions = [
  { value: 'low', label: 'Low - Minor issue, no immediate impact' },
  { value: 'medium', label: 'Medium - Degraded performance, schedule repair' },
  { value: 'high', label: 'High - Significant impact, urgent attention needed' },
  { value: 'critical', label: 'Critical - Production stopped, immediate action required' },
];

export function CreateIncident() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState({
    machine_id: '',
    machine_name: '',
    location: '',
    failure_description: '',
    severity: 'medium' as Severity,
  });
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const [errors, setErrors] = useState<Partial<typeof formData>>({});
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  const validateForm = () => {
    const newErrors: Partial<typeof formData> = {};
    if (!formData.machine_id.trim()) newErrors.machine_id = 'Machine ID is required';
    if (!formData.machine_name.trim()) newErrors.machine_name = 'Machine name is required';
    if (!formData.location.trim()) newErrors.location = 'Location is required';
    if (!formData.failure_description.trim()) newErrors.failure_description = 'Failure description is required';
    if (!photo) newErrors.failure_description = 'Component photo is required';
    setErrors(newErrors);
    return Object.keys(newErrors).length === 0;
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSubmitError(null);
    
    if (!validateForm()) return;
    
    setSubmitting(true);
    try {
      const response = await incidentsApi.create(formData, photo!);
      setSuccess(true);
      // Navigate to investigation page after a short delay
      setTimeout(() => {
        navigate(`/investigation/${response.data.id}`);
      }, 1500);
    } catch (err: any) {
      setSubmitError(err.response?.data?.detail || 'Failed to create incident. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  const handlePhotoChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) {
      // Validate file type
      const validTypes = ['image/jpeg', 'image/jpg', 'image/png'];
      if (!validTypes.includes(file.type)) {
        setErrors({ failure_description: 'Invalid file type. Please upload JPG or PNG.' });
        return;
      }
      // Validate file size (10MB)
      if (file.size > 10 * 1024 * 1024) {
        setErrors({ failure_description: 'File too large. Maximum size is 10MB.' });
        return;
      }
      
      setPhoto(file);
      setPhotoPreview(URL.createObjectURL(file));
      setErrors(prev => ({ ...prev, failure_description: '' }));
    }
  };

  const removePhoto = () => {
    setPhoto(null);
    setPhotoPreview(null);
    setErrors(prev => ({ ...prev, failure_description: 'Component photo is required' }));
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ ...prev, [name]: value }));
    if (errors[name as keyof typeof errors]) {
      setErrors(prev => ({ ...prev, [name]: '' }));
    }
  };

  if (success) {
    return (
      <PageLayout title="Incident Submitted" description="Your incident has been created successfully">
        <Card className="max-w-md mx-auto text-center">
          <CheckCircle className="h-16 w-16 text-green-500 mx-auto mb-4" />
          <h2 className="text-xl font-semibold text-surface-900 mb-2">Incident Created</h2>
          <p className="text-surface-600 mb-6">Redirecting to AI Investigation...</p>
          <Loader2 className="h-8 w-8 animate-spin text-primary-600 mx-auto" />
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Create New Incident" description="Report a machine failure and upload a component photo for AI analysis">
      <Card className="max-w-3xl mx-auto">
        <form onSubmit={handleSubmit}>
          {submitError && (
            <div className="mb-6 p-4 bg-red-50 border border-red-200 rounded-lg flex items-start gap-3 text-red-700" role="alert">
              <AlertCircle className="h-5 w-5 flex-shrink-0 mt-0.5" />
              <p>{submitError}</p>
            </div>
          )}

          <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mb-6">
            <Input
              label="Machine ID"
              name="machine_id"
              value={formData.machine_id}
              onChange={handleChange}
              error={errors.machine_id}
              placeholder="e.g., CNC-001"
              required
            />
            <Input
              label="Machine Name"
              name="machine_name"
              value={formData.machine_name}
              onChange={handleChange}
              error={errors.machine_name}
              placeholder="e.g., CNC Machining Center #1"
              required
            />
          </div>

          <Input
            label="Equipment Location"
            name="location"
            value={formData.location}
            onChange={handleChange}
            error={errors.location}
            placeholder="e.g., Production Line A, Station 3"
            required
          />

          <Select
            label="Severity"
            name="severity"
            value={formData.severity}
            onChange={handleChange}
            options={severityOptions}
            placeholder="Select severity"
          />

          <Textarea
            label="Failure Description"
            name="failure_description"
            value={formData.failure_description}
            onChange={handleChange}
            error={errors.failure_description}
            placeholder="Describe the failure in detail: symptoms, when it occurred, any error codes, etc."
            rows={4}
            required
          />

          {/* Photo Upload */}
          <div className="mb-6">
            <label className="label">Failed Component Photo</label>
            <div className="relative">
              <input
                type="file"
                accept="image/jpeg,image/jpg,image/png"
                onChange={handlePhotoChange}
                className="sr-only"
                id="photo-upload"
                disabled={submitting}
                aria-describedby="photo-help"
              />
              <label 
                htmlFor="photo-upload"
                className={cn(
                  'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-colors',
                  photo 
                    ? 'border-green-500 bg-green-50' 
                    : 'border-surface-300 hover:border-primary-500 hover:bg-surface-50'
                )}
              >
                {photoPreview ? (
                  <div className="relative max-w-xs mx-auto">
                    <img 
                      src={photoPreview} 
                      alt="Component photo preview" 
                      className="w-full h-auto rounded-lg shadow" 
                    />
                    <button
                      type="button"
                      onClick={removePhoto}
                      className="absolute top-2 right-2 p-1 bg-red-500 text-white rounded-full hover:bg-red-600 transition-colors"
                      aria-label="Remove photo"
                    >
                      <X className="h-4 w-4" />
                    </button>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-3">
                    <div className="p-3 bg-primary-100 rounded-full">
                      <Upload className="h-8 w-8 text-primary-600" />
                    </div>
                    <div>
                      <p className="text-surface-900 font-medium">Click to upload or drag and drop</p>
                      <p id="photo-help" className="text-sm text-surface-500">JPG or PNG, max 10MB</p>
                    </div>
                  </div>
                )}
              </label>
              {errors.failure_description && !photo && (
                <p className="mt-1 text-sm text-red-600" role="alert">{errors.failure_description}</p>
              )}
            </div>
          </div>

          <div className="flex justify-end gap-3 pt-4 border-t border-surface-200">
            <Button type="button" variant="secondary" onClick={() => navigate('/incidents')}>
              Cancel
            </Button>
            <Button type="submit" variant="primary" loading={submitting}>
              {submitting ? 'Submitting...' : 'Submit Incident'}
            </Button>
          </div>
        </form>
      </Card>
    </PageLayout>
  );
}