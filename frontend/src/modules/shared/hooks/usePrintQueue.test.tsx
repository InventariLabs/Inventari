import type { ReactNode } from "react";
import { act, renderHook, waitFor } from "@testing-library/react";
import {
  QueryClient,
  QueryClientProvider,
  useQuery,
} from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import { usePrintJobs } from "./usePrintQueue";
import { onePage } from "@/test/mocks/page";

vi.mock("@/contexts/ModulesContext", () => ({
  useEnabledModulesOptional: () => ["printing"],
}));

const job = (status: string) => ({
  id: "job-1",
  agent_id: "a-1",
  status,
  count: 2,
  short_codes: ["PRN-0001", "PRN-0002"],
  attempts: 1,
  error: null,
  created_at: "2026-10-06T21:00:00Z",
  finished_at: status === "printed" ? "2026-10-06T21:00:05Z" : null,
});

/** The jobs beside a labels list, the way the label pool page holds them. */
function renderJobsBesideLabels() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const labelReads = vi.fn(() => Promise.resolve([]));
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  const rendered = renderHook(
    () => {
      useQuery({
        queryKey: [...queryKeys.labels.all, "pool"],
        queryFn: labelReads,
      });
      return usePrintJobs();
    },
    { wrapper },
  );
  return { ...rendered, labelReads };
}

describe("usePrintJobs", () => {
  let jobs: ReturnType<typeof job>[];

  beforeEach(() => {
    server.use(
      http.get("/api/v1/printing/jobs", () => HttpResponse.json(onePage(jobs))),
    );
  });

  it("reads the labels again when a job it saw in flight comes back printed", async () => {
    jobs = [job("printing")];
    const { result, labelReads } = renderJobsBesideLabels();
    await waitFor(() =>
      expect(result.current.data?.[0].status).toBe("printing"),
    );
    expect(labelReads).toHaveBeenCalledTimes(1);

    jobs = [job("printed")];
    await act(() => result.current.refetch());

    await waitFor(() => expect(labelReads).toHaveBeenCalledTimes(2));
  });

  it("leaves the labels alone for a job that was already printed", async () => {
    jobs = [job("printed")];
    const { result, labelReads } = renderJobsBesideLabels();
    await waitFor(() => expect(result.current.data).toBeDefined());

    await act(() => result.current.refetch());

    expect(labelReads).toHaveBeenCalledTimes(1);
  });
});
