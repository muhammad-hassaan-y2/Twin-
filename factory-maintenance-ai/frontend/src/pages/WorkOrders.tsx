import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { 
  FileText, 
  Search, 
  Filter, 
  Plus,
  Wrench,
  User,
  Package,
  Clock,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
} from 'lucide-react';
import { PageLayout, Card, Badge, Button, Input, Select } from '../components/ui';
import { workOrdersApi } from '../services/api';
import { formatDate, getStatusColor, getPriorityColor, cn } from '../services/utils';
import type { WorkOrderListItem, WorkOrderStatus, WorkOrderPriority } from '../types/api';

const statusOptions = [
  { value: '', label: 'All Statuses' },
  { value: 'created', label: 'Created' },
  { value: 'scheduled', label: 'Scheduled' },
  { value: 'in_progress', label: 'In Progress' },
  { value: 'awaiting_verification', label: 'Awaiting Verification' },
  { value: 'verified', label: 'Verified' },
  { value: 'closed', label: 'Closed' },
  { value: 'rejected', label: 'Rejected' },
  { value: 'on_hold', label: 'On Hold' },
];

const priorityOptions = [
  { value: '', label: 'All Priorities' },
  { value: 'critical', label: 'Critical' },
  { value: 'high', label: 'High' },
  { value: 'medium', label: 'Medium' },
  { value: 'low', label: 'Low' },
];

export function WorkOrders() {
  const [workOrders, setWorkOrders] = useState<WorkOrderListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [priorityFilter, setPriorityFilter] = useState('');
  const [page, setPage] = useState(1);
  const pageSize = 10;

  useEffect(() => {
    loadWorkOrders();
  }, [statusFilter, priorityFilter]);

  const loadWorkOrders = async () => {
    try {
      setLoading(true);
      const response = await workOrdersApi.list({
        status: statusFilter || undefined,
        priority: priorityFilter || undefined,
      });
      setWorkOrders(response.data);
      setError(null);
    } catch (err) {
      setError('Failed to load work orders');
      console.error(err);
    } finally {
      setLoading(false);
    }
  };

  const filteredWorkOrders = workOrders
    .filter(wo => 
      wo.work_order_number.toLowerCase().includes(search.toLowerCase()) ||
      wo.machine_id.toLowerCase().includes(search.toLowerCase()) ||
      wo.machine_name.toLowerCase().includes(search.toLowerCase()) ||
      (wo.assigned_technician?.toLowerCase().includes(search.toLowerCase()) ?? false) ||
      (wo.replacement_part?.toLowerCase().includes(search.toLowerCase()) ?? false)
    )
    .sort((a, b) => new Date(b.created_at || 0).getTime() - new Date(a.created_at || 0).getTime());

  const paginatedWorkOrders = filteredWorkOrders.slice(
    (page - 1) * pageSize,
    page * pageSize
  );
  
  const totalFiltered = filteredWorkOrders.length;
  const totalPages = Math.ceil(totalFiltered / pageSize) || 1;

  if (loading) {
    return (
      <PageLayout 
        title="Work Orders" 
        description="Track and manage maintenance work orders"
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
      title="Work Orders" 
      description="Track and manage maintenance work orders"
    >
      {/* Filters */}
      <Card className="mb-6">
        <div className="card-body">
          <div className="flex flex-col sm:flex-row gap-4">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-5 w-5 text-surface-400" />
              <input
                type="text"
                placeholder="Search work orders..."
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
              value={priorityFilter}
              onChange={(e) => { setPriorityFilter(e.target.value); setPage(1); }}
              options={priorityOptions}
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
                <th>WO Number</th>
                <th>Machine</th>
                <th>Technician</th>
                <th>Part</th>
                <th>Priority</th>
                <th>Status</th>
                <th>Scheduled</th>
                <th className="w-20">Actions</th>
              </tr>
            </thead>
            <tbody>
              {paginatedWorkOrders.length === 0 ? (
                <tr>
                  <td colSpan={8} className="text-center py-12">
                    <FileText className="h-12 w-12 text-surface-300 mx-auto mb-3" />
                    <p className="text-surface-500">No work orders found</p>
                  </td>
                </tr>
              ) : (
                paginatedWorkOrders.map((wo) => (
                  <tr key={wo.id}>
                    <td>
                      <Link to={`/work-orders/${wo.id}`} className="font-mono font-medium text-primary-600 hover:text-primary-700">
                        {wo.work_order_number}
                      </Link>
                    </td>
                    <td className="text-surface-600">
                      <div className="font-medium">{wo.machine_id}</div>
                      <div className="text-sm text-surface-500 truncate max-w-xs">{wo.machine_name}</div>
                    </td>
                    <td>
                      {wo.assigned_technician ? (
                        <div className="flex items-center gap-1">
                          <User className="h-4 w-4 text-surface-400" />
                          <span>{wo.assigned_technician}</span>
                        </div>
                      ) : (
                        <span className="text-surface-400">Unassigned</span>
                      )}
                    </td>
                    <td>
                      {wo.replacement_part ? (
                        <div className="flex items-center gap-1">
                          <Package className="h-4 w-4 text-surface-400" />
                          <span className="truncate max-w-xs">{wo.replacement_part}</span>
                        </div>
                      ) : (
                        <span className="text-surface-400">TBD</span>
                      )}
                    </td>
                    <td>
                      <Badge variant={wo.priority === 'critical' ? 'danger' : wo.priority === 'high' ? 'warning' : wo.priority === 'medium' ? 'info' : 'success'}>
                        {wo.priority}
                      </Badge>
                    </td>
                    <td>
                      <Badge className={getStatusColor(wo.status)}>
                        {wo.status.replace(/_/g, ' ')}
                      </Badge>
                    </td>
                    <td className="text-surface-500 whitespace-nowrap">
                      {wo.scheduled_start ? `${formatDate(wo.scheduled_start)}` : 'Not scheduled'}
                    </td>
                    <td>
                      <Link to={`/work-orders/${wo.id}`} className="text-primary-600 hover:text-primary-700 text-sm font-medium">
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
        {totalPages > 1 && (
          <div className="px-6 py-4 border-t border-surface-200 flex items-center justify-between">
            <p className="text-sm text-surface-600">
              Showing {(page - 1) * pageSize + 1} to {Math.min(page * pageSize, totalFiltered)} of {totalFiltered} work orders
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
          </div>
        )}
      </Card>
    </PageLayout>
  );
}