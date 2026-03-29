import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AppShell from "./components/AppShell";
import AdminDashboard from "./pages/AdminDashboard";
import TwinDetail from "./pages/TwinDetail";
import QueryInterface from "./pages/QueryInterface";
import SettingsPage from "./pages/SettingsPage";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AppShell>
          <Routes>
            <Route path="/" element={<AdminDashboard />} />
            <Route path="/twins/:employeeId" element={<TwinDetail />} />
            <Route path="/twins/:employeeId/query" element={<QueryInterface />} />
            <Route path="/settings" element={<SettingsPage />} />
          </Routes>
        </AppShell>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
