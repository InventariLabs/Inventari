import React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useApproveDocument,
  useDocumentApprovalRequirement,
  useRejectDocument,
  useRequestDocumentApproval,
} from "./useDocumentApproval";

function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const invalidated: unknown[] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation(async (filters) => {
    invalidated.push(filters?.queryKey);
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { invalidated, wrapper };
}

function record(reply: JsonBodyType = { id: "ap-1" }) {
  const seen: string[] = [];
  server.use(
    http.all("*/api/v1/*", ({ request }) => {
      const url = new URL(request.url);
      seen.push(
        `${request.method} ${url.pathname.replace(/^.*\/api\/v1/, "")}${url.search}`,
      );
      return HttpResponse.json(reply);
    }),
  );
  return seen;
}

/**
 * An approval decision that did not drop the document's own entry left the
 * detail page offering the decision again; one that did not drop the
 * approvals namespace left the request in the approver's queue.
 */
describe("document approval decisions — the document and the queue both refresh", () => {
  it.each([
    ["request", useRequestDocumentApproval, "request-approval"],
    ["approve", useApproveDocument, "approve"],
    ["reject", useRejectDocument, "reject"],
  ] as const)(
    "%s goes through the document's route and refreshes its entry",
    async (_label, useHook, route) => {
      const seen = record();
      const { invalidated, wrapper } = setup();
      const { result } = renderHook(() => useHook(), { wrapper });

      await act(() =>
        result.current.mutateAsync({ docId: "doc-1", notes: "ok" }),
      );

      expect(seen).toEqual([
        `POST /approvals/documents/doc-1/${route}?notes=ok`,
      ]);
      expect(invalidated).toContainEqual(queryKeys.documents.detail("doc-1"));
      expect(invalidated).toContainEqual(queryKeys.documents.approval("doc-1"));
      expect(invalidated).toContainEqual(["approvals"]);
    },
  );
});

describe("useDocumentApprovalRequirement — asked only when it can matter", () => {
  it("stays quiet while approvals are off or no document is chosen", () => {
    const seen = record();
    const { wrapper } = setup();

    const off = renderHook(
      () => useDocumentApprovalRequirement("doc-1", { enabled: false }),
      { wrapper },
    );
    const none = renderHook(() => useDocumentApprovalRequirement(undefined), {
      wrapper,
    });

    expect(off.result.current.fetchStatus).toBe("idle");
    expect(none.result.current.fetchStatus).toBe("idle");
    expect(seen).toEqual([]);
  });

  it("reads whether confirming the document would queue it for approval", async () => {
    server.use(
      http.get("*/approvals/documents/:id/approval-requirement", () =>
        HttpResponse.json({ required: true }),
      ),
    );
    const { wrapper } = setup();
    const { result } = renderHook(
      () => useDocumentApprovalRequirement("doc-1"),
      { wrapper },
    );

    await waitFor(() =>
      expect(result.current.data).toEqual({ required: true }),
    );
  });
});
