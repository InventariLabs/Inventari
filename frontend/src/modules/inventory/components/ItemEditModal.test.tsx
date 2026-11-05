import { render, screen, fireEvent, waitFor } from "@/test/utils";
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "@/test/mocks/server";
import ItemEditModal from "./ItemEditModal";
import { signInWith, signOut } from "@/test/auth";
import { useAuthStore } from "@/store/authStore";
import { onePage } from "@/test/mocks/page";
import userEvent from "@testing-library/user-event";
import { useQueryClient, type QueryClient } from "@tanstack/react-query";
import { queryKeys } from "@/hooks/queries/keys";
import { useScopedCategories } from "@/modules/shared/hooks/useCategories";

// The sheet edits for an account holding `items:write` and only shows the
// product to one that does not; the describes below that do not sign in
// themselves are about editing.
beforeEach(() => signInWith(["items:read", "items:write", "items:delete"]));
afterEach(() => signOut());

describe("ItemEditModal", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  describe("opened from a row about a date", () => {
    let scrollIntoView: ReturnType<typeof vi.spyOn>;
    beforeEach(() => {
      scrollIntoView = vi.spyOn(HTMLElement.prototype, "scrollIntoView");
      // A dated record: the expiry field belongs to a category that keeps dates.
      server.use(
        http.get("/api/v1/items/:id", () =>
          HttpResponse.json({
            id: "1",
            name: "Test Item",
            quantity: 10,
            unit: "pcs",
            category_id: "77",
            expiry_date: "2026-10-29",
            added_date: new Date().toISOString(),
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          }),
        ),
        http.get("/api/v1/categories", () =>
          HttpResponse.json(
            onePage([
              {
                id: "77",
                name: "Dairy",
                sort_order: 1,
                field_definitions: [
                  {
                    key: "expiry_date",
                    type: "date",
                    label: "Expiry date",
                    visible: true,
                    required: false,
                  },
                ],
              },
            ]),
          ),
        ),
      );
    });
    afterEach(() => scrollIntoView.mockRestore());

    it("brings the expiry date into view, the reason the row was tapped", async () => {
      render(<ItemEditModal itemId="1" onClose={() => {}} openAtExpiry />);
      await screen.findByDisplayValue(/Test Item/i);

      await waitFor(() => expect(scrollIntoView).toHaveBeenCalledTimes(1));
      expect(scrollIntoView.mock.contexts[0]).toHaveAttribute(
        "data-field-key",
        "expiry_date",
      );
    });

    it("opens at the top when nothing asked for the date", async () => {
      render(<ItemEditModal itemId="1" onClose={() => {}} />);
      await screen.findByDisplayValue(/Test Item/i);

      expect(scrollIntoView).not.toHaveBeenCalled();
    });
  });

  it("should render edit modal with item data", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);

    // Header title
    expect(await screen.findByText(/Edit product/i)).toBeInTheDocument();

    // Field values
    expect(await screen.findByDisplayValue(/Test Item/i)).toBeInTheDocument();
    expect(screen.getByDisplayValue(/Test Brand/i)).toBeInTheDocument();
  });

  /**
   * The item form takes its labels and placeholders from key strings held in
   * SYSTEM_FIELDS, not from t() call sites, so a dead-code cleanup once deleted
   * the whole vocabulary as "orphans" and every label rendered as its own key
   * ("itemBrand", "fields.purchase_price") in all five languages.
   *
   * Asserting the actual strings — rather than merely the absence of raw keys
   * — is what makes this a regression test: a deleted key now surfaces as the
   * "Untitled field" fallback or an empty placeholder, neither of which looks
   * like a key.
   */
  it("renders translated field labels and placeholders", async () => {
    const { container } = render(
      <ItemEditModal itemId="1" onClose={() => {}} />,
    );
    await screen.findByDisplayValue(/Test Item/i);

    const labels = [...container.querySelectorAll("label")].map((el) =>
      (el.textContent ?? "").trim(),
    );
    expect(labels).toEqual(
      expect.arrayContaining([
        "Brand",
        "Quantity",
        "Shelf Location",
        "Weight / volume per piece",
        "Description / Notes",
        "Expiry date",
        "Freeze date",
        "Purchase price per unit",
        "Serial Number",
      ]),
    );
    // The getLabel() fallback for a key that resolves nowhere.
    expect(labels).not.toContain("Untitled field");

    const placeholders = [
      ...container.querySelectorAll("input, textarea"),
    ].flatMap((el) => {
      const value = el.getAttribute("placeholder");
      return value ? [value] : [];
    });
    expect(placeholders).toEqual(
      expect.arrayContaining([
        "e.g. Nestlé, Bosch, IKEA",
        "e.g. Shelf A, rack 2",
        "Additional notes…",
        // Was "e.g. 1299.99" — the price of one laptop, which reads as the
        // amount on an invoice rather than a rate. This field is the rate.
        "e.g. 4.50",
        "e.g. SN-001234",
      ]),
    );
  });

  it("should call update API when save button is clicked", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);

    const nameInput = await screen.findByDisplayValue(/Test Item/i);
    fireEvent.change(nameInput, { target: { value: "Updated Item Name" } });

    // Button text is "Save changes" in translations
    const saveButton = screen.getByRole("button", { name: /Save changes/i });
    fireEvent.click(saveButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });

  /**
   * The Save button must stay on screen however long the form is. That holds
   * only while the footer is a sibling of the scrolling body inside a clipped
   * column: a footer moved into the body scrolls away with the fields, and
   * a bare "Save is in the document" assertion would pass all the same.
   * JSDOM has no layout, so the placement is pinned structurally.
   */
  it("keeps the save footer outside the scrolling body", async () => {
    const { container } = render(
      <ItemEditModal itemId="1" onClose={() => {}} />,
    );
    await screen.findByDisplayValue(/Test Item/i);

    const dialog = screen.getByRole("dialog");
    const save = screen.getByRole("button", { name: /Save changes/i });
    const body = container.querySelector("#edit-item-form")?.parentElement;

    expect(body?.className).toContain("overflow-y-auto");
    expect(body).not.toContainElement(save);
    // The column clips and stacks: the body takes what is left, the footer
    // keeps its own row below it.
    expect(dialog.className).toContain("flex-col");
    expect(dialog.className).toContain("overflow-hidden");
    expect(body?.className).toContain("flex-1");
    expect(body?.nextElementSibling).toContainElement(save);
  });

  it("should call delete API when delete button is clicked", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);

    // Deleting acts on the item, not on the edit, so it lives in the header's
    // overflow menu rather than in the footer.
    fireEvent.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    const deleteButton = await screen.findByRole("button", {
      name: /Delete product/i,
    });
    fireEvent.click(deleteButton);

    // The dialog will not delete anything until it is told why.
    const reasonSelect = await screen.findByTestId("deletion-reason");
    const confirmButton = screen.getByRole("button", { name: /^Delete$/i });
    expect(confirmButton).toBeDisabled();

    fireEvent.change(reasonSelect, { target: { value: "EXPIRED" } });
    fireEvent.click(confirmButton);

    await waitFor(() => {
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("frees a label put on the wrong product from the header menu", async () => {
    const freed: string[] = [];
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Item",
          quantity: 10,
          unit: "pcs",
          category_id: "1",
          location_id: "1",
          label_code: "STM-0042",
          added_date: new Date().toISOString(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.post("/api/v1/labels/pool/:code/unassign", ({ params }) => {
        freed.push(String(params.code));
        return HttpResponse.json({ message: "Label is now free for reuse" });
      }),
    );
    render(<ItemEditModal itemId="1" onClose={() => {}} />);

    fireEvent.click(
      await screen.findByRole("button", { name: /more actions/i }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "Free label" }));
    // Nothing happens until the question is answered.
    expect(freed).toEqual([]);
    fireEvent.click(await screen.findByRole("button", { name: "Free label" }));

    await waitFor(() => expect(freed).toEqual(["STM-0042"]));
  });

  it("closes straight away when nothing was touched", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);
    await screen.findByDisplayValue(/Test Item/i);

    fireEvent.click(screen.getAllByRole("button", { name: /close/i })[0]);

    expect(onClose).toHaveBeenCalled();
  });

  it("asks before dropping an edit in progress", async () => {
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);

    const brand = await screen.findByDisplayValue(/Test Brand/i);
    fireEvent.change(brand, { target: { value: "Something typed" } });

    fireEvent.click(screen.getAllByRole("button", { name: /close/i })[0]);

    expect(onClose).not.toHaveBeenCalled();
    expect(
      await screen.findByText("Leave without saving?"),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /discard changes/i }));
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });
});

