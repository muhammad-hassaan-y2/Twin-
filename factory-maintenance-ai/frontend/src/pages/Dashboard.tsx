import { useEffect, useState } from 'react';
import { 
  AlertTriangle, 
  FileText, 
  Clock, 
  CheckCircle, 
  TrendingUp,
  Users,
  Package,
  AlertCircle
} from 'lucide-react';
import { PageLayout, Card, Badge } from '../components/ui';
import { dashboardApi } from '../services/api';
import { formatDate, getStatusColor, getSeverityColor, formatCurrency, cn } from '../services/utils';
import type { DashboardMetrics, IncidentListItem, ActivityLog } from '../types/api';

const statCards = [
  { name: 'Total Incidents', key: 'total_incidents', icon: AlertTriangle, color: 'text-blue-600 bg-blue-100' },
  { name: 'Active Work Orders', key: 'active_work_orders', icon: FileText, color: 'text-orange-600 bg-orange-100' },
  { name: 'Pending Approvals', key: 'pending_approvals', icon: Clock, color: 'text-yellow-600 bg-yellow-100' },
  { name: 'Awaiting Verification', key: 'repairs_awaiting_verification', icon: CheckCircle, color: 'text-green-600 bg-green-100' },
];

export function Dashboard() {
  const [metrics, setMetrics] = useState<DashboardMetrics | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadDashboard();
  }, []);

  const loadDashboard = async () => {
    try {
      setLoading(true);
      const response = await dashboardApi.get();
      setMetrics(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load dashboard data');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  if (loading) {
    return (
      <PageLayout title="Dashboard" description="Overview of maintenance operations">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => (
            <Card key={i} className="animate-pulse">
              <div className="h-4 bg-surface-200 rounded w-3/4 mb-2" />
              <div className="h-8 bg-surface-200 rounded w-1/4" />
            </Card>
          ))}
        </div>
      </PageLayout>
    );
  }

  if (error) {
    return (
      <PageLayout title="Dashboard" description="Overview of maintenance operations">
        <Card>
          <div className="text-center py-8">
            <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
            <p className="text-red-600">{error}</p>
            <button onClick={loadDashboard} className="mt-4 btn-primary">Retry</button>
          </div>
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="Dashboard" description="Overview of maintenance operations">
      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        {statCards.map((stat) => {
          const value = metrics?.[stat.key as keyof DashboardMetrics] ?? 0;
          const Icon = stat.icon;
          return (
            <Card key={stat.key}>
              <div className="flex items-start justify-between">
                <div>
                  <p className="text-sm font-medium text-surface-600">{stat.name}</p>
                  <p className="text-3xl font-bold text-surface-900 mt-1">{value}</p>
                </div>
                <div className={cn('p-3 rounded-xl', stat.color)}>
                  <Icon className="h-6 w-6" aria-hidden="true" />
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      {/* Recent Incidents & Activity */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Recent Incidents */}
        <Card>
          <div className="card-header flex items-center justify-between">
            <h2 className="text-lg font-semibold text-surface-900">Recent Incidents</h2>
            <a href="/incidents" className="text-sm text-primary-600 hover:text-primary-700">View all</a>
          </div>
          <div className="card-body p-0">
            <div className="table-container">
              <table className="table">
                <thead>
                  <tr>
                    <th>Machine</th>
                    <th>Location</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {metrics?.recent_incidents.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="text-center py-8 text-surface-500">No incidents yet</td>
                    </tr>
                  ) : (
                    metrics?.recent_incidents.map((incident: IncidentListItem) => (
                      <tr key={incident.id}>
                        <td className="font-mono font-medium">{incident.machine_id}</td>
                        <td className="text-surface-600 truncate max-w-xs">{incident.machine_name}</td>
                        <td>
                          <Badge variant={incident.severity === 'critical' ? 'danger' : incident.severity === 'high' ? 'warning' : incident.severity === 'medium' ? 'info' : 'success'}>
                            {incident.severity}
                          </Badge>
                        </td>
                        <td>
                          <Badge className={getStatusColor(incident.status)}>
                            {incident.status.replace(/_/g, ' ')}
                          </Badge>
                        </td>
                        <td className="text-surface-500 whitespace-nowrap">{formatDateShort(incident.created_at)}</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </Card>

        {/* Recent Activity */}
        <Card>
          <div className="card-header flex items-center justify-between">
            <h2 className="text-lg font-semibold text-surface-900">Recent Activity</h2>
            <a href="/activity" className="text-sm text-primary-600 hover:text-primary-700">View all</a>
          </div>
          <div className="card-body p-0">
            <div className="divide-y divide-surface-100">
              {metrics?.recent_activity.length === 0 ? (
                <div className="p-8 text-center text-surface-500">No recent activity</div>
              ) : (
                metrics?.recent_activity.map((activity: ActivityLog) => (
                  <div key={activity.id} className="p-4 hover:bg-surface-50">
                    <div className="flex items-start gap-3">
                      <div className={cn('p-2 rounded-lg', 
                        activity.actor_type === 'agent' ? 'bg-primary-100 text-primary-700' :
                        activity.actor_type === 'human' ? 'bg-green-100 text-green-700' :
                        'bg-surface-100 text-surface-700'
                      )}>
                        {activity.actor_type === 'agent' && <Activity className="h-4 w-4" />}
                        {activity.actor_type === 'human' && <Users className="h-4 w-4" />}
                        {activity.actor_type === 'system' && <Package className="h-4 w-4" />}
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-surface-900">{activity.description || activity.action}</p>
                        <p className="text-xs text-surface-500">
                          {activity.actor || 'System'} • {formatDate(activity.created_at)}
                        </p>
                        {activity.from_status && activity.to_status && (
                          <p className="text-xs text-surface-500 mt-1">
                            Status: <span className="font-medium">{activity.from_status}</span> → <span className="font-medium">{activity.to_status}</span>
                          </p>
                        )}
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          </div>
        </Card>
      </div>

      {/* Agent Execution Summary */}
      {metrics?.agent_execution_summary && Object.keys(metrics.agent_execution_summary).length > 0 && (
        <Card className="mt-6">
          <div className="card-header">
            <h2 className="text-lg font-semibold text-surface-900">Agent Execution Summary</h2>
          </div>
          <div className="card-body">
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {Object.entries(metrics.agent_execution_summary).map(([agent, stats]) => (
                <div key={agent} className="p-4 bg-surface-50 rounded-lg">
                  <h3 className="font-medium text-surface-900 mb-2">{agent}</h3>
                  <div className="flex gap-4 text-sm">
                    <span className={cn('font-medium', getStatusColor('completed'))}>✓ {stats.completed || 0}</span>
                    <span className={cn('font-medium', getStatusColor('failed'))}>✗ {stats.failed || 0}</span>
                    <span className={cn('font-medium', getStatusColor('pending'))}>○ {stats.pending || 0}</span>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </Card>
      )}
    </PageLayout>
  );
}