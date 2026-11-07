import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import IngredientTemplateCombobox from "./IngredientTemplateCombobox";

vi.mock("@/lib/api/productTemplates", () => ({
  productTemplatesApi: {
    search: vi.fn(),
  },
}));

import { productTemplatesApi } from "@/lib/api/productTemplates";

const mockSearch = vi.mocked(productTemplatesApi.search);

describe("IngredientTemplateCombobox", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSearch.mockResolvedValue([
      {
        id: "tpl-1",
        name: "Organic Spaghetti",
        brand: "BioFarm",
        uom_id: null,
      },
      {
        id: "tpl-2",
        name: "Spaghetti Bolognese Kit",
        brand: null,
        uom_id: null,
      },
    ] as never);
  });

  it("does not search below 2 characters", async () => {
    render(
      <IngredientTemplateCombobox
        query="s"
        value={null}
        onChange={vi.fn()}
        onQueryChange={vi.fn()}
      />,
    );
    await new Promise((r) => setTimeout(r, 400));
    expect(mockSearch).not.toHaveBeenCalled();
  });

  it("searches and offers suggestions after typing 2+ characters", async () => {
    const onQueryChange = vi.fn();
    const { rerender } = render(
      <IngredientTemplateCombobox
        query=""
        value={null}
        onChange={vi.fn()}
        onQueryChange={onQueryChange}
      />,
    );
    const input = screen.getByPlaceholderText("Ingredient name");
    fireEvent.change(input, { target: { value: "spa" } });
    rerender(
      <IngredientTemplateCombobox
        query="spa"
        value={null}
        onChange={vi.fn()}
        onQueryChange={onQueryChange}
      />,
    );
    await waitFor(() => expect(mockSearch).toHaveBeenCalledWith("spa"));
    await waitFor(() => {
      expect(screen.getByText("Organic Spaghetti")).toBeInTheDocument();
    });
  });

  it("links the selected template", async () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <IngredientTemplateCombobox
        query=""
        value={null}
        onChange={onChange}
        onQueryChange={vi.fn()}
      />,
    );
    fireEvent.change(screen.getByPlaceholderText("Ingredient name"), {
      target: { value: "spa" },
    });
    rerender(
      <IngredientTemplateCombobox
        query="spa"
        value={null}
        onChange={onChange}
        onQueryChange={vi.fn()}
      />,
    );
    fireEvent.mouseDown(await screen.findByText("Organic Spaghetti"));
    expect(onChange).toHaveBeenCalledWith("tpl-1", "Organic Spaghetti");
  });

  it("renders the dropdown through a portal, escaping clipping ancestors", async () => {
    const { container, rerender } = render(
      <div className="overflow-hidden">
        <IngredientTemplateCombobox
          query=""
          value={null}
          onChange={vi.fn()}
          onQueryChange={vi.fn()}
        />
      </div>,
    );
    const clipped = container.firstElementChild!;
    const input = screen.getByPlaceholderText("Ingredient name");
    fireEvent.change(input, { target: { value: "spa" } });
    rerender(
      <div className="overflow-hidden">
        <IngredientTemplateCombobox
          query="spa"
          value={null}
          onChange={vi.fn()}
          onQueryChange={vi.fn()}
        />
      </div>,
    );
    const suggestion = await screen.findByText("Organic Spaghetti");
    // Same clipping issue as UomSelect: the dropdown used `absolute` inside
    // the ingredient card (overflow-hidden) and was cut off / unclickable.
    expect(clipped).not.toContainElement(suggestion);
  });

  /**
   * The suggestion is a real `<button>`, but its only handler was
   * `onMouseDown` — and a keyboard press on a button emits `click`, never
   * `mousedown`. ArrowDown showed a focus ring on something Enter could not
   * accept, so a form filled from the keyboard left every ingredient unlinked.
   */
  describe("accepting a suggestion without a mouse", () => {
    async function openList(onChange = vi.fn()) {
      const user = userEvent.setup();
      const { rerender } = render(
        <IngredientTemplateCombobox
          query=""
          value={null}
          onChange={onChange}
          onQueryChange={vi.fn()}
        />,
      );
      const input = screen.getByPlaceholderText("Ingredient name");
      fireEvent.change(input, { target: { value: "spa" } });
      rerender(
        <IngredientTemplateCombobox
          query="spa"
          value={null}
          onChange={onChange}
          onQueryChange={vi.fn()}
        />,
      );
      await screen.findByText("Organic Spaghetti");
      input.focus();
      return { user, input, onChange };
    }

    it("links the ingredient on Enter", async () => {
      const { user, onChange } = await openList();

      await user.keyboard("{ArrowDown}{Enter}");

      expect(onChange).toHaveBeenCalledWith("tpl-1", "Organic Spaghetti");
    });

    it("links the ingredient on Space", async () => {
      const { user, onChange } = await openList();

      await user.keyboard("{ArrowDown}[Space]");

      expect(onChange).toHaveBeenCalledWith("tpl-1", "Organic Spaghetti");
    });

    it("walks the whole list with the arrows", async () => {
      const { user, onChange } = await openList();

      await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");

      expect(onChange).toHaveBeenCalledWith("tpl-2", "Spaghetti Bolognese Kit");
    });

    it("returns to the typed name from the first suggestion", async () => {
      const { user, input } = await openList();

      await user.keyboard("{ArrowDown}{ArrowUp}");

      expect(document.activeElement).toBe(input);
    });

    it("keeps the caret in the field while the list is open", async () => {
      // The typed text is the value; the list is a suggestion on top of it.
      const { input } = await openList();

      expect(document.activeElement).toBe(input);
    });

    it("closes the list once focus moves on to another control", async () => {
      // The unit picker sits right under the name. A list left open over it
      // hid its options, and a click aimed at a unit landed on a suggestion.
      const { user } = await openList();
      const next = document.createElement("button");
      next.textContent = "Unit";
      document.body.appendChild(next);

      await user.click(next);

      await waitFor(() =>
        expect(screen.queryByText("Organic Spaghetti")).not.toBeInTheDocument(),
      );
      next.remove();
    });

    it("keeps the list open while focus walks into it", async () => {
      const { user } = await openList();

      await user.keyboard("{ArrowDown}");

      expect(screen.getByText("Organic Spaghetti")).toBeInTheDocument();
    });

    it("does not open the list by focusing the field alone", async () => {
      // A pointer click focuses and then clicks: opening on focus and
      // toggling on click left the list shut after a click and open after
      // a Tab, over whatever the reader was heading for.
      const user = userEvent.setup();
      render(
        <IngredientTemplateCombobox
          query="spa"
          value={null}
          onChange={vi.fn()}
          onQueryChange={vi.fn()}
        />,
      );
      await waitFor(() => expect(mockSearch).toHaveBeenCalled());

      await user.tab();

      expect(screen.queryByText("Organic Spaghetti")).not.toBeInTheDocument();
    });

    it("renders the list on a Radix popper layer, so Escape stops there", async () => {
      // The sheet around this field reads exactly this marker before deciding
      // whether an Escape was aimed at it or at the list.
      await openList();

      expect(
        document.querySelector("[data-radix-popper-content-wrapper]"),
      ).not.toBeNull();
    });
  });
});
