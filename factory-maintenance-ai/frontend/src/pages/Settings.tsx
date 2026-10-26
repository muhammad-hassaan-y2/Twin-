import { useEffect, useState } from 'react';
import { 
  Database, 
  Server, 
  Download, 
  Upload,
  RefreshCw,
  AlertCircle,
  CheckCircle,
  Loader2,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Modal } from '../components/ui';
import { adminApi, healthApi } from '../services/api';
import { cn } from '../services/utils';

export function Settings() {
  const [health, setHealth] = useState<any>(null);
  const [seeding, setSeeding] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [seedResult, setSeedResult] = useState<{ success: boolean; message: string } | null>(null);
  const [showResetConfirm, setShowResetConfirm] = useState(false);

  useEffect(() => {
    checkHealth();
  }, []);

  const checkHealth = async () => {
    try {
      const response = await healthApi.check();
      setHealth(response.data);
    } catch (err) {
      console.error('Health check failed', err);
    }
  };

  const handleSeed = async () => {
    setSeeding(true);
    setSeedResult(null);
    try {
      const response = await adminApi.seed();
      setSeedResult({ success: true, message: `Database seeded successfully! ${JSON.stringify(response.data.counts)}` });
    } catch (err: any) {
      setSeedResult({ success: false, message: err.response?.data?.detail || 'Failed to seed database' });
    } finally {
      setSeeding(false);
    }
  };

  const handleReset = async () => {
    setResetting(true);
    setSeedResult(null);
    try {
      const response = await adminApi.reset();
      setSeedResult({ success: true, message: `Database reset and seeded successfully! ${JSON.stringify(response.data.counts)}` });
      checkHealth();
    } catch (err: any) {
      setSeedResult({ success: false, message: err.response?.data?.detail || 'Failed to reset database' });
    } finally {
      setResetting(false);
      setShowResetConfirm(false);
    }
  };

  return (
    <PageLayout title="Settings" description="System configuration and administration">
      {/* System Health */}
      <Card className="mb-6">
        <div className="card-header flex items-center justify-between">
          <h2 className="text-lg font-semibold text-surface-900 flex items-center gap-2">
            <Server className="h-5 w-5" />
            System Health
          </h2>
          <Button variant="ghost" size="sm" onClick={checkHealth}>
            <RefreshCw className="h-4 w-4 mr-1" />
            Refresh
          </Button>
        </div>
        <div className="card-body">
          {health ? (
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div className={cn('p-4 rounded-lg', health.status === 'healthy' ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200')}>
                <div className="flex items-center gap-2 mb-2">
                  {health.status === 'healthy' ? (
                    <CheckCircle className="h-5 w-5 text-green-600" />
                  ) : (
                    <AlertCircle className="h-5 w-5 text-red-600" />
                  )}
                  <span className="font-medium text-surface-900">{health.status.toUpperCase()}</span>
                </div>
                <p className="text-sm text-surface-600">API Status</p>
              </div>
              <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
                <p className="text-sm text-surface-600">Version</p>
                <p className="font-mono font-medium">{health.version}</p>
              </div>
              <div className="p-4 bg-surface-50 rounded-lg border border-surface-200">
                <p className="text-sm text-surface-600">Database</p>
                <p className="font-mono font-medium">{health.database}</p>
              </div>
            </div>
          ) : (
            <div className="flex items-center gap-2 text-surface-500">
              <Loader2 className="h-5 w-5 animate-spin" />
              Checking system health...
            </div>
          )}
        </div>
      </Card>

      {/* Database Management */}
      <Card className="mb-6">
        <div className="card-header flex items-center gap-2">
          <Database className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-surface-900">Database Management</h2>
        </div>
        <div className="card-body space-y-4">
          <div className="p-4 bg-yellow-50 border border-yellow-200 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-yellow-600 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-yellow-800">Warning: Destructive Actions</p>
                <p className="text-sm text-yellow-700 mt-1">
                  These actions will modify the database. Use with caution in production environments.
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-4 border border-surface-200 rounded-lg">
              <h3 className="font-medium text-surface-900 mb-2">Seed Database</h3>
              <p className="text-sm text-surface-600 mb-4">
                Populates the database with sample technicians, parts, and historical incidents.
                Safe to run multiple times - only creates data if tables are empty.
              </p>
              <Button 
                variant="primary" 
                onClick={handleSeed} 
                loading={seeding}
                className="w-full"
              >
                <Download className="h-4 w-4 mr-2" />
                Seed Database
              </Button>
            </div>

            <div className="p-4 border border-red-200 rounded-lg bg-red-50">
              <h3 className="font-medium text-red-900 mb-2">Reset Database</h3>
              <p className="text-sm text-red-700 mb-4">
                Completely drops all tables and recreates them with seed data. 
                <strong>All existing data will be permanently lost.</strong>
              </p>
              <Button 
                variant="danger" 
                onClick={() => setShowResetConfirm(true)} 
                loading={resetting}
                className="w-full"
              >
                <Upload className="h-4 w-4 mr-2" />
                Reset Database
              </Button>
            </div>
          </div>

          {seedResult && (
            <div className={cn('p-4 rounded-lg', seedResult.success ? 'bg-green-50 border border-green-200' : 'bg-red-50 border border-red-200')}>
              <div className="flex items-center gap-3">
                {seedResult.success ? (
                  <CheckCircle className="h-5 w-5 text-green-600" />
                ) : (
                  <AlertCircle className="h-5 w-5 text-red-600" />
                )}
                <span className={cn('text-sm', seedResult.success ? 'text-green-800' : 'text-red-800')}>
                  {seedResult.message}
                </span>
              </div>
            </div>
          )}
        </div>
      </Card>

      {/* API Information */}
      <Card className="mb-6">
        <div className="card-header flex items-center gap-2">
          <Server className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-surface-900">API Information</h2>
        </div>
        <div className="card-body">
          <div className="space-y-4 text-sm">
            <div className="flex justify-between">
              <span className="text-surface-500">API Base URL</span>
              <code className="font-mono bg-surface-100 px-2 py-1 rounded">/api</code>
            </div>
            <div className="flex justify-between">
              <span className="text-surface-500">Swagger Documentation</span>
              <a href="/docs" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700 font-mono">
                /docs
              </a>
            </div>
            <div className="flex justify-between">
              <span className="text-surface-500">ReDoc Documentation</span>
              <a href="/redoc" target="_blank" rel="noopener noreferrer" className="text-primary-600 hover:text-primary-700 font-mono">
                /redoc
              </a>
            </div>
            <div className="flex justify-between">
              <span className="text-surface-500">File Uploads</span>
              <code className="font-mono bg-surface-100 px-2 py-1 rounded">/api/files/{filename}</code>
            </div>
          </div>
        </div>
      </Card>

      {/* Environment */}
      <Card>
        <div className="card-header flex items-center gap-2">
          <Server className="h-5 w-5" />
          <h2 className="text-lg font-semibold text-surface-900">Environment Configuration</h2>
        </div>
        <div className="card-body">
          <p className="text-sm text-surface-600 mb-4">
            Configure the following environment variables in <code className="bg-surface-100 px-1.5 py-0.5 rounded font-mono">.env</code>:
          </p>
          <div className="space-y-2 text-sm font-mono bg-surface-900 text-surface-100 p-4 rounded-lg overflow-x-auto">
            <div>DATABASE_URL=sqlite:///./factory_maintenance.db</div>
            <div>UPLOAD_DIR=./uploads</div>
            <div>MAX_FILE_SIZE=10485760</div>
            <div>ALLOWED_EXTENSIONS=jpg,jpeg,png</div>
            <div className="text-surface-500"># Optional LLM Integration</div>
            <div className="text-surface-500">LLM_API_KEY=</div>
            <div className="text-surface-500">LLM_API_URL=</div>
            <div className="text-surface-500">LLM_MODEL=</div>
            <div className="text-surface-500"># Application</div>
            <div>APP_ENV=development</div>
            <div>DEBUG=true</div>
            <div>SECRET_KEY=your-secret-key-change-in-production</div>
          </div>
        </div>
      </Card>

      {/* Reset Confirmation Modal */}
      <Modal
        isOpen={showResetConfirm}
        onClose={() => setShowResetConfirm(false)}
        title="Confirm Database Reset"
        size="md"
      >
        <div className="space-y-4">
          <div className="p-4 bg-red-50 border border-red-200 rounded-lg">
            <div className="flex items-start gap-3">
              <AlertCircle className="h-5 w-5 text-red-600 flex-shrink-0" />
              <div>
                <p className="font-medium text-red-800">This action cannot be undone!</p>
                <p className="text-sm text-red-700 mt-1">
                  All incidents, work orders, agents runs, maintenance plans, technicians, parts, and activity logs will be permanently deleted.
                </p>
              </div>
            </div>
          </div>
          
          <p className="text-surface-600">Type "RESET" to confirm:</p>
          <input
            type="text"
            placeholder="RESET"
            className="input font-mono"
            onKeyDown={(e) => {
              if (e.key === 'Enter' && e.currentTarget.value === 'RESET') {
                handleReset();
              }
            }}
          />
          
          <div className="flex justify-end gap-3 pt-4">
            <Button variant="secondary" onClick={() => setShowResetConfirm(false)} disabled={resetting}>
              Cancel
            </Button>
            <Button 
              variant="danger" 
              onClick={handleReset} 
              loading={resetting}
              disabled={resetting}
            >
              Reset Database
            </Button>
          </div>
        </div>
      </Modal>
    </PageLayout>
  );
}