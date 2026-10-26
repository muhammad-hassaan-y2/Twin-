export type Severity = 'low' | 'medium' | 'high' | 'critical';

export type IncidentStatus = 
  | 'submitted'
  | 'investigating'
  | 'plan_proposed'
  | 'approved'
  | 'rejected'
  | 'work_order_created'
  | 'in_progress'
  | 'awaiting_verification'
  | 'verified'
  | 'closed'
  | 'failed_verification';

export type AgentStatus = 'pending' | 'running' | 'completed' | 'failed';

export type PlanStatus = 'draft' | 'proposed' | 'approved' | 'rejected';

export type TechnicianStatus = 'available' | 'busy' | 'off_duty' | 'on_leave';

export type PartStatus = 'in_stock' | 'low_stock' | 'out_of_stock' | 'on_order' | 'discontinued';

export type WorkOrderStatus = 
  | 'created'
  | 'scheduled'
  | 'in_progress'
  | 'awaiting_verification'
  | 'verified'
  | 'closed'
  | 'rejected'
  | 'on_hold';

export type WorkOrderPriority = 'low' | 'medium' | 'high' | 'critical';

export type VerificationStatus = 'pending' | 'verified' | 'failed' | 'inconclusive';

export interface Incident {
  id: number;
  machine_id: string;
  machine_name: string;
  location: string;
  failure_description: string;
  severity: Severity;
  status: IncidentStatus;
  photo_path: string | null;
  created_at: string;
  updated_at: string;
}

export interface IncidentListItem {
  id: number;
  machine_id: string;
  machine_name: string;
  location: string;
  severity: Severity;
  status: IncidentStatus;
  created_at: string;
}

export interface IncidentCreate {
  machine_id: string;
  machine_name: string;
  location: string;
  failure_description: string;
  severity: Severity;
}

export interface AgentRun {
  id: number;
  incident_id: number;
  agent_name: string;
  agent_order: number;
  status: AgentStatus;
  current_task: string | null;
  input_data: Record<string, any> | null;
  output_data: Record<string, any> | null;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface AgentRunListResponse {
  agents: AgentRun[];
  overall_status: string;
  completed_count: number;
  total_count: number;
}

export interface PartInfo {
  id: number;
  part_number: string;
  name: string;
  description: string | null;
  unit_cost: number | null;
  quantity_on_hand: number;
  status: string;
  lead_time_days: number;
}

export interface TechnicianInfo {
  id: number;
  name: string;
  email: string;
  skills: string[];
  status: string;
}

export interface MaintenancePlan {
  id: number;
  incident_id: number;
  status: PlanStatus;
  identified_failure: string | null;
  suspected_root_cause: string | null;
  recommended_part: PartInfo | null;
  part_availability: string | null;
  estimated_part_cost: number | null;
  recommended_technician: TechnicianInfo | null;
  estimated_repair_duration_hours: number | null;
  proposed_downtime_start: string | null;
  proposed_downtime_end: string | null;
  risk_level: string | null;
  risk_assessment: string | null;
  proposed_work_order_priority: string | null;
  proposed_work_order_notes: string | null;
  approved_by: string | null;
  approved_at: string | null;
  rejection_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface PlanApprovalRequest {
  approve: boolean;
  reviewer: string;
  rejection_reason?: string;
}

export interface Technician {
  id: number;
  name: string;
  email: string;
  phone: string | null;
  skills: string[];
  certifications: string[];
  status: TechnicianStatus;
  current_work_order_id: number | null;
  max_concurrent_jobs: number;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface InventoryPart {
  id: number;
  part_number: string;
  name: string;
  description: string | null;
  category: string | null;
  manufacturer: string | null;
  compatible_machines: string[];
  unit_cost: number | null;
  quantity_on_hand: number;
  reorder_point: number;
  reorder_quantity: number;
  lead_time_days: number;
  status: PartStatus;
  location: string | null;
  is_critical: boolean;
  created_at: string;
  updated_at: string;
}

export interface WorkOrder {
  id: number;
  work_order_number: string;
  incident_id: number;
  maintenance_plan_id: number | null;
  assigned_technician_id: number | null;
  replacement_part_id: number | null;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  scheduled_start: string | null;
  scheduled_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  progress_notes: string | null;
  completion_notes: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
  updated_at: string;
  incident?: {
    id: number;
    machine_id: string;
    machine_name: string;
  };
  technician?: {
    id: number;
    name: string;
    email: string;
  };
  part?: {
    id: number;
    part_number: string;
    name: string;
  };
}

export interface WorkOrderListItem {
  id: number;
  work_order_number: string;
  incident_id: number;
  machine_id: string;
  machine_name: string;
  assigned_technician: string | null;
  replacement_part: string | null;
  priority: WorkOrderPriority;
  status: WorkOrderStatus;
  scheduled_start: string | null;
  scheduled_end: string | null;
}

export interface WorkOrderExecuteRequest {
  action: 'start' | 'complete' | 'hold';
  notes?: string;
  actor: string;
}

export interface RepairVerification {
  id: number;
  work_order_id: number;
  expected_component: string;
  expected_part_number: string | null;
  repair_photo_path: string | null;
  status: VerificationStatus;
  confidence_score: number | null;
  verification_details: Record<string, any> | null;
  mismatch_reasons: string[] | null;
  reviewed_by: string | null;
  reviewed_at: string | null;
  human_override: boolean;
  override_reason: string | null;
  created_at: string;
  updated_at: string;
}

export interface RepairVerificationRequest {
  expected_component: string;
  expected_part_number?: string;
}

export interface WorkOrderCloseRequest {
  actor: string;
  notes?: string;
}

export interface ActivityLog {
  id: number;
  incident_id: number;
  work_order_id: number | null;
  action: string;
  actor: string | null;
  actor_type: string | null;
  description: string | null;
  details: Record<string, any> | null;
  from_status: string | null;
  to_status: string | null;
  created_at: string;
}

export interface DashboardMetrics {
  total_incidents: number;
  active_work_orders: number;
  pending_approvals: number;
  repairs_awaiting_verification: number;
  recent_incidents: IncidentListItem[];
  recent_activity: ActivityLog[];
  agent_execution_summary: Record<string, Record<string, number>>;
}