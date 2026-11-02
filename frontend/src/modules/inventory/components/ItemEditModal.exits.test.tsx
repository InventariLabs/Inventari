import { render, screen, fireEvent, waitFor, within, act } from "@/test/utils";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { toast } from "sonner";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import ItemEditModal from "./ItemEditModal";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), dismiss: vi.fn() },
}));

// jsdom has no canvas, so the real compressor never settles.
vi.mock("@/lib/imageUtils", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/imageUtils")>();
  return {
    ...actual,
    compressImage: (file: File) => Promise.resolve(file),
    prepareImageUpload: (file: File) => Promise.resolve(file),
  };
});

const record = {
  id: "1",
  name: "Test Item",
  quantity: 10,
  category_id: "1",
  location_id: "1",
  brand: "Test Brand",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

/**
 * The edit form's other ways out and side doors: Escape closes an untouched
 * form and asks about a touched one, "keep editing" really keeps the edit, a
 * refused save says why and stays open, the delete-reason dialog can be
 * backed out of, a chosen photo is uploaded at once (and a refused upload
 * says so), and a product that cannot be read settles the valuation section
 * instead of leaving it loading.
 */
describe("ItemEditModal — leaving, refusals and the photo", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    signInWith(["items:read", "items:write", "items:delete"]);
  });

  afterEach(() => signOut());

  it("closes an untouched form on Escape", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);
    await screen.findByDisplayValue("Test Item");

    fireEvent.keyDown(window, { key: "Escape" });

    expect(onClose).toHaveBeenCalled();
  });

  it("keeps a touched form open when the reader chooses to keep editing", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);
    const brand = await screen.findByDisplayValue("Test Brand");
    fireEvent.change(brand, { target: { value: "Typed" } });

    fireEvent.keyDown(window, { key: "Escape" });
    const dialog = await screen.findByRole("alertdialog");
    expect(dialog).toHaveTextContent("Leave without saving?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("alertdialog")).toBeNull());
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.getByDisplayValue("Typed")).toBeInTheDocument();
  });

  it("says why a save was refused and stays open", async () => {
    server.use(
      http.put("/api/v1/items/1", () =>
        HttpResponse.json({ detail: "Name already taken" }, { status: 400 }),
      ),
    );
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);
    const name = await screen.findByDisplayValue("Test Item");
    fireEvent.change(name, { target: { value: "Renamed" } });

    fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

    expect(await screen.findByText("Name already taken")).toBeInTheDocument();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("backs out of the delete-reason dialog without deleting", async () => {
    const deleted = vi.fn();
    server.use(
      http.delete("/api/v1/items/1", () => {
        deleted();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /delete product/i }),
    );
    await screen.findByTestId("deletion-reason");
    const dialog = screen
      .getByTestId("deletion-reason")
      .closest("[role='alertdialog'], [role='dialog']") as HTMLElement;
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByTestId("deletion-reason")).toBeNull(),
    );
    expect(deleted).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
  });

  it("uploads a chosen photo at once and shows the stored one", async () => {
    const uploads = vi.fn();
    server.use(
      http.post("/api/v1/items/1/image", () => {
        uploads();
        return HttpResponse.json({ image_url: "/uploads/stored.jpg" });
      }),
    );
    const { container } = render(
      <ItemEditModal itemId="1" onClose={vi.fn()} />,
    );
    await screen.findByDisplayValue("Test Item");

    const input = container.querySelector(
      'input[type="file"][accept="image/*"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "p.jpg", { type: "image/jpeg" })] },
    });

    await waitFor(() => expect(uploads).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
        "src",
        "/uploads/stored.jpg",
      ),
    );
  });

  it("keeps the stored photo when the local preview finishes reading after the upload", async () => {
    const readers: Array<() => void> = [];
    class SlowReader {
      result: string | null = null;
      onloadend: (() => void) | null = null;
      readAsDataURL() {
        readers.push(() => {
          this.result = "data:image/jpeg;base64,eA==";
          this.onloadend?.();
        });
      }
    }
    vi.stubGlobal("FileReader", SlowReader);
    try {
      const uploads = vi.fn();
      server.use(
        http.post("/api/v1/items/1/image", () => {
          uploads();
          return HttpResponse.json({ image_url: "/uploads/stored.jpg" });
        }),
      );
      const { container } = render(
        <ItemEditModal itemId="1" onClose={vi.fn()} />,
      );
      await screen.findByDisplayValue("Test Item");

      const input = container.querySelector(
        'input[type="file"][accept="image/*"]',
      ) as HTMLInputElement;
      fireEvent.change(input, {
        target: { files: [new File(["x"], "p.jpg", { type: "image/jpeg" })] },
      });
      await waitFor(() =>
        expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
          "src",
          "/uploads/stored.jpg",
        ),
      );

      // The reader reports in only now, after the stored photo is shown.
      readers.forEach((finish) => act(finish));
      expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
        "src",
        "/uploads/stored.jpg",
      );
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it("says so when the photo upload is refused", async () => {
    server.use(
      http.post("/api/v1/items/1/image", () =>
        HttpResponse.json({ detail: "Not an image" }, { status: 400 }),
      ),
    );
    const { container } = render(
      <ItemEditModal itemId="1" onClose={vi.fn()} />,
    );
    await screen.findByDisplayValue("Test Item");

    const input = container.querySelector(
      'input[type="file"][accept="image/*"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "p.jpg", { type: "image/jpeg" })] },
    });

    await waitFor(() =>
      expect(toast.error).toHaveBeenCalledWith("Not an image"),
    );
  });

  it("stops loading the valuation when the product behind the record cannot be read", async () => {
    server.use(
      http.get("/api/v1/items/1", () =>
        HttpResponse.json({ ...record, template_id: "tpl-gone" }),
      ),
      http.get("/api/v1/items/product-templates/tpl-gone", () =>
        HttpResponse.json({ detail: "gone" }, { status: 404 }),
      ),
    );
    render(<ItemEditModal itemId="1" onClose={vi.fn()} />);

    expect(await screen.findByDisplayValue("Test Item")).toBeInTheDocument();
    // The section settles on "no cost layers" instead of spinning forever.
    expect(await screen.findByText(/No cost layers yet/)).toBeInTheDocument();
    expect(screen.queryByText("Loading valuation…")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /save changes/i }),
    ).toBeInTheDocument();
  });
});
