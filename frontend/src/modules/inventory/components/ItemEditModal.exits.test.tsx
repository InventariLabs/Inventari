import { render, screen, fireEvent, waitFor, within, act } from "@/test/utils";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
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
 * backed out of, a chosen photo waits for Save (and a refused upload
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

  const pickPhoto = (container: HTMLElement) => {
    const input = container.querySelector(
      'input[type="file"][accept="image/*"]',
    ) as HTMLInputElement;
    fireEvent.change(input, {
      target: { files: [new File(["x"], "p.jpg", { type: "image/jpeg" })] },
    });
  };

  describe("a picked photo", () => {
    beforeEach(() => {
      // jsdom has no object URLs.
      URL.createObjectURL = vi.fn(() => "blob:picked");
      URL.revokeObjectURL = vi.fn();
    });

    it("is not written back by the update: the update never carries the picture the sheet opened with", async () => {
      let sent: Record<string, unknown> = {};
      server.use(
        http.get("/api/v1/items/1", () =>
          HttpResponse.json({ ...record, image_url: "/uploads/old.jpg" }),
        ),
        http.put("/api/v1/items/1", async ({ request }) => {
          sent = (await request.json()) as Record<string, unknown>;
          return HttpResponse.json(record);
        }),
      );
      const onClose = vi.fn();
      render(<ItemEditModal itemId="1" onClose={onClose} />);
      const name = await screen.findByDisplayValue("Test Item");
      fireEvent.change(name, { target: { value: "Renamed" } });

      fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(sent.name).toBe("Renamed");
      expect(sent).not.toHaveProperty("image_url");
    });

    it("keeps Save busy until the photo is stored, so a second click sends nothing", async () => {
      let release: () => void = () => {};
      const puts = vi.fn();
      const posts = vi.fn();
      server.use(
        http.put("/api/v1/items/1", () => {
          puts();
          return HttpResponse.json(record);
        }),
        http.post("/api/v1/items/1/image", async () => {
          posts();
          await new Promise<void>((resolve) => {
            release = resolve;
          });
          return HttpResponse.json({ image_url: "/uploads/stored.jpg" });
        }),
      );
      const onClose = vi.fn();
      const { container } = render(
        <ItemEditModal itemId="1" onClose={onClose} />,
      );
      await screen.findByDisplayValue("Test Item");
      pickPhoto(container);
      const save = screen.getByRole("button", { name: /save changes/i });

      fireEvent.click(save);
      await waitFor(() => expect(puts).toHaveBeenCalledTimes(1));
      // The update is answered; the photo is still on its way.
      await waitFor(() => expect(posts).toHaveBeenCalledTimes(1));
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 50));
      });
      expect(save).toBeDisabled();
      fireEvent.click(save);
      expect(puts).toHaveBeenCalledTimes(1);

      release();
      await waitFor(() => expect(onClose).toHaveBeenCalled());
    });

    it("waits for Save: nothing is uploaded and the sheet asks before it is closed", async () => {
      const uploads = vi.fn();
      server.use(
        http.post("/api/v1/items/1/image", () => {
          uploads();
          return HttpResponse.json({ image_url: "/uploads/stored.jpg" });
        }),
      );
      const onClose = vi.fn();
      const { container } = render(
        <ItemEditModal itemId="1" onClose={onClose} />,
      );
      await screen.findByDisplayValue("Test Item");

      pickPhoto(container);

      await waitFor(() =>
        expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
          "src",
          "blob:picked",
        ),
      );
      expect(uploads).not.toHaveBeenCalled();
      fireEvent.keyDown(window, { key: "Escape" });
      expect(await screen.findByRole("alertdialog")).toHaveTextContent(
        "Leave without saving?",
      );
      expect(onClose).not.toHaveBeenCalled();
    });

    it("is uploaded after the item is saved, so the save cannot write the old picture over it", async () => {
      const calls: string[] = [];
      server.use(
        http.put("/api/v1/items/1", () => {
          calls.push("save");
          return HttpResponse.json(record);
        }),
        http.post("/api/v1/items/1/image", () => {
          calls.push("photo");
          return HttpResponse.json({ image_url: "/uploads/stored.jpg" });
        }),
      );
      const onClose = vi.fn();
      const { container } = render(
        <ItemEditModal itemId="1" onClose={onClose} />,
      );
      await screen.findByDisplayValue("Test Item");
      pickPhoto(container);

      fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

      await waitFor(() => expect(onClose).toHaveBeenCalled());
      expect(calls).toEqual(["save", "photo"]);
    });

    it("says so when the photo is refused on Save, and the sheet stays open", async () => {
      server.use(
        http.post("/api/v1/items/1/image", () =>
          HttpResponse.json({ detail: "Not an image" }, { status: 400 }),
        ),
      );
      const onClose = vi.fn();
      const { container } = render(
        <ItemEditModal itemId="1" onClose={onClose} />,
      );
      await screen.findByDisplayValue("Test Item");
      pickPhoto(container);

      fireEvent.click(screen.getByRole("button", { name: /save changes/i }));

      expect(await screen.findByText("Not an image")).toBeInTheDocument();
      expect(onClose).not.toHaveBeenCalled();
    });

    it("keeps showing the picked photo when the local preview finishes reading later", async () => {
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
        const { container } = render(
          <ItemEditModal itemId="1" onClose={vi.fn()} />,
        );
        await screen.findByDisplayValue("Test Item");
        pickPhoto(container);
        await waitFor(() =>
          expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
            "src",
            "blob:picked",
          ),
        );

        readers.forEach((finish) => act(finish));

        expect(screen.getByRole("img", { name: /preview/i })).toHaveAttribute(
          "src",
          "blob:picked",
        );
      } finally {
        vi.unstubAllGlobals();
      }
    });
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
