import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { queryKeys } from "@/hooks/queries/keys";
import { documentsApi } from "@/modules/warehouse/api/documents";
import { useUpdateDocument } from "@/modules/warehouse/hooks/useDocuments";

vi.mock("@/modules/warehouse/api/documents", () => ({
  documentsApi: { update: vi.fn() },
}));

function setup() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return { queryClient, ...renderHook(() => useUpdateDocument(), { wrapper }) };
}

describe("useUpdateDocument", () => {
  it("drops the cached approval requirement of the document it edited", async () => {
    // The confirm dialog builds its sentence from this read. Editing a draft
    // from 50 to 250 moved it across the approval threshold on the server,
    // while the dialog went on saying it would confirm directly until a reload.
    vi.mocked(documentsApi.update).mockResolvedValue({} as never);
    const { queryClient, result } = setup();
    const requirement = queryKeys.documents.approvalRequirement("doc-1");
    queryClient.setQueryData(requirement, { required: false });

    await act(async () => {
      await result.current.mutateAsync({ id: "doc-1", data: {} });
    });

    await waitFor(() =>
      expect(queryClient.getQueryState(requirement)?.isInvalidated).toBe(true),
    );
  });

  it("leaves another document's approval requirement alone", async () => {
    vi.mocked(documentsApi.update).mockResolvedValue({} as never);
    const { queryClient, result } = setup();
    const other = queryKeys.documents.approvalRequirement("doc-2");
    queryClient.setQueryData(other, { required: false });

    await act(async () => {
      await result.current.mutateAsync({ id: "doc-1", data: {} });
    });

    expect(queryClient.getQueryState(other)?.isInvalidated).toBe(false);
  });
});
