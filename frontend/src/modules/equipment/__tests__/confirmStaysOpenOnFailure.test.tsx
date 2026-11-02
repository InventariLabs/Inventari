import React from "react";
import {
  render,
  screen,
  waitFor,
  within,
  renderHook,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

import AssetDetailPage from "@/modules/equipment/pages/AssetDetailPage";
import { useAssetListActions } from "@/modules/equipment/hooks/useAssetListActions";
import { ReadableError } from "@/lib/errors";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

/**
 * A confirm dialog that closes on failure looks exactly like one that
 * succeeded. The status is unchanged, the record is where it was, and the
 * only trace is a toast already on its way out — so whoever looked away
 * cannot tell whether the asset was retired, and finds out from the list.
 *
 * The dialog has been able to wait since it learned to take a promise; these
 * handlers were still calling `mutate` and returning nothing. Two of the
 * cases here are not refused requests at all: a bulk endpoint answers `200`
 * having purged nothing, and retiring a selection of checked-out assets is
 * turned down before a request is sent. Both used to close the dialog over a
 * toast, and both now keep it open with the reason inside.
 */
const ITEM_ID = "ec6be09a-90ba-449d-a45b-6217ef627d37";

beforeEach(() => {
  vi.clearAllMocks();
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "items:write",
    "locations:read",
    "categories:read",
  ]);
  server.resetHandlers();
  server.use(
    http.get(`/api/v1/items/${ITEM_ID}`, () =>
      HttpResponse.json({
        id: ITEM_ID,
        name: "HP EliteBook",
        brand: "HP",
        barcode: null,
        status: "ACTIVE",
        category_id: "cat-1",
        location_id: "loc-1",
        context_tag: "equipment",
        quantity: 1,
        added_date: "2024-01-01T00:00:00Z",
        created_at: "2024-01-01T00:00:00Z",
        updated_at: "2024-01-01T00:00:00Z",
        metadata: {
          equipment: {
            equipment_status: "AVAILABLE",
            serial_number: "SN-123",
          },
        },
      }),
    ),
    http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
      HttpResponse.json(onePage([])),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
      HttpResponse.json({
        has_workflow: false,
        request_id: null,
        status: null,
      }),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
      HttpResponse.json({}),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/equipment/assets", () =>
      HttpResponse.json({ items: [], total: 0, has_more: false }),
    ),
    http.get("/api/v1/items/archived", () =>
      HttpResponse.json({ items: [], total: 0 }),
    ),
  );
});

afterEach(() => {
  signOut();
});

/** Mirrors ModuleShell: the header actions have to be in the DOM to be clicked. */
function PageHeaderHost({ children }: { children: React.ReactNode }) {
  const [data, setData] = React.useState<PageHeaderData>({});
  return (
    <PageHeaderContext.Provider value={{ data, setHeader: setData }}>
      {data.actions ? <div>{data.actions}</div> : null}
      {children}
    </PageHeaderContext.Provider>
  );
}

function makeClient() {
  return new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
}

function renderDetail() {
  const wrapper = ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={makeClient()}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment/:id" element={children} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>
  );
  return render(<AssetDetailPage />, { wrapper });
}

const listWrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={makeClient()}>
    <ModulesProvider>
      <MemoryRouter>{children}</MemoryRouter>
    </ModulesProvider>
  </QueryClientProvider>
);

describe("a confirm dialog waits for the answer", () => {
  it("keeps the retire confirmation open when the request fails", async () => {
    const user = userEvent.setup();
    server.use(
      http.post(`/api/v1/equipment/items/${ITEM_ID}/retire`, () =>
        HttpResponse.json({ detail: "Internal Server Error" }, { status: 500 }),
      ),
    );

    renderDetail();
    await screen.findByText("Serial Number", {}, { timeout: 5000 });

    await user.click(await screen.findByRole("button", { name: "Retire" }));
    const dialog = await screen.findByRole("alertdialog");
    // Two buttons are called Retire once the dialog is up: the header icon
    // that opened it, and the one inside that answers it.
    await user.click(within(dialog).getByRole("button", { name: "Retire" }));

    // The dialog is still here, and it says why rather than leaving a toast
    // to carry the news away.
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(dialog).toBeInTheDocument();
    expect(screen.getByText("Retire this asset?")).toBeInTheDocument();
  });

  it("refuses to retire a selection that is checked out, in the dialog", async () => {
    const { result } = renderHook(() => useAssetListActions(), {
      wrapper: listWrapper,
    });

    await expect(result.current.handleBulkRetire()).rejects.toBeInstanceOf(
      ReadableError,
    );
  });

  it("reports a purge that the server accepted and did not perform", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", () =>
        HttpResponse.json({
          purged: 0,
          errors: [
            {
              item_id: "i-1",
              error: "blocked by documents",
              code: "PURGE_BLOCKED_DOCUMENTS",
              blocks: [{ kind: "documents", count: 2 }],
            },
          ],
        }),
      ),
    );

    const { result } = renderHook(() => useAssetListActions(), {
      wrapper: listWrapper,
    });

    await expect(result.current.handleSinglePurge("i-1")).rejects.toThrow(
      /document/i,
    );
  });

  it("closes over a purge that did happen", async () => {
    server.use(
      http.post("/api/v1/equipment/items/bulk-purge", () =>
        HttpResponse.json({ purged: 1, errors: [] }),
      ),
    );

    const { result } = renderHook(() => useAssetListActions(), {
      wrapper: listWrapper,
    });

    await waitFor(async () => {
      await expect(result.current.handleSinglePurge("i-1")).resolves.toBe(
        undefined,
      );
    });
  });
});
