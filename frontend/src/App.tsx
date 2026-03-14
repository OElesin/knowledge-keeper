import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import AdminDashboard from "./pages/AdminDashboard";
import TwinDetail from "./pages/TwinDetail";
import QueryInterface from "./pages/QueryInterface";

const queryClient = new QueryClient();

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<AdminDashboard />} />
          <Route path="/twins/:employeeId" element={<TwinDetail />} />
          <Route path="/twins/:employeeId/query" element={<QueryInterface />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
