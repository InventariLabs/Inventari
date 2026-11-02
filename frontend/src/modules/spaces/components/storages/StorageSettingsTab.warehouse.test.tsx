import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { onePage } from "@/test/mocks/page";
import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { makeStorageSummary } from "@/test/factories/storage";
// Registers the module, and with it the slot the strip comes through.
import "@/modules/warehouse/module";
import type { StorageLocation } from "@/types";
import { StorageSettingsTab } from "./StorageSettingsTab";

const storage = {
  ...makeStorageSummary({ id: "shelf-a", name: "Shelf A", full_path: "W / A" }),
  description: null,
  location_details: null,
  sequence: 15,
} as unknown as StorageLocation;

function serveWarehouse(enabledModules: string[]) {
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(enabledModules)),
    http.get("/api/v1/warehouse/putaway/capacity", () =>
      HttpResponse.json(onePage([])),
    ),
    http.get("/api/v1/warehouse/putaway/capacity-settings/:id", () =>
      HttpResponse.json({ location_id: "shelf-a", single_product: false }),
    ),
    http.get("/api/v1/warehouse/putaway/occupancy/:id", () =>
      HttpResponse.json({ locations: [], signals: [] }),
    ),
  );
}

beforeEach(() => {
  signInWith(["locations:read", "locations:write", "warehouse:read"]);
});

afterEach(() => {
  signOut();
});

function renderTab(canWrite: boolean) {
  render(
    <StorageSettingsTab
      storage={storage}
      summary={makeStorageSummary({ id: "shelf-a", name: "Shelf A" })}
      canWrite={canWrite}
      onDeleted={() => undefined}
    />,
  );
}

describe("a location's Settings tab and the warehouse module", () => {
  it.each([true, false])(
    "shows the warehouse strip when the module is on (editable: %s)",
    async (canWrite) => {
      serveWarehouse(["locations", "warehouse"]);
      renderTab(canWrite);
      expect(
        await screen.findByRole("button", { name: "Set up location" }),
      ).toBeInTheDocument();
      expect(screen.getByText(/walk order 15/)).toBeInTheDocument();
    },
  );

  it.each([true, false])(
    "shows neither the strip nor a walk order when the module is off (editable: %s)",
    async (canWrite) => {
      serveWarehouse(["locations"]);
      renderTab(canWrite);
      // The Basic section is up before the module list settles; wait on it.
      expect(await screen.findByText("Basic")).toBeInTheDocument();
      expect(
        screen.queryByRole("button", { name: "Set up location" }),
      ).not.toBeInTheDocument();
      expect(screen.queryByText(/walk order/i)).not.toBeInTheDocument();
      expect(screen.queryByLabelText(/walk order/i)).not.toBeInTheDocument();
    },
  );
});
