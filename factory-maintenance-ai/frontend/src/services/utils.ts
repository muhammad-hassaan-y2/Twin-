import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatDate(dateString: string | null | undefined): string {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'Invalid date';
  }
}

export function formatDateShort(dateString: string | null | undefined): string {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return 'Invalid date';
  }
}

export function formatTime(dateString: string | null | undefined): string {
  if (!dateString) return 'N/A';
  try {
    return new Date(dateString).toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return 'Invalid time';
  }
}

export function getSeverityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'text-red-700 bg-red-100';
    case 'high': return 'text-orange-700 bg-orange-100';
    case 'medium': return 'text-yellow-700 bg-yellow-100';
    case 'low': return 'text-blue-700 bg-blue-100';
    default: return 'text-surface-700 bg-surface-100';
  }
}

export function getStatusColor(status: string): string {
  switch (status) {
    case 'completed':
    case 'verified':
    case 'closed':
    case 'approved':
    case 'available':
    case 'in_stock':
      return 'text-green-700 bg-green-100';
    case 'running':
    case 'in_progress':
    case 'investigating':
    case 'busy':
    case 'low_stock':
      return 'text-blue-700 bg-blue-100';
    case 'pending':
    case 'submitted':
    case 'plan_proposed':
    case 'awaiting_verification':
    case 'scheduled':
    case 'on_order':
      return 'text-yellow-700 bg-yellow-100';
    case 'failed':
    case 'rejected':
    case 'failed_verification':
    case 'out_of_stock':
    case 'off_duty':
    case 'on_leave':
      return 'text-red-700 bg-red-100';
    case 'draft':
    case 'created':
    case 'on_hold':
      return 'text-surface-700 bg-surface-100';
    default:
      return 'text-surface-700 bg-surface-100';
  }
}

export function getPriorityColor(priority: string): string {
  switch (priority) {
    case 'critical': return 'text-red-700 bg-red-100';
    case 'high': return 'text-orange-700 bg-orange-100';
    case 'medium': return 'text-yellow-700 bg-yellow-100';
    case 'low': return 'text-blue-700 bg-blue-100';
    default: return 'text-surface-700 bg-surface-100';
  }
}

export function truncate(str: string, length: number): string {
  if (str.length <= length) return str;
  return str.slice(0, length) + '...';
}

export function getInitials(name: string): string {
  return name
    .split(' ')
    .map(n => n[0])
    .join('')
    .toUpperCase()
    .slice(0, 2);
}

export function calculateProgress(completed: number, total: number): number {
  if (total === 0) return 0;
  return Math.round((completed / total) * 100);
}

export function formatCurrency(amount: number | null | undefined): string {
  if (amount === null || amount === undefined) return 'N/A';
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
  }).format(amount);
}

export function getFileUrl(path: string | null): string | null {
  if (!path) return null;
  const filename = path.split('/').pop();
  return filename ? `/api/files/${filename}` : null;
}