describe("ItemEditModal — Valuation", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("does not show valuation section when item has no template_id", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);

    expect(screen.queryByText(/Valuation/i)).not.toBeInTheDocument();
  });
});

describe("ItemEditModal — not found", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  it("shows a 'not found' state with a back link when the item 404s", async () => {
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({ detail: "Not found" }, { status: 404 }),
      ),
    );

    render(<ItemEditModal itemId="missing-uuid" onClose={() => {}} />);

    expect(
      await screen.findByText(/not found|nie znaleziono|could not be loaded/i, {
        exact: false,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /back to items|back|close/i }),
    ).toBeInTheDocument();
  });

  describe("footer", () => {
    /**
     * The filled red button belongs to the confirmation dialog, where the
     * destructive act is the point of the screen; in a row it outweighs the
     * row's own content (§2.13a).
     */
    it("colours the delete at rest instead of filling it", async () => {
      render(<ItemEditModal itemId="1" onClose={() => {}} />);
      await screen.findByDisplayValue(/Test Item/i);

      fireEvent.click(screen.getByRole("button", { name: /more actions/i }));
      const remove = await screen.findByRole("button", {
        name: /delete product/i,
      });
      // The label carries the colour at rest, the background stays out of it
      // until the pointer arrives.
      expect(remove).toHaveClass("bg-transparent");
      expect(remove).toHaveClass("text-on-danger");
    });

    /**
     * The footer speaks about this edit — save it or abandon it. Deleting
     * speaks about the record and outlives the dialog, so it is not a second
     * row here but an entry in the header menu (§4.3).
     */
    it("keeps the record's own actions out of the footer", async () => {
      render(<ItemEditModal itemId="1" onClose={() => {}} />);
      await screen.findByDisplayValue(/Test Item/i);

      expect(
        screen.queryByRole("button", { name: /delete item/i }),
      ).not.toBeInTheDocument();
      const save = screen.getByRole("button", { name: /save/i });
      expect(save.parentElement?.children).toHaveLength(2);
    });

    it("puts the way out before the way forward", async () => {
      render(<ItemEditModal itemId="1" onClose={() => {}} />);
      await screen.findByDisplayValue(/Test Item/i);

      const save = screen.getByRole("button", { name: /save/i });
      const close = save.parentElement?.firstElementChild;
      expect(close).toHaveTextContent(/close/i);
    });
  });
});

