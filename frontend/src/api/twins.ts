import apiClient from "./client";

export interface Twin {
  employeeId: string;
  name: string;
  email: string;
  role: string;
  department: string;
  tenureStart?: string;
  offboardDate: string;
  chunkCount: number;
  status: "ingesting" | "processing" | "embedding" | "active" | "error" | "deleted";
  retentionExpiry?: string;
}

export interface CreateTwinPayload {
  employeeId: string;
  name: string;
  email: string;
  role: string;
  department: string;
  offboardDate: string;
  provider: "google" | "upload";
}

interface ApiResponse<T> {
  success: boolean;
  data: T;
  error: { code: string; message: string; details?: Record<string, unknown> } | null;
  requestId: string;
}

export async function fetchTwins(): Promise<Twin[]> {
  const { data } = await apiClient.get<ApiResponse<Twin[]>>("/twins");
  if (!data.success) throw new Error(data.error?.message ?? "Failed to fetch twins");
  return data.data;
}

export async function fetchTwin(employeeId: string): Promise<Twin> {
  const { data } = await apiClient.get<ApiResponse<Twin>>(`/twins/${employeeId}`);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to fetch twin");
  return data.data;
}

export async function createTwin(payload: CreateTwinPayload): Promise<Twin> {
  const { data } = await apiClient.post<ApiResponse<Twin>>("/twins", payload);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to create twin");
  return data.data;
}

export async function deleteTwin(employeeId: string): Promise<{ deletedAt: string }> {
  const { data } = await apiClient.delete<ApiResponse<{ deletedAt: string }>>(`/twins/${employeeId}`);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to delete twin");
  return data.data;
}

export interface AccessRecord {
  userId: string;
  employeeId: string;
  role: "admin" | "viewer";
}

export interface GrantAccessPayload {
  userId: string;
  role: "admin" | "viewer";
}

export async function fetchAccess(employeeId: string): Promise<AccessRecord[]> {
  const { data } = await apiClient.get<ApiResponse<AccessRecord[]>>(`/twins/${employeeId}/access`);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to fetch access list");
  return data.data;
}

export async function grantAccess(employeeId: string, payload: GrantAccessPayload): Promise<AccessRecord> {
  const { data } = await apiClient.post<ApiResponse<AccessRecord>>(`/twins/${employeeId}/access`, payload);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to grant access");
  return data.data;
}

export async function revokeAccess(employeeId: string, userId: string): Promise<void> {
  const { data } = await apiClient.delete<ApiResponse<null>>(`/twins/${employeeId}/access/${userId}`);
  if (!data.success) throw new Error(data.error?.message ?? "Failed to revoke access");
}

export interface ChunkSource {
  key: string;
  date: string;
  subject: string;
  content: string;
  distance: number;
}

export interface QueryResponse {
  answer: string;
  sources: ChunkSource[];
  confidence: number;
  staleness_warning: string | null;
}

export async function queryTwin(employeeId: string, query: string): Promise<QueryResponse> {
  const { data } = await apiClient.post<ApiResponse<QueryResponse>>(
    `/twins/${employeeId}/query`,
    { query },
  );
  if (!data.success) throw new Error(data.error?.message ?? "Failed to query twin");
  return data.data;
}
