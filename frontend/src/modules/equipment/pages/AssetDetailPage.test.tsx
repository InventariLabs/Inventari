import React from "react";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";

import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { ModulesProvider } from "@/contexts/ModulesContext";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";
import { onePage } from "@/test/mocks/page";

import AssetDetailPage from "./AssetDetailPage";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), warning: vi.fn(), info: vi.fn() },
}));

const ITEM_ID = "5b0f4a9e-2c1d-4e8f-9a3b-7d6c5e4f3a21";

function assetWith(overrides: {
  status?: string;
  is_deleted?: boolean;
}): Record<string, unknown> {
  return {
    id: ITEM_ID,
    name: "HP EliteBook",
    brand: "HP",
    barcode: null,
    status: "ACTIVE",
    category_id: "cat-1",
    location_id: "loc-1",
    context_tag: "equipment",
    quantity: 1,
    is_deleted: overrides.is_deleted ?? false,
    added_date: "2024-01-01T00:00:00Z",
    created_at: "2024-01-01T00:00:00Z",
    updated_at: "2024-01-01T00:00:00Z",
    metadata: {
      equipment: {
        equipment_status: overrides.status ?? "AVAILABLE",
        serial_number: "SN-123",
      },
    },
  };
}

function serveAsset(
  overrides: Parameters<typeof assetWith>[0] = {},
  approval: Record<string, unknown> = { has_workflow: false, status: null },
) {
  server.use(
    http.get(`/api/v1/items/${ITEM_ID}`, () =>
      HttpResponse.json(assetWith(overrides)),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/approval-status`, () =>
      HttpResponse.json({ request_id: null, ...approval }),
    ),
  );
}

beforeEach(() => {
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "items:write",
    "locations:read",
    "categories:read",
  ]);
  server.use(
    http.get(`/api/v1/equipment/assignments/item/${ITEM_ID}`, () =>
      HttpResponse.json(onePage([])),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/valuation`, () =>
      HttpResponse.json({}),
    ),
    http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
      HttpResponse.json(onePage([])),
    ),
    http.get(`/api/v1/equipment/maintenance/item/${ITEM_ID}`, () =>
      HttpResponse.json({ items: [] }),
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

function renderDetail() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ModulesProvider>
        <MemoryRouter initialEntries={[`/equipment/${ITEM_ID}`]}>
          <PageHeaderHost>
            <Routes>
              <Route path="/equipment" element={<p>the asset list</p>} />
              <Route path="/equipment/:id" element={<AssetDetailPage />} />
            </Routes>
          </PageHeaderHost>
        </MemoryRouter>
      </ModulesProvider>
    </QueryClientProvider>,
  );
}

async function confirmIn(dialogButton: string) {
  const dialog = await screen.findByRole("alertdialog");
  await userEvent.click(
    within(dialog).getByRole("button", { name: dialogButton }),
  );
}

/**
 * The header's destructive actions each ask first and then do one request.
 * What breaks when they are wired wrong: an archive that leaves the reader
 * on the page of a record that is gone, a restore that keeps its dialog up
 * over a record already back, a purge sent to the wrong address.
 */
