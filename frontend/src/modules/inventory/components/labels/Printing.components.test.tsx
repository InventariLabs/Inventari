import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import {
  render as renderBare,
  screen,
  fireEvent,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { QueryWrapper } from "@/test/queryWrapper";
import { LabelCard } from "./LabelCard";
import { LabelRow } from "./LabelRow";
import type { LabelPool } from "@/types";

// The purpose name resolves through the module registry; pinned here so the
// assertions below read the wording, not the registry.
vi.mock("../../hooks/useLabelPurposeName", () => ({
  useLabelPurposeName: () => (tag?: string | null) => tag ?? "Products",
}));

// A label in use carries the Free label action, which asks the server through
// a query client.
const render = (ui: ReactElement) => renderBare(ui, { wrapper: QueryWrapper });

const noop = vi.fn();

const makeLabel = (overrides: Partial<LabelPool> = {}): LabelPool => ({
  id: "label-1",
  short_code: "INV-0001",
  is_assigned: false,
  assigned_at: null,
  item_id: null,
  organization_id: "org-1",
  created_at: "2026-01-01T00:00:00Z",
  scan_count: 3,
  label_type: "GENERIC",
  context_tag: null,
  description: null,
  printed_at: null,
  target_location_id: null,
  is_item_deleted: false,
  assigned_item_name: null,
  assigned_item_quantity: undefined,
  assigned_item_unit: undefined,
  ...overrides,
});

// ─── LabelCard ────────────────────────────────────────────────────────────────

describe("LabelCard", () => {
  it("renders short_code", () => {
    render(
      <LabelCard
        label={makeLabel()}
        isSelected={false}
        onToggleSelect={noop}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("INV-0001")).toBeInTheDocument();
  });

  it("shows 'In use' badge when label is assigned and item not deleted", () => {
    render(
      <LabelCard
        label={makeLabel({ is_assigned: true, assigned_item_name: "Milk" })}
        isSelected={false}
        onToggleSelect={noop}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("In use")).toBeInTheDocument();
  });

  it("shows assigned item name when assigned", () => {
    render(
      <LabelCard
        label={makeLabel({ is_assigned: true, assigned_item_name: "Butter" })}
        isSelected={false}
        onToggleSelect={noop}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("Butter")).toBeInTheDocument();
  });

  it("names an unassigned equipment label by its purpose, not as a product", () => {
    render(
      <LabelCard
        label={makeLabel({ context_tag: "equipment" })}
        isSelected={false}
        onToggleSelect={noop}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("equipment")).toBeInTheDocument();
  });

  it("shows scan count when not assigned", () => {
    render(
      <LabelCard
        label={makeLabel({ scan_count: 7 })}
        isSelected={false}
        onToggleSelect={noop}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    expect(screen.getByText("7")).toBeInTheDocument();
  });

  it("calls onToggleSelect when card is clicked", () => {
    const onToggleSelect = vi.fn();
    const { container } = render(
      <LabelCard
        label={makeLabel()}
        isSelected={false}
        onToggleSelect={onToggleSelect}
        onPreviewSingle={noop}
        onDelete={noop}
      />,
    );
    fireEvent.click(container.firstChild as Element);
    expect(onToggleSelect).toHaveBeenCalled();
  });
});

// ─── LabelRow ─────────────────────────────────────────────────────────────────

describe("LabelRow", () => {
  it("selects the row once for a tap on the checkbox's 44px square, and once for the row", async () => {
    const user = userEvent.setup();
    const onToggleSelect = vi.fn();
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel()}
            isSelected={false}
            onToggleSelect={onToggleSelect}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );

    const square = screen
      .getByRole("checkbox", { name: /Select label/ })
      .closest("label") as HTMLElement;
    await user.click(square);
    expect(onToggleSelect).toHaveBeenCalledTimes(1);

    await user.click(screen.getByText("INV-0001"));
    expect(onToggleSelect).toHaveBeenCalledTimes(2);
  });

  it("renders short_code in a table row", () => {
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel()}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("INV-0001")).toBeInTheDocument();
  });

  it("renders 'New' badge when neither printed nor assigned", () => {
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel()}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("New")).toBeInTheDocument();
  });

  it("renders 'In use' badge when assigned and item not deleted", () => {
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel({
              is_assigned: true,
              assigned_item_name: "Juice",
            })}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText("In use")).toBeInTheDocument();
  });

  it.each([
    [{ printed_at: "2026-01-01T00:00:00Z" }, "Printed"],
    [{ is_assigned: true, is_item_deleted: true }, "Archived"],
    // One state, one pill: an assigned label that was also printed is "In use".
    [{ is_assigned: true, printed_at: "2026-01-01T00:00:00Z" }, "In use"],
  ])("shows the single state pill for %j", (overrides, name) => {
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel(overrides as Partial<LabelPool>)}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );
    expect(screen.getByText(name)).toBeInTheDocument();
    expect(
      screen.queryAllByText(/^(New|Printed|In use|Archived)$/),
    ).toHaveLength(1);
  });

  it("calls onToggleSelect when row is clicked", () => {
    const onToggleSelect = vi.fn();
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel()}
            isSelected={false}
            onToggleSelect={onToggleSelect}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );
    fireEvent.click(screen.getByRole("row"));
    expect(onToggleSelect).toHaveBeenCalled();
  });

  it("does not call a label pointing at an asset a product", () => {
    // The assignment outlived the printing: a generic label assigned to an
    // equipment asset used to read "Product in use" over a column that said
    // "PRODUCTS" — both lies about what the sheet points at.
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel({
              is_assigned: true,
              assigned_item_name: "QAF Laptop X",
              assigned_item_context_tag: "equipment",
            })}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );

    expect(screen.getByText("equipment in use")).toBeInTheDocument();
    expect(screen.getByText("equipment")).toBeInTheDocument();
    expect(screen.queryByText("Product in use")).not.toBeInTheDocument();
    expect(screen.queryByText("Products")).not.toBeInTheDocument();
  });

  it("keeps the product wording for a label pointing at a product", () => {
    render(
      <table>
        <tbody>
          <LabelRow
            label={makeLabel({
              is_assigned: true,
              assigned_item_name: "Juice",
            })}
            isSelected={false}
            onToggleSelect={noop}
            onPreviewSingle={noop}
            onDelete={noop}
          />
        </tbody>
      </table>,
    );

    expect(screen.getByText("Product in use")).toBeInTheDocument();
    expect(screen.getByText("Products")).toBeInTheDocument();
  });
  it.each([
    [undefined, "Product (deleted)"],
    ["equipment", "equipment (deleted)"],
  ])(
    "does not describe a deleted item as in use (context %s)",
    (contextTag, subtitle) => {
      render(
        <table>
          <tbody>
            <LabelRow
              label={makeLabel({
                is_assigned: true,
                is_item_deleted: true,
                assigned_item_name: "Old drill",
                assigned_item_context_tag: contextTag,
              })}
              isSelected={false}
              onToggleSelect={noop}
              onPreviewSingle={noop}
              onDelete={noop}
            />
          </tbody>
        </table>,
      );

      expect(screen.getAllByText("Old drill").length).toBeGreaterThan(0);
      expect(screen.getByText(subtitle)).toBeInTheDocument();
      expect(screen.queryByText(/in use/)).not.toBeInTheDocument();
    },
  );
});

// end of test file