describe("ItemEditModal — one panel, one height", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  /**
   * The dialog is as tall as its content, so a short History panel next to a
   * long form made the window jump on every tab switch. The product page owns
   * the history (its own tab), so the dialog keeps the form alone: there is no
   * second panel to differ in height from the first.
   */
  it("offers no tabs, so switching cannot resize it", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    await screen.findByDisplayValue(/Test Item/i);

    expect(screen.queryByRole("tablist")).not.toBeInTheDocument();
    expect(screen.queryByRole("tab")).not.toBeInTheDocument();
  });

  it("keeps the save footer on screen, since no tab can replace it", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    await screen.findByDisplayValue(/Test Item/i);

    expect(screen.getByRole("button", { name: /save/i })).toBeInTheDocument();
  });
});

describe("ItemEditModal — the record's category feeds the form's fields", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  /**
   * The add form computes its fields from the picked category's
   * field_definitions; the edit dialog must answer with the same set for
   * the same record — an asset tag typed at creation has to be correctable
   * at edit time.
   */
  it("renders the category's declared fields for the edited record", async () => {
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Item",
          quantity: 10,
          unit: "pcs",
          category_id: "77",
          brand: "Test Brand",
          added_date: new Date().toISOString(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.get("/api/v1/categories", () =>
        HttpResponse.json(
          onePage([
            { id: "1", name: "Food", sort_order: 1 },
            {
              id: "77",
              name: "Laptop",
              code: "LAPTOP",
              sort_order: 2,
              field_definitions: [
                {
                  key: "asset_tag",
                  type: "text",
                  label: "Asset Tag",
                  visible: true,
                  required: false,
                  is_system: true,
                },
                {
                  key: "ram_gb",
                  type: "number",
                  label: "RAM (GB)",
                  visible: true,
                  required: false,
                  is_system: true,
                },
              ],
            },
          ]),
        ),
      ),
    );

    const { container } = render(
      <ItemEditModal itemId="1" onClose={() => {}} />,
    );
    await screen.findByDisplayValue(/Test Item/i);

    const labels = [...container.querySelectorAll("label")].map((el) =>
      (el.textContent ?? "").trim(),
    );
    expect(labels).toEqual(expect.arrayContaining(["Asset Tag", "RAM (GB)"]));
  });
});