describe("AssetDetailPage — archive, restore and purge", () => {
  it("archives after the confirmation and returns to the list", async () => {
    const archived = vi.fn();
    serveAsset();
    server.use(
      http.post(`/api/v1/equipment/items/${ITEM_ID}/archive`, () => {
        archived();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Archive" }),
    );
    expect(screen.getByText("Archive this asset?")).toBeInTheDocument();
    await confirmIn("Archive");

    expect(await screen.findByText("the asset list")).toBeInTheDocument();
    expect(archived).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("Asset archived");
  });

  it("retires after the confirmation and stays on the asset", async () => {
    const retired = vi.fn();
    serveAsset();
    server.use(
      http.post(`/api/v1/equipment/items/${ITEM_ID}/retire`, () => {
        retired();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Retire" }),
    );
    await confirmIn("Retire");

    await waitFor(() => expect(retired).toHaveBeenCalledTimes(1));
    // Retiring is a status change, not a removal: the asset is still here,
    // and the page the reader is on is the one that shows it retired.
    expect(screen.queryByText("the asset list")).not.toBeInTheDocument();
    expect(toast.success).toHaveBeenCalledWith("Asset retired");
    // The dialog closes with the success: left open, its live Retire button
    // sent a second request the API refuses.
    await waitFor(() =>
      expect(
        screen.queryByRole("alertdialog", { name: /retire this asset/i }),
      ).not.toBeInTheDocument(),
    );
  });

  it("cancelling the archive sends nothing and stays on the asset", async () => {
    const archived = vi.fn();
    serveAsset();
    server.use(
      http.post(`/api/v1/equipment/items/${ITEM_ID}/archive`, () => {
        archived();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Archive" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Cancel" }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(archived).not.toHaveBeenCalled();
    expect(screen.queryByText("the asset list")).not.toBeInTheDocument();
  });

  it("restores an archived asset in place and closes the dialog", async () => {
    const restored = vi.fn();
    serveAsset({ is_deleted: true });
    server.use(
      http.post(`/api/v1/items/${ITEM_ID}/restore`, () => {
        restored();
        return HttpResponse.json(assetWith({}));
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Restore" }),
    );
    expect(
      screen.getByText(
        "The asset will be returned to your active assets list.",
      ),
    ).toBeInTheDocument();
    await confirmIn("Restore");

    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(restored).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("Asset restored");
    expect(screen.queryByText("the asset list")).not.toBeInTheDocument();
  });

  it("purges an archived asset for good and returns to the list", async () => {
    const purged = vi.fn();
    serveAsset({ is_deleted: true });
    server.use(
      http.delete(`/api/v1/items/${ITEM_ID}/purge`, () => {
        purged();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("button", { name: "Delete Permanently" }),
    );
    expect(
      screen.getByText("Permanently delete this asset?"),
    ).toBeInTheDocument();
    await confirmIn("Delete Permanently");

    expect(await screen.findByText("the asset list")).toBeInTheDocument();
    expect(purged).toHaveBeenCalledTimes(1);
    expect(toast.success).toHaveBeenCalledWith("Asset permanently deleted");
  });
});

describe("AssetDetailPage — changing the status", () => {
  async function pickStatus(label: string) {
    await userEvent.click(
      await screen.findByRole("button", { name: "Change status" }),
    );
    await userEvent.click(
      screen.getByRole("menuitemradio", { name: new RegExp(label) }),
    );
  }

  it("asks before bringing a retired asset back", async () => {
    serveAsset({ status: "RETIRED" });
    const update = vi.fn();
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", () => {
        update();
        return HttpResponse.json({ updated: 1, errors: [] });
      }),
    );
    renderDetail();
    expect(
      await screen.findByRole("button", {
        name: "This asset is already retired",
      }),
    ).toBeDisabled();
    await pickStatus("Available");
    expect(update).not.toHaveBeenCalled();
    expect(await screen.findByRole("alertdialog")).toBeInTheDocument();
    await confirmIn("Change status");
    await waitFor(() => expect(update).toHaveBeenCalledOnce());
  });

  it("passes on the server's reason when the row was refused", async () => {
    serveAsset();
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", () =>
        HttpResponse.json({
          updated: 0,
          errors: [{ item_id: ITEM_ID, error: "still checked out" }],
        }),
      ),
    );
    renderDetail();

    await pickStatus("Maintenance");
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("still checked out"),
    );
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("says the change failed when the request itself fails", async () => {
    serveAsset();
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    renderDetail();

    await pickStatus("Maintenance");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("ends a service from the maintenance tab by setting the asset available", async () => {
    let body: Record<string, unknown> = {};
    serveAsset({ status: "MAINTENANCE" });
    server.use(
      http.patch("/api/v1/equipment/assets/bulk", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ updated: 1, errors: [] });
      }),
    );
    renderDetail();

    await userEvent.click(
      await screen.findByRole("tab", { name: "Maintenance" }),
    );
    await userEvent.click(
      await screen.findByRole("button", { name: "End service" }),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Status changed to Available"),
    );
    expect(body).toEqual({
      item_ids: [ITEM_ID],
      action: "change_status",
      data: { status: "AVAILABLE" },
    });
  });
});

/**
 * A request names the checkout it asks for: the page's button opens the
 * checkout dialog, where the holder is typed and the request is sent.
 */
async function askForTheCheckoutOf(holder: string) {
  await userEvent.click(
    await screen.findByRole("button", { name: "Request Approval" }),
  );
  await userEvent.type(
    await screen.findByLabelText(/assigned to \(name\)/i),
    holder,
  );
  await userEvent.click(
    screen.getByRole("button", { name: "Send for approval" }),
  );
}

describe("AssetDetailPage — asking for approval", () => {
  it("names a waiting request the way the approvals queue does", async () => {
    // The asset page said "Pending" for the request the queue lists under
    // "Waiting for approval" — two names for one state.
    serveAsset({}, { has_workflow: true, status: "PENDING" });
    renderDetail();

    expect(
      await screen.findByRole("button", { name: "Waiting for approval" }),
    ).toBeInTheDocument();
  });

  it("confirms a request that went through", async () => {
    serveAsset({}, { has_workflow: true, status: null });
    server.use(
      http.post(`/api/v1/equipment/${ITEM_ID}/request-approval`, () =>
        HttpResponse.json({ request_id: "r-1", status: "PENDING" }),
      ),
    );
    renderDetail();

    await askForTheCheckoutOf("Kasia Kowalska");
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Approval requested"),
    );
  });

  it("says so when the request is refused", async () => {
    serveAsset({}, { has_workflow: true, status: null });
    server.use(
      http.post(`/api/v1/equipment/${ITEM_ID}/request-approval`, () =>
        HttpResponse.json(
          { detail: "An approval is already pending" },
          { status: 400 },
        ),
      ),
    );
    renderDetail();

    await askForTheCheckoutOf("Kasia Kowalska");
    // Read in the dialog the request was sent from, not in a toast outside it.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An approval is already pending",
    );
  });
});

/**
 * An archived card is where a restore decision is made: its history stays
 * readable, but the writes the API refuses for an archived record — a new
 * maintenance entry, a status change, a checkout, an upload — are not
 * offered. Offering them left the reader with a 404 after filling a form.
 * What the API still allows on an archived record (removing a paper or an
 * entry) stays.
 */
describe("AssetDetailPage — an archived card", () => {
  it("offers no new maintenance entry and no end of service", async () => {
    serveAsset({ is_deleted: true, status: "MAINTENANCE" });
    renderDetail();

    await userEvent.click(
      await screen.findByRole("tab", { name: "Maintenance" }),
    );
    expect(
      await screen.findByText("No maintenance records"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add Entry" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "End service" }),
    ).not.toBeInTheDocument();
  });

  it("offers no checkout", async () => {
    serveAsset({ is_deleted: true });
    renderDetail();

    await userEvent.click(
      await screen.findByRole("tab", { name: "Assignments" }),
    );
    expect(
      await screen.findByRole("tabpanel", { name: "Assignments" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Check Out" }),
    ).not.toBeInTheDocument();
  });

  it("keeps its papers removable but offers no upload", async () => {
    serveAsset({ is_deleted: true });
    server.use(
      http.get(`/api/v1/equipment/${ITEM_ID}/attachments`, () =>
        HttpResponse.json(
          onePage([
            {
              id: "att-1",
              item_id: ITEM_ID,
              original_name: "invoice.pdf",
              size_bytes: 1024,
              file_type: "INVOICE",
              content_type: "application/pdf",
              url: "/uploads/org/attachments/x/invoice.pdf",
              created_at: "2026-01-01T00:00:00Z",
            },
          ]),
        ),
      ),
    );
    renderDetail();

    expect(await screen.findByText("invoice.pdf")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Delete invoice.pdf" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Upload" }),
    ).not.toBeInTheDocument();
  });
});
