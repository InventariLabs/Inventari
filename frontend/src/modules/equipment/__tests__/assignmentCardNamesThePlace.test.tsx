import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import { AssignmentsTab } from "@/modules/equipment/components/AssetAssignmentsTab";
import type { Item } from "@/types";
import { onePage } from "@/test/mocks/page";

/**
 * A check-out that names a person and a place at once (the demo data has four
 * of them) used to print the bare word "Location" under the person, with the
 * place itself nowhere, and hid the person's e-mail because a place was set.
 */

const item = {
  id: "item-1",
  name: "Dell Latitude 5540",
  metadata: { equipment: { equipment_status: "DEPLOYED" } },
} as unknown as Item;

const base = {
  id: "assignment-1",
  item_id: "item-1",
  item_name: "Dell Latitude 5540",
  checked_out_at: "2026-09-01T09:00:00Z",
  checked_in_at: null,
};

function serve(assignment: object) {
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
}

describe("AssignmentsTab — a person's check-out that also names a place", () => {
  it("prints the place beside the label and keeps the person's e-mail", async () => {
    serve({
      ...base,
      holder_name: "Ava Brennan",
      assigned_to_name: "Ava Brennan",
      assigned_to_email: "ava@example.com",
      checkout_location_id: "loc-1",
      checkout_location_name: "Front desk",
    });

    await screen.findByText("Ava Brennan");
    expect(screen.getByText("ava@example.com")).toBeInTheDocument();
    expect(screen.getByText("Location: Front desk")).toBeInTheDocument();
  });

  it("does not repeat the place under itself when the place is the holder", async () => {
    serve({
      ...base,
      holder_name: null,
      assigned_to_name: null,
      checkout_location_id: "loc-1",
      checkout_location_name: "Front desk",
    });

    await screen.findByText("Front desk");
    expect(screen.queryByText(/^Location/)).not.toBeInTheDocument();
  });
});
