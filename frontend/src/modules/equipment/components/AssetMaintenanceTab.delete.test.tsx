import { describe, expect, it, vi, beforeEach } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { render, screen, waitFor, within } from "@/test/utils";
import type { Item } from "@/types";

import { MaintenanceTab } from "./AssetMaintenanceTab";

vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "USD",
}));

const LOG = {
  id: "log-1",
  item_id: "asset-1",
  maintenance_type: "REPAIR",
  title: "Replaced fan",
  description: null,
  cost: null,
  currency: null,
  performed_at: "2026-09-01",
  performed_by: null,
  next_maintenance_at: null,
  created_at: "2026-09-01T00:00:00Z",
};

const item = {
  id: "asset-1",
  name: "ThinkPad T14s",
  quantity: 1,
  metadata: { equipment: { equipment_status: "AVAILABLE" } },
} as unknown as Item;

let reads: number;

beforeEach(() => {
  reads = 0;
  server.use(
    http.get("/api/v1/equipment/maintenance/item/asset-1", () => {
      reads++;
      return HttpResponse.json({ items: [LOG] });
    }),
  );
});

function renderTab(onAdd = vi.fn()) {
  render(<MaintenanceTab item={item} onAdd={onAdd} onEndService={vi.fn()} />);
  return { onAdd, user: userEvent.setup() };
}

/**
 * A service entry is removed for good, so the trash icon asks first. The
 * failures caught: a delete sent on the click, or despite Cancel, a list
 * that keeps the deleted row, and an Add button that opens nothing.
 */
describe("MaintenanceTab — the service entries", () => {
  it("deletes an entry only once the confirmation is accepted", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/equipment/maintenance/log-1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const { user } = renderTab();
    await screen.findByText("Replaced fan");

    await user.click(
      screen.getByRole("button", { name: "Delete maintenance entry" }),
    );
    let dialog = await screen.findByRole("alertdialog");
    expect(
      within(dialog).getByText('This permanently removes "Replaced fan".'),
    ).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await waitFor(() =>
      expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument(),
    );
    expect(deleted).not.toHaveBeenCalled();

    await user.click(
      screen.getByRole("button", { name: "Delete maintenance entry" }),
    );
    dialog = await screen.findByRole("alertdialog");
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toHaveBeenCalledTimes(1));
    // The list is asked again, so the deleted row leaves the screen.
    await waitFor(() => expect(reads).toBeGreaterThan(1));
  });

  it("asks the page for the new-entry form", async () => {
    const { onAdd, user } = renderTab();
    await screen.findByText("Replaced fan");
    await user.click(screen.getByRole("button", { name: "Add Entry" }));
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it("asks for the entries again after they failed to load", async () => {
    server.use(
      http.get("/api/v1/equipment/maintenance/item/asset-1", () => {
        reads++;
        return HttpResponse.json({}, { status: 500 });
      }),
    );
    const { user } = renderTab();
    const retry = await screen.findByRole("button", { name: /try again/i });
    const before = reads;
    await user.click(retry);
    await waitFor(() => expect(reads).toBeGreaterThan(before));
  });
});
