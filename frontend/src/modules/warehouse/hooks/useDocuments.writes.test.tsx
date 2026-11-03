import React from "react";
import { describe, expect, it, vi } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse, type JsonBodyType } from "msw";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { queryKeys } from "@/hooks/queries/keys";
import {
  useConfirmDocument,
  useCreateCorrection,
  useCreateDocument,
  useCreateReturn,
  useDocumentCorrections,
  useDocumentRegister,
  useDocumentRegisterRows,
  useDocumentWorkflow,
  useDuplicateDocument,
  useFetchDocument,
  useImportOpeningStock,
  usePostNewDocument,
} from "./useDocuments";

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({
    enabledModules: ["warehouse"],
    isModuleEnabled: (name: string) => name === "warehouse",
    isLoading: false,
    refreshModules: vi.fn(),
  }),
}));

/**
 * A client whose invalidations are recorded rather than refetched.
 *
 * `src/test/mocks/reactQuery.ts` forces `gcTime: 0` on every QueryClient, so a
 * query nobody observes is collected on the next timer tick — which the read
 * below only beats by luck. `setQueryDefaults` is per key and outranks the
 * global default, which keeps the document entries until the assertion.
 */
function setup() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  client.setQueryDefaults(queryKeys.documents.all, { gcTime: Infinity });
  const invalidated: unknown[] = [];
  vi.spyOn(client, "invalidateQueries").mockImplementation(async (filters) => {
    invalidated.push(filters?.queryKey);
  });
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, invalidated, wrapper };
}

/** Every request the hooks send, as "METHOD /path?query". */
function record(reply: JsonBodyType = { id: "doc-1" }) {
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
 * The writes that a document screen relies on to refresh itself. Each one
 * that forgot its invalidation left the list, the stock or the approvers'
 * notifications showing what was there before the write.
 */
describe("useDocuments writes — the right call, then the right caches dropped", () => {
  it("posts a new document under its key and refreshes the documents and the notifications", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => usePostNewDocument(), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        data: { type: "IN" } as never,
        key: "press-1",
        confirmSurplus: true,
      }),
    );

    expect(seen).toEqual([
      "POST /warehouse/documents/post?confirm_surplus=true",
    ]);
    expect(invalidated).toContainEqual(queryKeys.documents.all);
    expect(invalidated).toContainEqual(queryKeys.notifications.all);
  });

  it("posts a draft at once through the workflow and drops that document's own entry", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useDocumentWorkflow(), { wrapper });

    await act(() =>
      result.current.postDocumentNow.mutateAsync({ id: "doc-7" }),
    );

    expect(seen).toEqual(["POST /warehouse/documents/doc-7/post"]);
    expect(invalidated).toContainEqual(queryKeys.documents.detail("doc-7"));
    expect(invalidated).toContainEqual(queryKeys.notifications.all);
  });

  it("creates, confirms and duplicates a document, refreshing the confirmed one's own entry", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(
      () => ({
        create: useCreateDocument(),
        confirm: useConfirmDocument(),
        duplicate: useDuplicateDocument(),
      }),
      { wrapper },
    );

    await act(() =>
      result.current.create.mutateAsync({ type: "OUT" } as never),
    );
    await act(() => result.current.confirm.mutateAsync("doc-4"));
    await act(() => result.current.duplicate.mutateAsync("doc-4"));

    expect(seen).toEqual([
      "POST /warehouse/documents",
      "PATCH /warehouse/documents/doc-4/confirm",
      "POST /warehouse/documents/doc-4/duplicate",
    ]);
    expect(invalidated).toContainEqual(queryKeys.documents.detail("doc-4"));
    expect(invalidated).toContainEqual(queryKeys.documents.approval("doc-4"));
  });

  it("imports opening stock and refreshes the documents list", async () => {
    const seen = record({ document_id: "doc-9" });
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useImportOpeningStock(), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        file: new File(["a"], "a.csv"),
        mapping: {},
        targetLocationId: "loc-1",
      }),
    );

    expect(seen).toEqual(["POST /warehouse/import/opening-stock"]);
    expect(invalidated).toContainEqual(queryKeys.documents.all);
  });

  it("creates a correction and refreshes the documents even when it is refused", async () => {
    server.use(
      http.post("*/warehouse/corrections", () =>
        HttpResponse.json({ detail: "period closed" }, { status: 422 }),
      ),
    );
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useCreateCorrection(), { wrapper });

    await act(async () => {
      await result.current
        .mutateAsync({ document_id: "doc-1" } as never)
        .catch(() => undefined);
    });

    expect(result.current.isError).toBe(true);
    expect(invalidated).toContainEqual(queryKeys.documents.all);
  });

  it("creates a return against its document", async () => {
    const seen = record();
    const { invalidated, wrapper } = setup();
    const { result } = renderHook(() => useCreateReturn(), { wrapper });

    await act(() =>
      result.current.mutateAsync({
        documentId: "doc-3",
        data: { lines: [] } as never,
      }),
    );

    expect(seen).toEqual(["POST /warehouse/documents/doc-3/return"]);
    expect(invalidated).toContainEqual(queryKeys.documents.all);
  });
});

describe("useDocuments reads — asked only when they can be answered", () => {
  it("fetches a document on demand and stores it under its detail key", async () => {
    record({ id: "doc-5", number: "PZ/5" });
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useFetchDocument(), { wrapper });

    const doc = await act(() => result.current("doc-5"));

    expect(doc).toEqual({ id: "doc-5", number: "PZ/5" });
    expect(client.getQueryData(queryKeys.documents.detail("doc-5"))).toEqual(
      doc,
    );
  });

  it("asks the register summary only once both ends of the window are set", async () => {
    const seen = record({ groups: [] });
    const { wrapper } = setup();

    const open = renderHook(
      () => useDocumentRegister({ date_from: "2026-10-01" } as never),
      { wrapper },
    );
    expect(open.result.current.fetchStatus).toBe("idle");

    const { result } = renderHook(
      () =>
        useDocumentRegister({
          date_from: "2026-10-01",
          date_to: "2026-10-31",
        } as never),
      { wrapper },
    );
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toEqual([
      "GET /warehouse/register/summary?date_from=2026-10-01&date_to=2026-10-31",
    ]);
  });

  it("leaves a collapsed register group's rows unasked, and asks them once opened", async () => {
    const seen = record({ items: [] });
    const { wrapper } = setup();
    const params = {
      date_from: "2026-10-01",
      date_to: "2026-10-31",
      group: "IN",
    } as never;

    const collapsed = renderHook(() => useDocumentRegisterRows(params, false), {
      wrapper,
    });
    expect(collapsed.result.current.fetchStatus).toBe("idle");

    const { result } = renderHook(() => useDocumentRegisterRows(params), {
      wrapper,
    });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(seen).toHaveLength(1);
    expect(seen[0]).toMatch(/^GET \/warehouse\/register\/rows\?/);
  });

  it("lists a document's corrections, and none for a document not chosen yet", async () => {
    server.use(
      http.get("*/warehouse/documents/:id/corrections", () =>
        HttpResponse.json(onePage([{ id: "kor-1", number: "KOR/1" }])),
      ),
    );
    const { wrapper } = setup();

    const none = renderHook(() => useDocumentCorrections(""), { wrapper });
    expect(none.result.current.fetchStatus).toBe("idle");

    const { result } = renderHook(() => useDocumentCorrections("doc-1"), {
      wrapper,
    });
    await waitFor(() =>
      expect(result.current.data).toEqual([{ id: "kor-1", number: "KOR/1" }]),
    );
  });
});
