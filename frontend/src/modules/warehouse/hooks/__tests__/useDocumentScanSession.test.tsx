import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { server } from "@/test/mocks/server";
import { QueryWrapper } from "@/test/queryWrapper";
import { useDocumentScanSession } from "../useDocumentScanSession";

beforeEach(() => {
  server.resetHandlers();
});

const openReceiving = {
  id: "session-1",
  document_id: "doc-1",
  assigned_to: "user-1",
  status: "active",
  started_at: "2026-10-11T08:00:00Z",
  completed_at: null,
  lines: [],
  total_lines: 2,
  received_lines: 0,
  pending_lines: 2,
};

describe("useDocumentScanSession", () => {
  it("hands back the session that is open, named for its direction", async () => {
    server.use(
      http.get("/api/v1/warehouse/documents/doc-1/receiving", () =>
        HttpResponse.json(onePage([openReceiving])),
      ),
      http.get("/api/v1/warehouse/documents/doc-1/picking", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    const { result } = renderHook(() => useDocumentScanSession("doc-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.data).toBeDefined());
    expect(result.current.data).toMatchObject({
      kind: "receiving",
      id: "session-1",
      status: "active",
      doneLines: 0,
      totalLines: 2,
    });
  });

  it("says nothing when the latest session was cancelled", async () => {
    server.use(
      http.get("/api/v1/warehouse/documents/doc-1/receiving", () =>
        HttpResponse.json(
          onePage([
            { ...openReceiving, status: "cancelled" },
            {
              ...openReceiving,
              id: "session-0",
              status: "completed",
              started_at: "2026-10-10T08:00:00Z",
            },
          ]),
        ),
      ),
      http.get("/api/v1/warehouse/documents/doc-1/picking", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    const { result } = renderHook(() => useDocumentScanSession("doc-1"), {
      wrapper: QueryWrapper,
    });

    await waitFor(() => expect(result.current.isFetched).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it.each([
    ["receiving", "completed"],
    ["picking", "short_pick"],
  ] as const)(
    "names a %s session that ended over the document as finished",
    async (kind, status) => {
      const finished = { ...openReceiving, status };
      server.use(
        http.get("/api/v1/warehouse/documents/doc-1/receiving", () =>
          HttpResponse.json(onePage(kind === "receiving" ? [finished] : [])),
        ),
        // The picking list filters on no direction: a receiving session is
        // in it too, and keeps its receiving name.
        http.get("/api/v1/warehouse/documents/doc-1/picking", () =>
          HttpResponse.json(onePage([finished])),
        ),
      );

      const { result } = renderHook(() => useDocumentScanSession("doc-1"), {
        wrapper: QueryWrapper,
      });

      await waitFor(() => expect(result.current.data).toBeDefined());
      expect(result.current.data).toMatchObject({
        kind,
        id: "session-1",
        status: "finished",
      });
    },
  );

  it("leaves out a finished session older than the confirmation", async () => {
    server.use(
      http.get("/api/v1/warehouse/documents/doc-1/receiving", () =>
        HttpResponse.json(onePage([{ ...openReceiving, status: "completed" }])),
      ),
      http.get("/api/v1/warehouse/documents/doc-1/picking", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    const { result } = renderHook(
      () =>
        useDocumentScanSession("doc-1", {
          confirmedAt: "2026-10-11T09:00:00Z",
        }),
      { wrapper: QueryWrapper },
    );

    await waitFor(() => expect(result.current.isFetched).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it("asks nothing of the API while the caller keeps it off", async () => {
    const { result } = renderHook(
      () => useDocumentScanSession("doc-1", { enabled: false }),
      { wrapper: QueryWrapper },
    );

    expect(result.current.fetchStatus).toBe("idle");
    expect(result.current.data).toBeUndefined();
  });
});
