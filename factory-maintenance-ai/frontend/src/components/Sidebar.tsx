import { NavLink, useLocation } from 'react-router-dom';
import { 
  LayoutDashboard, 
  AlertTriangle, 
  Search, 
  ClipboardList, 
  FileText, 
  Wrench, 
  CheckCircle,
  Settings,
  Activity
} from 'lucide-react';
import { cn } from '../services/utils';

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Create Incident', href: '/incidents/new', icon: AlertTriangle },
  { name: 'Incidents', href: '/incidents', icon: Search },
  { name: 'AI Investigation', href: '/investigation', icon: Activity },
  { name: 'Maintenance Plans', href: '/plans', icon: ClipboardList },
  { name: 'Work Orders', href: '/work-orders', icon: FileText },
  { name: 'Repair Verification', href: '/verification', icon: CheckCircle },
  { name: 'Settings', href: '/settings', icon: Settings },
];

export function Sidebar() {
  const location = useLocation();
  
  return (
    <aside className="fixed left-0 top-0 z-40 h-screen w-64 bg-surface-900 border-r border-surface-800 transform transition-transform duration-200 lg:translate-x-0">
      <div className="flex h-full flex-col">
        {/* Logo */}
        <div className="flex h-16 items-center justify-center px-6 border-b border-surface-800">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary-600">
              <Wrench className="h-5 w-5 text-white" />
            </div>
            <span className="text-xl font-bold text-white">FactoryAI</span>
          </div>
        </div>
        
        {/* Navigation */}
        <nav className="flex-1 space-y-1 px-4 py-4 overflow-y-auto" aria-label="Main navigation">
          {navigation.map((item) => {
            const isActive = location.pathname === item.href || 
              (item.href !== '/' && location.pathname.startsWith(item.href));
            const Icon = item.icon;
            
            return (
              <NavLink
                key={item.name}
                to={item.href}
                className={cn(
                  'flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                  isActive
                    ? 'bg-primary-600/20 text-white'
                    : 'text-surface-400 hover:text-white hover:bg-surface-800'
                )}
                aria-current={isActive ? 'page' : undefined}
              >
                <Icon className={cn('h-5 w-5 flex-shrink-0', isActive && 'text-primary-400')} aria-hidden="true" />
                {item.name}
              </NavLink>
            );
          })}
        </nav>
        
        {/* Footer */}
        <div className="border-t border-surface-800 p-4">
          <div className="text-xs text-surface-500 text-center">
            Factory Maintenance AI System v1.0
          </div>
        </div>
      </div>
    </aside>
  );
}