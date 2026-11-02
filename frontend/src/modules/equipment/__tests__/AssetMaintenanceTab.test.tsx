/**
 * Regression guard for.
 *
 * The backend serializes the maintenance `cost` column (Numeric(10,2)) as a
 * JSON string ("450.00") and stores `currency` only when the client sends it.
 * Both the maintenance tab and the asset timeline checked
 * `typeof log.cost === "number"`, so a cost of 450 rendered as nothing at
 * all, and the form field carried no currency marker. Now the cost renders
 * with the log currency or the organization currency as fallback, and the
 * form shows the currency suffix and sends it with the payload.
 */
import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor, fireEvent } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { MaintenanceTab } from "@/modules/equipment/components/AssetMaintenanceTab";
import { AssetTimeline } from "@/modules/equipment/components/AssetTimeline";
import { MaintenanceLogModal } from "@/modules/equipment/components/MaintenanceLogModal";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

const makeItem = (): Item => ({
  is_deleted: false,
  id: "item-1",
  location_id: "loc-1",
  category_id: null,
  name: "Asset 1",
  brand: null,
  description: null,
  weight: null,
  quantity: "1",
  added_date: "2026-01-01",
  expiry_date: null,
  freeze_date: null,
  shelf_location: null,
  image_url: null,
  metadata: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
});

const maintenanceLog = {
  id: "log-1",
  item_id: "item-1",
  item_name: "Asset 1",
  maintenance_type: "REPAIR",
  title: "Replaced screen",
  description: null,
  cost: "450.00",
  currency: null,
  performed_at: "2026-08-01",
  performed_by: "Anna",
  service_partner_id: null,
  next_maintenance_at: null,
  created_by: "u1",
  created_at: "2026-08-01T00:00:00Z",
};

function mockMaintenanceLogs() {
  server.use(
    http.get("/api/v1/equipment/maintenance/item/:itemId", () =>
      HttpResponse.json(onePage([maintenanceLog])),
    ),
    http.get("/api/v1/equipment/assignments/item/:itemId", () =>
      HttpResponse.json(onePage([])),
    ),
  );
}

describe("maintenance cost rendering", () => {
  it("shows a string cost with org-currency fallback in the tab", async () => {
    mockMaintenanceLogs();

    render(<MaintenanceTab item={makeItem()} onAdd={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Replaced screen")).toBeInTheDocument();
    });
    // The entry row and the header total both show the amount.
    expect(screen.getAllByText(/450\.00/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/PLN/).length).toBeGreaterThan(0);
  });

  it("shows a string cost in the asset timeline", async () => {
    // The timeline reads the server-assembled feed, so the string cost
    // arrives exactly as the endpoint ships it — a JSON string from the
    // Numeric(10,2) column.
    server.use(
      http.get("/api/v1/equipment/assets/:itemId/timeline", () =>
        HttpResponse.json({
          events: [
            {
              kind: "maintenance",
              date: "2026-08-01",
              maintenance_type: "REPAIR",
              title: "Replaced screen",
              cost: "450.00",
              currency: null,
            },
          ],
        }),
      ),
    );

    render(<AssetTimeline item={makeItem()} />);

    await waitFor(() => {
      expect(screen.getByText(/Replaced screen/)).toBeInTheDocument();
    });
    expect(screen.getByText(/450\.00/)).toBeInTheDocument();
  });

  it("shows the currency suffix on the cost field and sends currency", async () => {
    let posted: Record<string, unknown> | null = null;
    server.use(
      http.post("/api/v1/equipment/maintenance", async ({ request }) => {
        posted = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(maintenanceLog, { status: 201 });
      }),
    );

    render(
      <MaintenanceLogModal
        itemId="item-1"
        itemName="Asset 1"
        onClose={vi.fn()}
      />,
    );

    // Currency suffix rendered next to the cost input (MSW org uses PLN).
    await waitFor(() => {
      expect(screen.getByText("PLN")).toBeInTheDocument();
    });

    fireEvent.change(
      screen.getByPlaceholderText("e.g. Replaced thermal paste"),
      {
        target: { value: "Screen swap" },
      },
    );
    // The type no longer opens on a standing answer, so the form asks for
    // one before it will save.
    fireEvent.click(screen.getByRole("radio", { name: "Repair" }));
    fireEvent.click(screen.getByRole("button", { name: /save/i }));

    await waitFor(() => {
      expect(posted).not.toBeNull();
    });
    expect(posted).toMatchObject({ title: "Screen swap", currency: "PLN" });
  });
});

describe("maintenance total cost", () => {
  it("sums the logged costs in the tab header", async () => {
    server.use(
      http.get("/api/v1/equipment/maintenance/item/:itemId", () =>
        HttpResponse.json(
          onePage([
            maintenanceLog,
            {
              ...maintenanceLog,
              id: "log-2",
              title: "Battery",
              cost: "120.50",
            },
            { ...maintenanceLog, id: "log-3", title: "Cleaning", cost: null },
          ]),
        ),
      ),
      http.get("/api/v1/equipment/assignments/item/:itemId", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    render(<MaintenanceTab item={makeItem()} onAdd={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Battery")).toBeInTheDocument();
    });
    // 450.00 + 120.50, with the entry that has no cost skipped.
    const total = screen.getByTestId("maintenance-total-cost");
    expect(total).toHaveTextContent(/570\.50/);
    expect(total).toHaveTextContent(/PLN/);
  });

  it("hides Add Entry and the row delete from a reader", async () => {
    // Logging and removing maintenance are writes; an employee who opened
    // the asset from My Assets was offered both.
    mockMaintenanceLogs();

    render(
      <MaintenanceTab item={makeItem()} onAdd={vi.fn()} canWrite={false} />,
    );

    await waitFor(() => {
      expect(screen.getByText("Replaced screen")).toBeInTheDocument();
    });
    expect(
      screen.queryByRole("button", { name: "Add Entry" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete maintenance entry" }),
    ).not.toBeInTheDocument();
  });

  it("shows no total when nothing was logged with a cost", async () => {
    server.use(
      http.get("/api/v1/equipment/maintenance/item/:itemId", () =>
        HttpResponse.json(onePage([{ ...maintenanceLog, cost: null }])),
      ),
      http.get("/api/v1/equipment/assignments/item/:itemId", () =>
        HttpResponse.json(onePage([])),
      ),
    );

    render(<MaintenanceTab item={makeItem()} onAdd={vi.fn()} />);

    await waitFor(() => {
      expect(screen.getByText("Replaced screen")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("maintenance-total-cost")).toBeNull();
  });
});