describe("ItemEditModal — the order the product's stock leaves in", () => {
  beforeEach(() => {
    useAuthStore.setState({
      user: {
        is_blocked: false,
        is_superuser: false,
        permissions: ["items:read", "items:write", "items:delete"],
        is_active: true,
        id: "1",
        full_name: "Test User",
        email: "test@example.com",
        preferred_language: "en",
        role: "user",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
      isAuthenticated: true,
    });
  });

  const itemWithStrategy = (strategy: string | null) => ({
    id: "1",
    name: "Test Item",
    quantity: 10,
    location_id: "1",
    template_id: "t1",
    template: { id: "t1", name: "Test Item", removal_strategy: strategy },
    added_date: new Date().toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  });

  // The modal reads the product for its valuation section.
  beforeEach(() => {
    server.use(
      http.get("/api/v1/items/product-templates/:id", () =>
        HttpResponse.json({ id: "t1", name: "Test Item" }),
      ),
    );
  });

  it("shows the product's strategy with a sentence for each choice", async () => {
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json(itemWithStrategy("FEFO")),
      ),
    );

    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    await screen.findByDisplayValue(/Test Item/i);

    const group = await screen.findByRole("radiogroup", {
      name: "Which stock leaves first",
    });
    expect(group).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "FEFO" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.getByText("FIFO: what came in first leaves first."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "FEFO: what expires first leaves first, whenever it came in.",
      ),
    ).toBeInTheDocument();
  });

  it("shows a shared product's order without offering to change it", async () => {
    // The server keeps a catalogue product's order for every organization;
    // the choice used to be offered, answered "Updated" and saved nothing.
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({
          ...itemWithStrategy(null),
          template: {
            id: "t1",
            name: "Test Item",
            removal_strategy: null,
            organization_id: null,
          },
        }),
      ),
    );
    render(<ItemEditModal itemId="1" onClose={vi.fn()} />);
    await screen.findByDisplayValue(/Test Item/i);

    expect(
      await screen.findByText(/comes from the shared catalogue/),
    ).toBeInTheDocument();
    expect(screen.getByText("FIFO")).toBeInTheDocument();
    expect(
      screen.queryByRole("radio", { name: "FEFO" }),
    ).not.toBeInTheDocument();
  });

  it("saves FEFO chosen on a product that had no strategy", async () => {
    let sent: Record<string, unknown> | null = null;
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json(itemWithStrategy(null)),
      ),
      http.put("/api/v1/items/:id", async ({ request }) => {
        sent = (await request.json()) as Record<string, unknown>;
        return HttpResponse.json(itemWithStrategy("FEFO"));
      }),
    );
    const onClose = vi.fn();
    render(<ItemEditModal itemId="1" onClose={onClose} />);
    await screen.findByDisplayValue(/Test Item/i);

    // Nothing set reads as FIFO, the way the stock engine reads it.
    expect(await screen.findByRole("radio", { name: "FIFO" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    fireEvent.click(screen.getByRole("radio", { name: "FEFO" }));
    fireEvent.click(screen.getByRole("button", { name: /Save changes/i }));

    await waitFor(() => expect(onClose).toHaveBeenCalled());
    expect(sent).toMatchObject({ removal_strategy: "FEFO" });
  });
});

/**
 * A viewer opens the product to read it. The sheet used to open as "Edit
 * product" with every field live and a Save that answered 403 after the work.
 */
describe("ItemEditModal — a reader without items:write", () => {
  beforeEach(() => signInWith(["items:read"]));
  afterEach(() => signOut());

  it("shows the product read-only: no editable field, no Save, no delete", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    const brand = await screen.findByDisplayValue(/Test Brand/i);

    expect(screen.queryByText("Edit product")).not.toBeInTheDocument();
    expect(screen.getByText("Product")).toBeInTheDocument();
    expect(brand).toBeDisabled();
    expect(screen.getByDisplayValue(/Test Item/i)).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: /^save/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /more actions/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Close" }).at(-1),
    ).toBeEnabled();
  });

  it("says why the form cannot be changed", async () => {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    await screen.findByDisplayValue(/Test Brand/i);

    expect(screen.getByRole("note")).toHaveTextContent(
      /view this, not change it/i,
    );
  });
});

/**
 * The thumbnail shows the picked file until Save stores it. A refused photo
 * left it there, where it read as the product's picture until the sheet was
 * reopened.
 */
