import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { 
  Search, 
  Filter, 
  Plus, 
  AlertTriangle,
  ChevronLeft,
  ChevronRight
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Input, Select } from '../components/ui';
import { incidentsApi } from '../services/api';
import { formatDate, getStatusColor, getSeverityColor, cn } from '../services/utils';
import type { IncidentListItem, IncidentStatus, Severity } from '../types/api';

const statusOptions = [
  { value: '', label: 'All Statuses' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'investigating', label: 'Investigating' },
  { value: 'plan_proposed', label: 'Plan Proposed' },
  { value: 'approved', label: 'Approved' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'work_order_created', label: 'Work Order Created' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'awaiting_verification', label: 'Awaiting Verification' },
  { value: 'verified', label: 'Verified' },
  { value: 'closed', label: 'Closed' },
  { value: 'failed_verification', label: 'Failed Verification' },
];

const severityFilterOptions = [
  { value: '', label: 'All Severities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

export function IncidentsList() {
  const [incidents, setIncidents] = useState<IncidentListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [severityFilter, setSeverityFilter] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    loadIncidents();
  }, [page, statusFilter, severityFilter]);

  const loadIncidents = async () => {
    try {
      setLoading(true);
      const response = await incidentsApi.list({
        status: statusFilter || undefined,
        severity: severityFilter || undefined,
        limit: 100, // Get more for client-side search
      });
      setIncidents(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load incidents');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const filteredIncidents = incidents
    .filter(inc => 
      inc.machine_id.toLowerCase().includes(search.toLowerCase()) ||
      inc.machine_name.toLowerCase().includes(search.toLowerCase()) ||
      inc.location.toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

  const paginatedIncidents = filteredIncidents.slice(
    (page - 1) * pageSize,
    page * pageSize
  );
  
  const totalFiltered = filteredIncidents.length;
  const calculatedTotalPages = Math.ceil(totalFiltered / pageSize) || 1;

  if (loading) {
    return (
      <PageLayout 
        title="Incidents" 
        description="View and manage all maintenance incidents"
        actions={
          <Button variant="primary" onClick={() => window.location.href = '/incidents/new'}>
            <Plus className="h-4 w-4 mr-2" />
            New Incident
          </Button>
        }
      >
        <Card>
          <div className="animate-pulse space-y-4">
            {[...Array(5)].map((_, i) => (
              <div key={i} className="h-16 bg-surface-200 rounded" />
            ))}
          </div>
        </Card>
      </PageLayout>
    );
  }

  return (
    <PageLayout 
      title="Incidents" 
      description="View and manage all maintenance incidents"
      actions={
        <Button variant="primary" onClick={() => window.location.href = '/incidents/new'}>
          <Plus className="h-4 w-4 mr-2" />
          New Incident
        </Button>
      }
    >
      {/* Filters */}
      <Card className="mb-6">
        <div className="card-body">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-surface-400" />
              <input
                type="text"
                placeholder="Search incidents..."
                value={search}
                onChange={(e) => { setSearch(e.target.value); setPage(1); }}
                className="input pl-10"
              />
            </div>
            <Select
              value={statusFilter}
              onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
              options={statusOptions}
              className="w-full sm:w-48"
            />
            <Select
              value={severityFilter}
              onChange={(e) => { setSeverityFilter(e.target.value); setPage(1); }}
              options={severityFilterOptions}
              className="w-full sm:w-40"
            />
          </div>
        </div>
      </Card>

      {/* Results */}
      <Card>
        {error && (
          <div className="p-4 bg-red-50 border-b border-red-200 text-red-700">{error}</div>
        )}
        <div className="table-container">
          <table className="table">
            <thead>
              <tr>
                <th>Machine</th>
                <th>Location</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Created</th>
                <th className="w-24">Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedIncidents.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-12">
                    <AlertTriangle className="h-12 w-12 text-surface-300 mx-auto mb-3" />
                    <p className="text-surface-500">No incidents found</p>
                  </td>
                </tr>
              ) : (
                paginatedIncidents.map((incident) => (
                  <tr key={incident.id}>
                    <td>
                      <Link to={`/incidents/${incident.id}`} className="font-mono font-medium text-primary-600 hover:text-primary-700">
                        {incident.machine_id}
                      </Link>
                    </td>
                    <td className="text-surface-600 truncate max-w-xs">
                      <div className="font-medium">{incident.machine_name}</div>
                      <div className="text-sm text-surface-500">{incident.location}</div>
                    </td>
                    <td>
                      <Badge 
                        variant={incident.severity === 'critical' ? 'danger' : incident.severity === 'high' ? 'warning' : incident.severity === 'medium' ? 'info' : 'success'}
                      >
                        {incident.severity}
                      </Badge>
                    </td>
                    <td>
                      <Badge className={getStatusColor(incident.status)}>
                        {incident.status.replace(/_/g, ' ')}
                      </Badge>
                    </td>
                    <td className="text-surface-500 whitespace-nowrap">{formatDate(incident.created_at)}</td>
                    <td>
                      <Link to={`/incidents/${incident.id}`} className="text-primary-600 hover:text-primary-700 text-sm font-medium">
                        View
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        
        {/* Pagination */}
        {calculatedTotalPages > 1 && (
          <div className="px-6 py-4 border-t border-surface-200 flex items-center justify-between">
            <p className="text-sm text-surface-600">
              Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalFiltered)} of {totalFiltered} incidents
            </p>
            <div className="flex gap-2">
              <Button 
                variant="secondary" 
                size="sm"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
              >
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <span className="px-3 py-1 text-sm text-surface-600">
                Page {page} of {calculatedTotalPages}
              </span>
              <Button 
                variant="secondary" 
                size="sm"
                onClick={() => setPage(p => Math.min(calculatedTotalPages, p + 1))}
                disabled={page === calculatedTotalPages}
              >
                <ChevronRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        )}
      </Card>
    </PageLayout>
  );
}