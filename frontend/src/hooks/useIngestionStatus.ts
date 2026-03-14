import { useQuery } from "@tanstack/react-query";
import { fetchTwins, type Twin } from "../api/twins";

/**
 * Polls the twin list on an interval while any twin is still ingesting/processing/embedding.
 * Stops polling once all twins are in a terminal state (active, error, deleted).
 */
export function useIngestionStatus() {
  return useQuery({
    queryKey: ["twins", "polling"],
    queryFn: fetchTwins,
    refetchInterval: (query) => {
      const twins = query.state.data as Twin[] | undefined;
      if (!twins) return 5000;
      const hasInProgress = twins.some((t) =>
        ["ingesting", "processing", "embedding"].includes(t.status)
      );
      return hasInProgress ? 5000 : false;
    },
  });
}
