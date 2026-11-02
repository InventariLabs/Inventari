import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { signInWith, signOut } from "@/test/auth";
import { serveLocations } from "@/test/serveLocations";
import { makeStorageSummary } from "@/test/factories/storage";
import type { StorageLocation } from "@/types";
import { StorageSettingsTab } from "./StorageSettingsTab";

vi.mock("sonner", () => ({
  toast: {
    success: vi.fn(),
    error: vi.fn(),
    info: vi.fn(),
    warning: vi.fn(),
    loading: vi.fn(),
    dismiss: vi.fn(),
  },
}));

const download = vi.hoisted(() => vi.fn());
vi.mock("@/utils/helpers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/utils/helpers")>()),
  downloadBlob: download,
}));

const FLOOR = [
  { id: "home", name: "Home", parent_id: null },
  { id: "shelf", name: "Shelf A", parent_id: "home" },
  { id: "garage", name: "Garage", parent_id: null },
];

const makeStorage = (extra: Record<string, unknown> = {}): StorageLocation =>
  ({
    ...makeStorageSummary({
      id: "shelf",
      name: "Shelf A",
      parent_id: "home",
      short_code: "SH-A",
    }),
    description: null,
    location_details: null,
    ...extra,
  }) as unknown as StorageLocation;

function renderTab(
  storage: StorageLocation = makeStorage(),
  onDeleted: () => void = vi.fn(),
) {
  render(
    <StorageSettingsTab
      storage={storage}
      summary={makeStorageSummary({
        id: storage.id,
        name: storage.name,
        parent_id: storage.parent_id,
      })}
      canWrite
      onDeleted={onDeleted}
    />,
  );
  return onDeleted;
}

const openRecordMenu = async () =>
  userEvent.click(screen.getByRole("button", { name: "Actions for Shelf A" }));

