import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  fetchTwins,
  fetchTwin,
  createTwin,
  deleteTwin,
  fetchAccess,
  grantAccess,
  revokeAccess,
  type CreateTwinPayload,
  type GrantAccessPayload,
} from "../api/twins";

export function useTwins() {
  return useQuery({
    queryKey: ["twins"],
    queryFn: fetchTwins,
  });
}

export function useTwin(employeeId: string) {
  return useQuery({
    queryKey: ["twins", employeeId],
    queryFn: () => fetchTwin(employeeId),
    enabled: !!employeeId,
  });
}

export function useCreateTwin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: CreateTwinPayload) => createTwin(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["twins"] });
    },
  });
}

export function useDeleteTwin() {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (employeeId: string) => deleteTwin(employeeId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["twins"] });
    },
  });
}

export function useAccess(employeeId: string) {
  return useQuery({
    queryKey: ["twins", employeeId, "access"],
    queryFn: () => fetchAccess(employeeId),
    enabled: !!employeeId,
  });
}

export function useGrantAccess(employeeId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (payload: GrantAccessPayload) => grantAccess(employeeId, payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["twins", employeeId, "access"] });
    },
  });
}

export function useRevokeAccess(employeeId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (userId: string) => revokeAccess(employeeId, userId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["twins", employeeId, "access"] });
    },
  });
}
