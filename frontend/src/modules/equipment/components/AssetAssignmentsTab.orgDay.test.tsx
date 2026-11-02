import { describe, expect, it, afterEach, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { AssignmentsTab } from "@/modules/equipment/components/AssetAssignmentsTab";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * The return day reproduction on the assignments tab.
 *
 * A checkout sent "2026-09-30" and the record came back as
 * ``2026-09-30T00:00:00Z``. A reader in Los Angeles, whose clock is seven
 * hours behind UTC, read the browser's day off that instant and saw
 * "09/29/2026" — the day before the one the form said. The stored value owes
 * the organization's clock, and the row must read it there.
 */

const assignment = {
  id: "assignment-1",
  item_id: "item-1",
  item_name: "ThinkPad T14",
  assigned_to_name: "Marta Zielinska",
  assigned_to_email: "marta@example.com",
  checked_out_at: "2026-09-01T09:00:00Z",
  expected_return_at: "2026-09-30T00:00:00Z",
  checked_in_at: null,
};

const item = {
  id: "item-1",
  name: "ThinkPad T14",
  serial_number: "SN-9",
  metadata: { equipment: { equipment_status: "DEPLOYED" } },
} as unknown as Item;

function inZone(zone: string, body: () => Promise<void> | void): Promise<void> {
  const original = process.env.TZ;
  process.env.TZ = zone;
  return Promise.resolve()
    .then(body)
    .finally(() => {
      process.env.TZ = original;
    });
}

afterEach(() => {
  process.env.TZ = undefined;
});

describe("AssignmentsTab — the return day reads the organization's clock", () => {
  it("a Los Angeles reader sees the day the form picked, not the one before", async () => {
    await inZone("America/Los_Angeles", async () => {
      server.use(
        http.get("/api/v1/equipment/assignments/item/item-1", () =>
          HttpResponse.json(onePage([assignment])),
        ),
        http.get("/api/v1/organizations/my", () =>
          HttpResponse.json({ timezone: "UTC" }),
        ),
      );

      render(
        <AssignmentsTab item={item} onCheckout={vi.fn()} onCheckin={vi.fn()} />,
      );

      await screen.findByText("Marta Zielinska");
      expect(
        screen.getByText(/Expected return: Sep 30, 2026/),
      ).toBeInTheDocument();
      expect(screen.queryByText(/Sep 29, 2026/)).not.toBeInTheDocument();
    });
  });

  it("hides check-in from a reader, and keeps the protocol", async () => {
    // Check-in is `equipment:write` on the API; a holder who only reads the
    // asset must not be offered it.
    server.use(
      http.get("/api/v1/equipment/assignments/item/item-1", () =>
        HttpResponse.json(onePage([assignment])),
      ),
      http.get("/api/v1/organizations/my", () =>
        HttpResponse.json({ timezone: "UTC" }),
      ),
    );

    render(
      <AssignmentsTab
        item={item}
        canWrite={false}
        onCheckout={vi.fn()}
        onCheckin={vi.fn()}
      />,
    );

    await screen.findByText("Marta Zielinska");
    expect(
      screen.queryByRole("button", { name: /check in/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /protocol/i }),
    ).toBeInTheDocument();
  });
});
