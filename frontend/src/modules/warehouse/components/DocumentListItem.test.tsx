import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { DocumentListItem } from "./DocumentListItem";
import type {
  WarehouseDocument,
  WarehouseDocumentRow,
} from "@/modules/warehouse/types";
import {
  documentLine,
  documentRow,
  warehouseDocument,
} from "@/test/factories/documents";

const mockAuthState: { user: { role: string; is_superuser: boolean } | null } =
  { user: { role: "admin", is_superuser: false } };

vi.mock("@/store/authStore", () => ({
  useAuthStore: (selector?: (s: typeof mockAuthState) => unknown) =>
    selector ? selector(mockAuthState) : mockAuthState,
}));

// A row quotes what a document was worth only where the organization
// tracks value, so the profile is the test's to state.
let valueTracking = true;
vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: () => ({
    data: { value_tracking_enabled: valueTracking },
  }),
}));

// Cancel and delete ask for `warehouse:manage`, which is the key the API
// checks. The menu used to ask the account's role instead — a different rule,
// and one that told a custom role holding the permission it could not.
const rights = vi.hoisted(() => ({ manage: true }));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => rights.manage,
}));

// The row is built from a whole document the way the server builds it, so a
// test still says what is on the document and the row is what the list gets.
const makeDoc = (
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocumentRow =>
  documentRow(
    warehouseDocument({
      id: "doc-1",
      number: "IN/2026/001",
      type: "IN",
      status: "DRAFT",
      currency: "PLN",
      lines: [],
      ...overrides,
    }),
  );

function buildDocument(
  overrides: Partial<WarehouseDocument> = {},
): WarehouseDocumentRow {
  return documentRow(
    warehouseDocument({
      id: "doc-1",
      organization_id: "org-1",
      type: "IN",
      number: "PZ/2026/001",
      status: "COMPLETED",
      partner_id: "partner-1",
      source_location_id: null,
      target_location_id: "loc-1",
      scheduled_date: null,
      notes: null,
      external_reference: null,
      lines: [
        documentLine({
          id: "line-1",
          document_id: "doc-1",
          item_id: "item-1",
          product_template_id: null,
          name: "Widget",
          brand: null,
          barcode: null,
          quantity: "2",
          batch_number: null,
          expiry_date: null,
          notes: null,
          line_number: 1,
        }),
      ],
      created_by: "user-1",
      confirmed_by: "user-1",
      created_at: "2026-04-01T10:00:00Z",
      updated_at: "2026-04-01T10:00:00Z",
      confirmed_at: "2026-04-01T11:00:00Z",
      completed_at: "2026-04-01T12:00:00Z",
      ...overrides,
    }),
  );
}

const baseProps = {
  formattedDate: "2026-07-27",
  onOpenDetails: vi.fn(),
  onEdit: vi.fn(),
  onRequestAction: vi.fn(),
};

beforeEach(() => {
  valueTracking = true;
});

function openMenu() {
  fireEvent.click(screen.getByRole("button", { name: "More actions" }));
}

describe("DocumentListItem permission gating", () => {
  beforeEach(() => {
    mockAuthState.user = { role: "admin", is_superuser: false };
    rights.manage = true;
  });

  it("offers cancel and delete to an account that may manage documents", () => {
    render(<DocumentListItem doc={makeDoc()} {...baseProps} />);
    openMenu();
    expect(screen.getByRole("button", { name: "Cancel" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it("keeps edit and confirm for an account that may write but not manage", () => {
    rights.manage = false;
    render(<DocumentListItem doc={makeDoc()} {...baseProps} />);
    openMenu();
    expect(
      screen.queryByRole("button", { name: "Cancel" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm" })).toBeInTheDocument();
  });

  it("hides delete on a draft correction without manage", () => {
    rights.manage = false;
    render(
      <DocumentListItem doc={makeDoc({ type: "CORRECTION" })} {...baseProps} />,
    );
    openMenu();
    expect(
      screen.queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
  });

  it("leaves a read-only account no menu at all", () => {
    // Every entry in this menu ends in a mutating request, so the whole menu
    // goes. It used to offer Duplicate, Edit, Confirm and Execute and answer
    // 403 to each — on all 48 rows of the list.
    render(
      <DocumentListItem
        doc={makeDoc()}
        {...baseProps}
        canWrite={false}
        onDuplicate={vi.fn()}
      />,
    );
    expect(
      screen.queryByRole("button", { name: "More actions" }),
    ).not.toBeInTheDocument();
  });
});

describe("DocumentListItem duplicate action", () => {
  beforeEach(() => {
    mockAuthState.user = { role: "admin", is_superuser: false };
  });

  it("shows the duplicate action for a completed non-correction document", () => {
    render(
      <DocumentListItem
        doc={buildDocument()}
        {...baseProps}
        onDuplicate={vi.fn()}
      />,
    );
    openMenu();
    expect(
      screen.getByRole("button", { name: "Duplicate" }),
    ).toBeInTheDocument();
  });

  it("hides the duplicate action for correction documents", () => {
    render(
      <DocumentListItem
        doc={buildDocument({ type: "CORRECTION", status: "DRAFT" })}
        {...baseProps}
        onDuplicate={vi.fn()}
      />,
    );
    openMenu();
    expect(
      screen.queryByRole("button", { name: "Duplicate" }),
    ).not.toBeInTheDocument();
  });

  it("hides the duplicate action when no handler is provided", () => {
    render(<DocumentListItem doc={buildDocument()} {...baseProps} />);
    // COMPLETED document with no other actions → no menu at all.
    expect(
      screen.queryByRole("button", { name: "More actions" }),
    ).not.toBeInTheDocument();
  });

  it("calls onDuplicate with the document", async () => {
    const onDuplicate = vi.fn();
    const user = userEvent.setup();
    const doc = buildDocument();
    render(
      <DocumentListItem doc={doc} {...baseProps} onDuplicate={onDuplicate} />,
    );
    openMenu();
    await user.click(screen.getByRole("button", { name: "Duplicate" }));
    expect(onDuplicate).toHaveBeenCalledWith(doc);
  });
});

describe("DocumentListItem content", () => {
  beforeEach(() => {
    mockAuthState.user = { role: "admin", is_superuser: false };
  });

  it("answers 'from whom, where to, for how much' inline", () => {
    const { container } = render(
      <DocumentListItem
        doc={buildDocument({
          partner_snapshot: { name: "Acme Sp. z o.o." },
          source_location_name: "Receiving",
          target_location_name: "Shelf A",
          total_gross: "1234.50",
          currency: "PLN",
        })}
        {...baseProps}
      />,
    );
    expect(screen.getByText("Acme Sp. z o.o.")).toBeInTheDocument();
    expect(container.textContent).toContain("Receiving");
    expect(container.textContent).toContain("Shelf A");
    // NBSP between the ISO code and the amount makes exact string matching
    // brittle — assert the formatted amount itself.
    expect(screen.getByText(/1,234\.50/)).toBeInTheDocument();
  });

  it("quotes no amount for a transfer, whatever it holds", () => {
    // A move between shelves asks for no price; a stored value on one is
    // still stored and registered — the row just does not quote it.
    render(
      <DocumentListItem
        doc={buildDocument({
          type: "INT",
          number: "INT/2026/004",
          total_gross: "1234.50",
          currency: "PLN",
        })}
        {...baseProps}
      />,
    );

    expect(screen.queryByText(/1,234\.50/)).not.toBeInTheDocument();
  });

  it("quotes no amount while the profile does not track value", () => {
    valueTracking = false;

    render(
      <DocumentListItem
        doc={buildDocument({ total_gross: "1234.50", currency: "PLN" })}
        {...baseProps}
      />,
    );

    expect(screen.queryByText(/1,234\.50/)).not.toBeInTheDocument();
  });

  it("renders one row implementation — a single number link and menu trigger", () => {
    render(<DocumentListItem doc={makeDoc()} {...baseProps} />);
    expect(screen.getAllByRole("button", { name: "IN/2026/001" })).toHaveLength(
      1,
    );
    expect(
      screen.getAllByRole("button", { name: "More actions" }),
    ).toHaveLength(1);
  });

  it("keeps row actions behind the overflow menu until it opens", () => {
    render(<DocumentListItem doc={makeDoc()} {...baseProps} />);
    expect(
      screen.queryByRole("button", { name: "Edit" }),
    ).not.toBeInTheDocument();
    openMenu();
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("shows the execute action for confirmed documents", () => {
    render(
      <DocumentListItem
        doc={makeDoc({ status: "CONFIRMED" })}
        {...baseProps}
      />,
    );
    openMenu();
    expect(screen.getByRole("button", { name: "Execute" })).toBeInTheDocument();
  });
});

describe("DocumentListItem — execution progress", () => {
  const lines = [
    documentLine({ expected_quantity: "4", done_quantity: "1" }),
    documentLine({ expected_quantity: "6", done_quantity: "2" }),
  ];

  it("shows how far a confirmed document has been executed", () => {
    render(
      <DocumentListItem
        doc={makeDoc({ status: "CONFIRMED", lines })}
        {...baseProps}
      />,
    );

    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "3");
    expect(meter).toHaveAttribute("aria-valuemax", "10");
    expect(screen.getByText("3/10")).toBeInTheDocument();
  });

  it("shows nothing on a draft", () => {
    // A draft has nothing done yet — its numbers are intentions.
    render(
      <DocumentListItem
        doc={makeDoc({ status: "DRAFT", lines })}
        {...baseProps}
      />,
    );
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("does not add pieces, kilograms and packs into one number", () => {
    // The row summed unlike units into "56.5/62.5"; a reader could not tell
    // what was counted, and no bar can have a denominator in no unit.
    const mixed = [
      documentLine({
        expected_quantity: "20",
        done_quantity: "18",
        uom: { id: "u1", symbol: "pcs", name: "pieces", rounding: "1" },
      }),
      documentLine({
        expected_quantity: "12.5",
        done_quantity: "12.5",
        uom: { id: "u2", symbol: "kg", name: "kilograms", rounding: "1" },
      }),
      documentLine({
        expected_quantity: "30",
        done_quantity: "26",
        uom: { id: "u3", symbol: "pack", name: "packs", rounding: "1" },
      }),
    ];

    render(
      <DocumentListItem
        doc={makeDoc({ status: "CONFIRMED", lines: mixed })}
        {...baseProps}
      />,
    );

    expect(screen.queryByText("56.5/62.5")).not.toBeInTheDocument();
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
    expect(
      screen.getByText("18/20 pcs. · 12.5/12.5 kg · 26/30 pack"),
    ).toBeInTheDocument();
  });

  it("shows what did not arrive on a completed document", () => {
    // A closed receipt printing its plans alone reads as a delivered
    // order: "0/10" is a result, not noise.
    render(
      <DocumentListItem
        doc={makeDoc({ status: "COMPLETED", lines })}
        {...baseProps}
      />,
    );
    const meter = screen.getByRole("meter");
    expect(meter).toHaveAttribute("aria-valuenow", "3");
    expect(meter).toHaveAttribute("aria-valuemax", "10");
  });

  it("stays quiet on a completed document where everything arrived", () => {
    // A full bar on every completed receipt is decoration.
    const fullyServed = [
      documentLine({ expected_quantity: "4", done_quantity: "4" }),
      documentLine({ expected_quantity: "6", done_quantity: "6" }),
    ];
    render(
      <DocumentListItem
        doc={makeDoc({ status: "COMPLETED", lines: fullyServed })}
        {...baseProps}
      />,
    );
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("speaks on a completed document when one unit is short and another over-received", () => {
    // 30 pcs against 20 planned plus 5 kg against 12.5 sums to 35 >= 32.5,
    // so a comparison of summed totals let the over-receipt pay for the
    // shortage and left the row silent next to its own per-unit pairs.
    const overAndShort = [
      documentLine({
        expected_quantity: "20",
        done_quantity: "30",
        uom: { id: "u1", symbol: "pcs", name: "pieces", rounding: "1" },
      }),
      documentLine({
        expected_quantity: "12.5",
        done_quantity: "5",
        uom: { id: "u2", symbol: "kg", name: "kilograms", rounding: "1" },
      }),
    ];
    render(
      <DocumentListItem
        doc={makeDoc({ status: "COMPLETED", lines: overAndShort })}
        {...baseProps}
      />,
    );
    expect(screen.getByText("30/20 pcs. · 5/12.5 kg")).toBeInTheDocument();
  });
});

describe("DocumentListItem phone layout", () => {
  beforeEach(() => {
    mockAuthState.user = { role: "admin", is_superuser: false };
    rights.manage = true;
  });

  // jsdom has no layout, so the wrap is pinned by the classes that do it: on
  // a 320 px row the status badge, the line count and the progress bar used
  // to share one line and drew over each other.
  it("lets the row wrap and drops the figures onto their own line below sm", () => {
    const { container } = render(
      <DocumentListItem
        doc={makeDoc({
          status: "CONFIRMED",
          lines: [documentLine({ id: "l-1", expected_quantity: "3" })],
        })}
        {...baseProps}
      />,
    );
    const row = container.querySelector(".sm\\:flex-nowrap");
    expect(row?.className).toContain("flex-wrap");

    const figures = screen.getByRole("meter").closest(".max-sm\\:basis-full");
    expect(figures).not.toBeNull();
    expect(figures?.className).toContain("max-sm:order-last");
    expect(figures?.className).toContain("shrink-0");
  });

  it("keeps the figures beside the identity block from sm up", () => {
    const { container } = render(
      <DocumentListItem doc={makeDoc()} {...baseProps} />,
    );
    // nowrap restores the single-row layout, and the figures keep `shrink-0`
    // and the right alignment the wide layout always had.
    expect(container.querySelector(".sm\\:flex-nowrap")).not.toBeNull();
    const figures = screen.getByText(/line/i).closest(".text-right");
    expect(figures?.className).toContain("shrink-0");
  });

  describe("touch targets", () => {
    it("stretches the number button over the whole card", () => {
      render(
        <DocumentListItem
          doc={makeDoc()}
          {...baseProps}
          onToggleSelect={vi.fn()}
        />,
      );
      const number = screen.getByRole("button", { name: "IN/2026/001" });
      // jsdom has no layout: the overlay is a pseudo-element, so what can be
      // asserted is the pair that makes it cover the card — and the press
      // transform that would otherwise shrink it under a thumb.
      expect(number.className).toContain("after:absolute");
      expect(number.className).toContain("after:inset-0");
      expect(number.className).toContain("active:![transform:none]");
      expect(number.closest(".relative")).not.toBeNull();
    });

    it("opens the document from the number button", () => {
      const onOpenDetails = vi.fn();
      render(
        <DocumentListItem
          doc={makeDoc()}
          {...baseProps}
          onOpenDetails={onOpenDetails}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "IN/2026/001" }));
      expect(onOpenDetails).toHaveBeenCalledExactlyOnceWith("doc-1");
    });

    it("toggles the document instead of opening it while a selection is under way", () => {
      const onOpenDetails = vi.fn();
      const onToggleSelect = vi.fn();
      render(
        <DocumentListItem
          doc={makeDoc()}
          {...baseProps}
          onOpenDetails={onOpenDetails}
          selectionActive
          onToggleSelect={onToggleSelect}
        />,
      );
      fireEvent.click(screen.getByRole("button", { name: "IN/2026/001" }));
      expect(onToggleSelect).toHaveBeenCalledExactlyOnceWith("doc-1");
      expect(onOpenDetails).not.toHaveBeenCalled();
    });

    it("gives the checkbox a 44 px target above the overlay, and the number a 44 px height", () => {
      const onOpenDetails = vi.fn();
      const onToggleSelect = vi.fn();
      render(
        <DocumentListItem
          doc={makeDoc()}
          {...baseProps}
          onOpenDetails={onOpenDetails}
          onToggleSelect={onToggleSelect}
        />,
      );
      const target = screen.getByRole("checkbox").closest("label")!;
      expect(target.className).toContain("h-11");
      expect(target.className).toContain("w-11");
      expect(target.className).toContain("z-10");
      // The z-10 stays inside the card: left to the page's stacking context,
      // it would show through a sticky bulk bar scrolled over the list.
      expect(target.closest(".isolate")).not.toBeNull();
      fireEvent.click(target);
      expect(onToggleSelect).toHaveBeenCalledExactlyOnceWith("doc-1");
      expect(onOpenDetails).not.toHaveBeenCalled();
      expect(
        screen.getByRole("button", { name: "IN/2026/001" }).className,
      ).toContain("min-h-11");
    });
  });
});
