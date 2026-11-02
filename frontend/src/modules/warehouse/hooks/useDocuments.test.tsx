import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useDocuments,
  useDocument,
  useCreateDocument,
  useUpdateDocument,
  useConfirmDocument,
  useCompleteDocument,
  useCancelDocument,
  useDeleteDocument,
  useDocumentWorkflow,
} from "./useDocuments";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";
import { ModulesProvider } from "@/contexts/ModulesContext";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false, gcTime: 0 },
    },
  });
  return ({ children }: { children: React.ReactNode }) =>
    React.createElement(
      QueryClientProvider,
      { client: queryClient },
      React.createElement(ModulesProvider, null, children),
    );
};

describe("useDocuments hooks — shape", () => {
  it("useDocuments returns query result shape", () => {
    const { result } = renderHook(() => useDocuments(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("data");
    expect(result.current).toHaveProperty("isLoading");
    expect(result.current).toHaveProperty("isSuccess");
    expect(result.current).toHaveProperty("isError");
  });

  it("useDocument returns query result shape", () => {
    const { result } = renderHook(() => useDocument("doc-1"), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("data");
    expect(result.current).toHaveProperty("isLoading");
  });

  it("useDocument disabled when no id", () => {
    const { result } = renderHook(() => useDocument(undefined), {
      wrapper: createWrapper(),
    });
    expect(result.current.fetchStatus).toBe("idle");
  });

  it("useCreateDocument returns mutation shape", () => {
    const { result } = renderHook(() => useCreateDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });

  it("useUpdateDocument returns mutation shape", () => {
    const { result } = renderHook(() => useUpdateDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });

  it("useConfirmDocument returns mutation shape", () => {
    const { result } = renderHook(() => useConfirmDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });

  it("useCompleteDocument returns mutation shape", () => {
    const { result } = renderHook(() => useCompleteDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });

  it("useCancelDocument returns mutation shape", () => {
    const { result } = renderHook(() => useCancelDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });

  it("useDeleteDocument returns mutation shape", () => {
    const { result } = renderHook(() => useDeleteDocument(), {
      wrapper: createWrapper(),
    });
    expect(result.current).toHaveProperty("mutate");
    expect(result.current).toHaveProperty("isPending");
  });
});

describe("useDocumentWorkflow", () => {
  it("returns all workflow hooks", () => {
    const { result } = renderHook(() => useDocumentWorkflow(), {
      wrapper: createWrapper(),
    });
    expect(result.current.createDocument).toBeDefined();
    expect(result.current.updateDocument).toBeDefined();
    expect(result.current.confirmDocument).toBeDefined();
    expect(result.current.completeDocument).toBeDefined();
    expect(result.current.postDocumentNow).toBeDefined();
    expect(result.current.cancelDocument).toBeDefined();
    expect(result.current.deleteDocument).toBeDefined();
  });

  it("tracks isSavingDraft state", () => {
    const { result } = renderHook(() => useDocumentWorkflow(), {
      wrapper: createWrapper(),
    });
    expect(result.current.isSavingDraft).toBe(false);
  });

  it("tracks isTransitionPending state", () => {
    const { result } = renderHook(() => useDocumentWorkflow(), {
      wrapper: createWrapper(),
    });
    expect(result.current.isTransitionPending).toBe(false);
  });
});

describe("settling the approval request together with the document", () => {
  // Cancelling or deleting a document withdraws its open approval request on
  // the server, which marks the "waiting for your decision" notice read; the
  // bell has to hear about it without waiting for the next poll.
  it.each([
    [
      "cancel",
      "patch",
      "/api/v1/warehouse/documents/doc-1/cancel",
      useCancelDocument,
    ],
    [
      "delete",
      "delete",
      "/api/v1/warehouse/documents/doc-1",
      useDeleteDocument,
    ],
  ] as const)(
    "refreshes the notification bell after a %s",
    async (_name, method, path, useHook) => {
      const queryClient = new QueryClient({
        defaultOptions: { mutations: { retry: false } },
      });
      const spy = vi.spyOn(queryClient, "invalidateQueries");
      server.use(http[method](path, () => HttpResponse.json({})));
      const { result } = renderHook(() => useHook(), {
        wrapper: ({ children }: { children: React.ReactNode }) =>
          React.createElement(
            QueryClientProvider,
            { client: queryClient },
            React.createElement(ModulesProvider, null, children),
          ),
      });

      act(() => result.current.mutate("doc-1"));

      await waitFor(() =>
        expect(spy).toHaveBeenCalledWith({
          queryKey: queryKeys.notifications.all,
        }),
      );
    },
  );
});
