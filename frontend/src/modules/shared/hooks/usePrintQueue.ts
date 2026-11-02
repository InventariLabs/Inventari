import { useEffect, useRef } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import {
  printQueueApi,
  type PrintJob,
  type PrintOptions,
  type PrintTarget,
} from "../lib/printQueue";

/** How often a screen that shows printer state asks again. */
const LIVE_REFRESH_MS = 5_000;

/**
 * The organization's printers. Asked only while the `printing` module is on,
 * so a screen offering "Send to printer" costs nothing where it is off.
 */
export function usePrintAgents(options?: { live?: boolean }) {
  const enabled = useEnabledModulesOptional().includes("printing");
  return useQuery({
    queryKey: queryKeys.printing.agents,
    queryFn: printQueueApi.agents,
    enabled,
    refetchInterval: options?.live ? LIVE_REFRESH_MS : false,
  });
}

const inFlight = (job: PrintJob) =>
  job.status === "queued" || job.status === "printing";

/**
 * A job the agent reports printed marks its labels printed on the server, so
 * the labels on screen are stale from that moment. Refresh them when a job
 * this screen saw in flight comes back printed — not on every poll.
 */
function useLabelsRefreshOnPrinted(jobs: PrintJob[] | undefined) {
  const queryClient = useQueryClient();
  const seenInFlight = useRef<Set<string>>(new Set());
  useEffect(() => {
    if (!jobs) return;
    const landed = jobs.some(
      (job) => job.status === "printed" && seenInFlight.current.has(job.id),
    );
    seenInFlight.current = new Set(jobs.filter(inFlight).map((job) => job.id));
    if (landed) invalidation.labels(queryClient);
  }, [jobs, queryClient]);
}

/** The latest print jobs, refreshed while something is still in flight. */
export function usePrintJobs() {
  const enabled = useEnabledModulesOptional().includes("printing");
  const query = useQuery({
    queryKey: queryKeys.printing.jobs,
    queryFn: printQueueApi.jobs,
    enabled,
    refetchInterval: (current) =>
      current.state.data?.some(inFlight) ? LIVE_REFRESH_MS : false,
  });
  useLabelsRefreshOnPrinted(query.data);
  return query;
}

export function useQueuePrintJob() {
  return useAppMutation(
    (vars: { target: PrintTarget; agentId?: string; options?: PrintOptions }) =>
      printQueueApi.queue(vars),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.printing.jobs });
    },
  );
}

export function useRetryPrintJob() {
  return useAppMutation(
    (jobId: string) => printQueueApi.retry(jobId),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.printing.jobs });
    },
  );
}
