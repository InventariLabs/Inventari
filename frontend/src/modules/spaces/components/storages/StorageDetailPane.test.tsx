import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation } from "@/types";
import { StorageDetailPane } from "./StorageDetailPane";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() },
}));

vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: vi.fn(),
}));

const node = makeStorageSummary({
  id: "shelf-a",
  name: "Shelf A",
  parent_id: "rack-1",
  short_code: "SH-A",
});
const storage = {
  ...node,
  description: null,
  location_details: null,
} as unknown as StorageLocation;
const path = [
  { id: "rack-1", name: "Rack 1" },
  { id: "shelf-a", name: "Shelf A" },
] as never;

beforeEach(() => {
  signInWith(["locations:read", "locations:write", "items:read"]);
  server.use(
    http.get("/api/v1/locations", () =>
      HttpResponse.json({ items: [], total: 0, limit: 50, offset: 0 }),
    ),
    http.get("/api/v1/print/agents", () => HttpResponse.json([])),
  );
});

afterEach(() => {
  signOut();
});

function renderPane() {
  const props = {
    node,
    storage,
    path,
    excludeModuleContexts: false,
    canWriteStorage: true,
    canWriteItems: true,
    onSelect: vi.fn(),
    onMove: vi.fn(),
    onAddInside: vi.fn(),
    onDeleted: vi.fn(),
  };
  render(<StorageDetailPane {...props} />);
  return props;
}

/**
 * The inline rename is the one write the pane makes itself. A rename that
 * sends an unchanged name, keeps the field open after a refusal with the
 * refused name in it, or ignores Escape fails one of these.
 */
describe("StorageDetailPane — renaming in place", () => {
  it("saves a new name on Enter and closes the field", async () => {
    let body: Record<string, unknown> = {};
    server.use(
      http.put("/api/v1/locations/shelf-a", async ({ request }) => {
        body = (await request.json()) as typeof body;
        return HttpResponse.json({ ...storage, ...body });
      }),
    );
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Rename" }));
    const field = screen.getByRole("textbox", { name: "Location name" });
    expect(field).toHaveFocus();
    await user.clear(field);
    await user.type(field, "Shelf A1{Enter}");

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Location updated successfully!",
      ),
    );
    expect(body).toEqual({ name: "Shelf A1" });
    expect(
      screen.queryByRole("textbox", { name: "Location name" }),
    ).not.toBeInTheDocument();
  });

  it("sends nothing for an unchanged name", async () => {
    const saved = vi.fn();
    server.use(
      http.put("/api/v1/locations/shelf-a", () => {
        saved();
        return HttpResponse.json(storage);
      }),
    );
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.click(screen.getByRole("button", { name: "Save name" }));
    expect(
      screen.queryByRole("textbox", { name: "Location name" }),
    ).not.toBeInTheDocument();
    expect(saved).not.toHaveBeenCalled();
  });

  it("puts the old name back and says why when the rename is refused", async () => {
    server.use(
      http.put("/api/v1/locations/shelf-a", () =>
        HttpResponse.json(
          { detail: "Name already used here" },
          { status: 400 },
        ),
      ),
    );
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Rename" }));
    const field = screen.getByRole("textbox", { name: "Location name" });
    await user.clear(field);
    await user.type(field, "Rack 1{Enter}");

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Name already used here"),
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByRole("textbox", { name: "Location name" })).toHaveValue(
      "Shelf A",
    );
  });

  it("drops the typed name on Escape and on Cancel", async () => {
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Rename" }));
    await user.type(
      screen.getByRole("textbox", { name: "Location name" }),
      " draft{Escape}",
    );
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByRole("textbox", { name: "Location name" })).toHaveValue(
      "Shelf A",
    );

    await user.type(
      screen.getByRole("textbox", { name: "Location name" }),
      " draft",
    );
    await user.click(screen.getByRole("button", { name: "Cancel rename" }));
    await user.click(screen.getByRole("button", { name: "Rename" }));
    expect(screen.getByRole("textbox", { name: "Location name" })).toHaveValue(
      "Shelf A",
    );
  });
});

describe("StorageDetailPane — the header's actions", () => {
  it("downloads the location's label under its code", async () => {
    server.use(
      http.get(
        "/api/v1/locations/shelf-a/print",
        () =>
          new HttpResponse(new Blob(["png"]), {
            headers: { "Content-Type": "image/png" },
          }),
      ),
    );
    const { downloadBlob } = await import("@/utils/helpers");
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Print Preview" }));
    await waitFor(() =>
      expect(downloadBlob).toHaveBeenCalledWith(
        expect.anything(),
        "storage_SH-A.png",
      ),
    );
  });

  it("says when the label could not be downloaded", async () => {
    server.use(
      http.get("/api/v1/locations/shelf-a/print", () =>
        HttpResponse.json({}, { status: 500 }),
      ),
    );
    const user = userEvent.setup();
    renderPane();

    await user.click(screen.getByRole("button", { name: "Print Preview" }));
    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Error downloading labels"),
    );
  });

  it("moves this location, and leads back up to its parent", async () => {
    const user = userEvent.setup();
    const props = renderPane();

    await user.click(screen.getByRole("button", { name: "Move to…" }));
    expect(props.onMove).toHaveBeenCalledWith(["shelf-a"]);

    // The phone's back button and the path's crumb both name the parent.
    const [back, crumb] = screen.getAllByRole("button", { name: "Rack 1" });
    await user.click(back);
    await user.click(crumb);
    expect(props.onSelect).toHaveBeenNthCalledWith(1, "rack-1");
    expect(props.onSelect).toHaveBeenNthCalledWith(2, "rack-1");
  });
});
