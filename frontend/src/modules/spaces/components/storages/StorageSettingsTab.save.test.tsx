import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { onePage } from "@/test/mocks/page";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation } from "@/types";
import { StorageSettingsTab } from "./StorageSettingsTab";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

const storage = {
  ...makeStorageSummary({
    id: "shelf-a",
    name: "Shelf A",
    parent_id: "rack-1",
  }),
  description: null,
  location_details: null,
  location_type_id: null,
  sequence: null,
} as unknown as StorageLocation;

const summary = makeStorageSummary({
  id: "shelf-a",
  name: "Shelf A",
  parent_id: "rack-1",
});

beforeEach(() => {
  server.use(
    http.get("/api/v1/modules/my", () => HttpResponse.json(["locations"])),
    http.get("/api/v1/location-types", () =>
      HttpResponse.json(
        onePage([{ id: "type-bin", name: "Bin", behavior_mode: "STOCK" }]),
      ),
    ),
    http.get("/api/v1/locations", () =>
      HttpResponse.json(
        onePage([makeStorageSummary({ id: "rack-1", name: "Rack 1" })]),
      ),
    ),
    http.get("/api/v1/locations/tree", () => HttpResponse.json([])),
  );
});

afterEach(() => {
  signOut();
});

function renderTab(canWrite = true, onDeleted = vi.fn()) {
  signInWith(
    canWrite ? ["locations:read", "locations:write"] : ["locations:read"],
  );
  render(
    <StorageSettingsTab
      storage={storage}
      summary={summary}
      canWrite={canWrite}
      onDeleted={onDeleted}
    />,
  );
  return onDeleted;
}

/**
 * One Save sends every field the tab edits. A field whose change handler
 * writes the wrong key, or a setting dropped from the payload, comes back
 * from the server as the old value — the reader's edit silently undone.
 */
describe("StorageSettingsTab — saving", () => {
  it("sends the edited fields and the label settings in one update", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.put("/api/v1/locations/shelf-a", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...storage, ...body });
      }),
    );
    const user = userEvent.setup();
    renderTab();

    await screen.findByRole("option", { name: "Bin" });
    await user.selectOptions(
      screen.getByLabelText("Location type"),
      "type-bin",
    );
    await user.type(screen.getByLabelText("Description"), "Cold side");
    await user.type(
      screen.getByLabelText("How to get there (optional)"),
      "By the door",
    );
    await user.click(screen.getByLabelText("Reserve location"));
    await user.type(screen.getByLabelText("QR Code"), "sa1");
    await user.click(screen.getByLabelText("Show description on label"));
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Location updated successfully!",
      ),
    );
    expect(body).toMatchObject({
      name: "Shelf A",
      location_type_id: "type-bin",
      description: "Cold side",
      location_details: "By the door",
      short_code: "SA1",
      settings: { is_reserve: true, label_show_description: false },
    });
  });
});

/**
 * Without write access the tab names where the location lies; a reader who
 * cannot move it is offered neither the picker nor a Save.
 */
describe("StorageSettingsTab — read only", () => {
  it("names the parent location instead of offering a picker", async () => {
    renderTab(false);

    expect(await screen.findByText("Rack 1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Save" }),
    ).not.toBeInTheDocument();
  });
});