describe("ItemEditModal — a picture the server refused", () => {
  const SAVED = "/uploads/saved.png";

  const picture = (name: string) =>
    new File(["pixels"], name, { type: "image/gif" });

  beforeEach(() => {
    // jsdom has no object URLs.
    URL.createObjectURL = vi.fn(() => "blob:picked");
    URL.revokeObjectURL = vi.fn();
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Item",
          quantity: 1,
          category_id: "1",
          location_id: "1",
          image_url: SAVED,
          added_date: new Date().toISOString(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
      http.put("/api/v1/items/:id", () => HttpResponse.json({ id: "1" })),
      http.post("/api/v1/items/:id/image", () =>
        HttpResponse.json({ detail: "The file is too large" }, { status: 413 }),
      ),
    );
  });

  async function pickAndSave() {
    render(<ItemEditModal itemId="1" onClose={() => {}} />);
    await screen.findByDisplayValue(/Test Item/i);
    const thumbnail = () => screen.getByAltText(/image preview/i);
    await waitFor(() => expect(thumbnail()).toHaveAttribute("src", SAVED));
    const input = document.querySelector<HTMLInputElement>(
      'input[type="file"][accept="image/*"]',
    )!;
    const user = userEvent.setup();
    await user.upload(input, picture("too-big.png"));
    await waitFor(() =>
      expect(thumbnail()).toHaveAttribute("src", "blob:picked"),
    );
    await user.click(screen.getByRole("button", { name: /save changes/i }));
    return { thumbnail, input, user };
  }

  it("goes back to the product's picture once the upload is refused", async () => {
    const { thumbnail } = await pickAndSave();

    expect(await screen.findByText("The file is too large")).toBeVisible();
    await waitFor(() => expect(thumbnail()).toHaveAttribute("src", SAVED));
  });

  it("lets the same file be picked again after a refusal", async () => {
    const { input } = await pickAndSave();

    await screen.findByText("The file is too large");
    // A browser fires no change for the file the input already holds, so a
    // retry of the same file would do nothing and say nothing.
    expect(input.value).toBe("");
  });
});

/**
 * Which fields the form draws comes from the category list. A list that never
 * arrived left the form on the base fields with nothing saying so: a laptop's
 * asset tag simply was not there.
 */
describe("ItemEditModal — a category list that failed", () => {
  const LAPTOP = {
    id: "cat-lap",
    name: "Laptop",
    sort_order: 1,
    field_definitions: [
      {
        key: "asset_tag",
        type: "text",
        label: "Asset Tag",
        visible: true,
        required: false,
      },
    ],
  };

  beforeEach(() => {
    server.use(
      http.get("/api/v1/items/:id", () =>
        HttpResponse.json({
          id: "1",
          name: "Test Item",
          quantity: 1,
          category_id: LAPTOP.id,
          added_date: new Date().toISOString(),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
        }),
      ),
    );
  });

  it("says the fields may be missing, and a retry brings them back", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    render(<ItemEditModal itemId="1" onClose={() => {}} />);

    expect(
      await screen.findByText(/categories could not be loaded/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Asset Tag")).not.toBeInTheDocument();

    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([LAPTOP])),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));

    expect(await screen.findByLabelText("Asset Tag")).toBeInTheDocument();
    expect(
      screen.queryByText(/categories could not be loaded/i),
    ).not.toBeInTheDocument();
  });

  it("says nothing when a refresh fails while the last list still stands", async () => {
    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json(onePage([LAPTOP])),
      ),
    );
    let client: QueryClient | undefined;
    // Reads the query the form reads, so the assertion below runs on a render
    // that has already seen the refresh fail.
    function ListError() {
      client = useQueryClient();
      const { error } = useScopedCategories(LAPTOP.id);
      return error ? <span>refresh failed</span> : null;
    }
    render(
      <>
        <ItemEditModal itemId="1" onClose={() => {}} />
        <ListError />
      </>,
    );
    expect(await screen.findByLabelText("Asset Tag")).toBeInTheDocument();

    server.use(
      http.get("/api/v1/categories", () =>
        HttpResponse.json({ detail: "boom" }, { status: 500 }),
      ),
    );
    await client?.invalidateQueries({ queryKey: queryKeys.categories.all });

    expect(await screen.findByText("refresh failed")).toBeInTheDocument();
    expect(screen.getByLabelText("Asset Tag")).toBeInTheDocument();
    expect(
      screen.queryByText(/categories could not be loaded/i),
    ).not.toBeInTheDocument();
  });
});
