import { Routes, Route, Navigate } from 'react-router-dom';
import { Sidebar } from './components/Sidebar';
import { Dashboard } from './pages/Dashboard';
import { CreateIncident } from './pages/CreateIncident';
import { IncidentsList } from './pages/IncidentsList';
import { Investigation } from './pages/Investigation';
import { MaintenancePlans } from './pages/MaintenancePlans';
import { WorkOrders } from './pages/WorkOrders';
import { RepairVerification } from './pages/RepairVerification';
import { Settings } from './pages/Settings';
import { IncidentDetail } from './pages/IncidentDetail';
import { PlanDetail } from './pages/PlanDetail';
import { WorkOrderDetail } from './pages/WorkOrderDetail';

function AppLayout() {
  return (
    <div className="min-h-screen bg-surface-50">
      <Sidebar />
      <main className="lg:pl-64 min-h-screen">
        <div className="p-6">
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/incidents/new" element={<CreateIncident />} />
            <Route path="/incidents" element={<IncidentsList />} />
            <Route path="/incidents/:id" element={<IncidentDetail />} />
            <Route path="/investigation" element={<Investigation />} />
            <Route path="/investigation/:id" element={<Investigation />} />
            <Route path="/plans" element={<MaintenancePlans />} />
            <Route path="/plans/:id" element={<PlanDetail />} />
            <Route path="/work-orders" element={<WorkOrders />} />
            <Route path="/work-orders/:id" element={<WorkOrderDetail />} />
            <Route path="/verification" element={<RepairVerification />} />
            <Route path="/verification/:id" element={<RepairVerification />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </div>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <AppLayout />
  );
}