describe("StorageSettingsTab — acting on the location", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["locations:read", "locations:write"]);
    serveLocations(FLOOR);
    server.use(
      http.get("/api/v1/location-types", () => HttpResponse.json(onePage([]))),
      http.get("/api/v1/modules/my", () => HttpResponse.json([])),
    );
    return () => signOut();
  });

  it("fills in the code the server generated for a location that has none", async () => {
    let asked = 0;
    server.use(
      http.post("/api/v1/locations/shelf/generate-code", () => {
        asked += 1;
        return HttpResponse.json({ ...makeStorage(), short_code: "SH-0042" });
      }),
    );
    renderTab(makeStorage({ short_code: null }));

    await userEvent.click(
      await screen.findByRole("button", { name: /Generate code/ }),
    );

    await waitFor(() =>
      expect(screen.getByPlaceholderText(/LOC-001/)).toHaveValue("SH-0042"),
    );
    expect(asked).toBe(1);
  });

  it("says the code could not be generated, and leaves the field empty", async () => {
    server.use(
      http.post("/api/v1/locations/shelf/generate-code", () =>
        HttpResponse.json({ detail: "Sequence exhausted" }, { status: 409 }),
      ),
    );
    renderTab(makeStorage({ short_code: null }));

    await userEvent.click(
      await screen.findByRole("button", { name: /Generate code/ }),
    );

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Sequence exhausted"),
    );
    expect(screen.getByPlaceholderText(/LOC-001/)).toHaveValue("");
  });

  it("downloads the QR label under the code, asking for the description the form shows", async () => {
    let query: URLSearchParams | undefined;
    server.use(
      http.get("/api/v1/locations/shelf/print", ({ request }) => {
        query = new URL(request.url).searchParams;
        return new HttpResponse(new Blob(["png"]), {
          headers: { "Content-Type": "image/png" },
        });
      }),
    );
    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Download" }),
    );

    await waitFor(() => expect(download).toHaveBeenCalledTimes(1));
    expect(download.mock.calls[0][1]).toBe("qr_SH-A.png");
    expect(query?.get("show_description")).toBe("true");
  });

  it("says the QR label could not be downloaded when the server refuses", async () => {
    server.use(
      http.get("/api/v1/locations/shelf/print", () =>
        HttpResponse.json({ detail: "Printer offline" }, { status: 503 }),
      ),
    );
    renderTab();

    await userEvent.click(
      await screen.findByRole("button", { name: "Download" }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(download).not.toHaveBeenCalled();
  });

  it("offers the location types again after they failed to load", async () => {
    let failing = true;
    server.use(
      http.get("/api/v1/location-types", () =>
        failing
          ? HttpResponse.json({ detail: "down" }, { status: 500 })
          : HttpResponse.json(
              onePage([
                {
                  id: "t-rack",
                  name: "Rack",
                  type_code: "RACK",
                  behavior_mode: "NONE",
                  is_system: false,
                  context_schema: [],
                },
              ]),
            ),
      ),
    );
    renderTab();

    const retry = await screen.findByRole("button", { name: "Try again" });
    failing = false;
    await userEvent.click(retry);

    expect(
      await screen.findByRole("option", { name: "Rack" }),
    ).toBeInTheDocument();
  });

  it("archives the location from its menu and tells the page it is gone", async () => {
    server.use(
      http.get("/api/v1/locations/:id/summary", ({ params }) =>
        HttpResponse.json({
          id: params.id,
          name: "Shelf A",
          items_count: 0,
          subtree_items_count: 0,
          children_count: 0,
        }),
      ),
      http.post("/api/v1/locations/shelf/archive", () =>
        HttpResponse.json(makeStorage()),
      ),
    );
    const onDeleted = renderTab();

    await openRecordMenu();
    await userEvent.click(
      await screen.findByRole("button", { name: "Archive" }),
    );
    const dialog = await screen.findByRole("alertdialog");
    await waitFor(() =>
      expect(
        within(dialog).getByRole("button", { name: "Archive" }),
      ).toBeEnabled(),
    );
    await userEvent.click(
      within(dialog).getByRole("button", { name: "Archive" }),
    );

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(toast.success).toHaveBeenCalledWith("Location archived");
  });

  it("deletes the location after the question and tells the page it is gone", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/locations/:id", ({ params }) => {
        deleted.push(String(params.id));
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onDeleted = renderTab();

    await openRecordMenu();
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    await waitFor(() => expect(onDeleted).toHaveBeenCalledTimes(1));
    expect(deleted).toEqual(["shelf"]);
    expect(toast.success).toHaveBeenCalledWith(
      "Location deleted successfully!",
    );
  });

  it("keeps the page where it is and gives the reason when the delete is refused", async () => {
    server.use(
      http.delete("/api/v1/locations/:id", () =>
        HttpResponse.json({ detail: "Still holds stock" }, { status: 409 }),
      ),
    );
    const onDeleted = renderTab();

    await openRecordMenu();
    await userEvent.click(
      await screen.findByRole("button", { name: "Delete" }),
    );
    await userEvent.click(
      within(await screen.findByRole("alertdialog")).getByRole("button", {
        name: "Delete",
      }),
    );

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onDeleted).not.toHaveBeenCalled();
    expect(toast.success).not.toHaveBeenCalled();
  });

  it("files the location under the chosen parent and sends it with Save, after the move is checked", async () => {
    const reorgs: Array<{ dry_run?: boolean }> = [];
    const updates: Array<Record<string, unknown>> = [];
    server.use(
      http.post("/api/v1/locations/reorg", async ({ request }) => {
        const body = (await request.json()) as { dry_run?: boolean };
        reorgs.push(body);
        return HttpResponse.json({
          applied: true,
          created: {},
          rejections: [],
          moves: [],
        });
      }),
      http.put("/api/v1/locations/:id", async ({ request }) => {
        updates.push((await request.json()) as Record<string, unknown>);
        return HttpResponse.json(makeStorage());
      }),
    );
    renderTab();

    await userEvent.click(await screen.findByLabelText("Lies in"));
    await userEvent.click(
      await screen.findByRole("button", { name: /Garage/ }),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(updates).toHaveLength(1));
    expect(updates[0]).toMatchObject({ parent_id: "garage" });
    expect(reorgs.length).toBeGreaterThan(0);
    expect(reorgs.every((body) => body.dry_run === true)).toBe(true);
  });

  it("names a taken short code in the user's language when Save is refused", async () => {
    server.use(
      http.put("/api/v1/locations/:id", () =>
        HttpResponse.json(
          { detail: "dup", code: "STORAGE_SHORT_CODE_CONFLICT" },
          { status: 409 },
        ),
      ),
    );
    renderTab();

    await userEvent.click(await screen.findByRole("button", { name: "Save" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledTimes(1));
    expect(toast.error).toHaveBeenCalledWith(expect.stringMatching(/code/i));
  });
});
