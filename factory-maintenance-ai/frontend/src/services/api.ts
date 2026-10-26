import axios from 'axios';
import type {
  Incident,
  IncidentListItem,
  IncidentCreate,
  AgentRunListResponse,
  MaintenancePlan,
  PlanApprovalRequest,
  Technician,
  InventoryPart,
  WorkOrder,
  WorkOrderListItem,
  WorkOrderExecuteRequest,
  RepairVerification,
  RepairVerificationRequest,
  WorkOrderCloseRequest,
  ActivityLog,
  DashboardMetrics,
} from '../types/api';

const api = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'application/json',
  },
});

// Helper for file uploads
const uploadApi = axios.create({
  baseURL: '/api',
  headers: {
    'Content-Type': 'multipart/form-data',
  },
});

// Incidents
export const incidentsApi = {
  create: (data: IncidentCreate, photo: File) => {
    const formData = new FormData();
    formData.append('machine_id', data.machine_id);
    formData.append('machine_name', data.machine_name);
    formData.append('location', data.location);
    formData.append('failure_description', data.failure_description);
    formData.append('severity', data.severity);
    formData.append('photo', photo);
    return uploadApi.post<Incident>('/incidents', formData);
  },
  
  list: (params?: { status?: string; severity?: string; machine_id?: string; limit?: number }) =>
    api.get<IncidentListItem[]>('/incidents', { params }),
  
  get: (id: number) => api.get<Incident>(`/incidents/${id}`),
  
  investigate: (id: number) => api.post(`/incidents/${id}/investigate`),
  
  getAgents: (id: number) => api.get<AgentRunListResponse>(`/incidents/${id}/agents`),
  
  getPlan: (id: number) => api.get<MaintenancePlan>(`/incidents/${id}/plan`),
  
  approve: (id: number, data: PlanApprovalRequest) => api.post(`/incidents/${id}/approve`, data),
};

// Technicians
export const techniciansApi = {
  list: (activeOnly = true) => api.get<Technician[]>('/technicians', { params: { active_only: activeOnly } }),
  create: (data: Partial<Technician>) => api.post<Technician>('/technicians', data),
};

// Parts
export const partsApi = {
  list: (params?: { status?: string; machine_id?: string; critical_only?: boolean }) =>
    api.get<InventoryPart[]>('/parts', { params }),
  create: (data: Partial<InventoryPart>) => api.post<InventoryPart>('/parts', data),
};

// Work Orders
export const workOrdersApi = {
  list: (params?: { status?: string; priority?: string; technician_id?: number }) =>
    api.get<WorkOrderListItem[]>('/work-orders', { params }),
  get: (id: number) => api.get<WorkOrder>(`/work-orders/${id}`),
  execute: (id: number, data: WorkOrderExecuteRequest) => api.post(`/work-orders/${id}/execute`, data),
  verify: (id: number, data: RepairVerificationRequest, photo: File) => {
    const formData = new FormData();
    formData.append('expected_component', data.expected_component);
    if (data.expected_part_number) formData.append('expected_part_number', data.expected_part_number);
    formData.append('photo', photo);
    formData.append('actor', 'Operator'); // TODO: get from auth
    return uploadApi.post<RepairVerification>(`/work-orders/${id}/verification`, formData);
  },
  close: (id: number, data: WorkOrderCloseRequest) => api.post(`/work-orders/${id}/close`, data),
};

// Activity
export const activityApi = {
  list: (incidentId?: number, limit = 50) => 
    api.get<ActivityLog[]>('/activity', { params: { incident_id: incidentId, limit } }),
};

// Dashboard
export const dashboardApi = {
  get: () => api.get<DashboardMetrics>('/dashboard'),
};

// Health
export const healthApi = {
  check: () => api.get('/health'),
};

// Admin
export const adminApi = {
  seed: () => api.post('/admin/seed'),
  reset: () => api.post('/admin/reset'),
};

export default api;