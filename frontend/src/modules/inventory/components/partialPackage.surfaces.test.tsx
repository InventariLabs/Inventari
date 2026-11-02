import { http, HttpResponse } from "msw";
import { describe, it, expect, vi } from "vitest";

import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";
import type { Item, LabelScanView } from "@/types";
import ItemDetailOverview from "./items/ItemDetailOverview";
import ItemMobileCard from "./items/ItemMobileCard";
import ItemTable from "./items/ItemTable";
import StockActionSheet from "./StockActionSheet";
import { onePage } from "@/test/mocks/page";

/**
 * A record kept in pieces that is partly used reads in the weight or volume
 * unit of its card — "1.5 kg left of 2 kg" — on every screen that showed the
 * bare fraction of a piece. The stored quantity is not touched.
 */

const KG = "uom-kg";
const PCS = "uom-pcs";

const catalogue = [
  {
    id: "cat-weight",
    name: "Weight",
    uoms: [
      { id: KG, category_id: "cat-weight", name: "Kilogram", symbol: "kg" },
    ],
  },
  {
    id: "cat-unit",
    name: "Unit",
    uoms: [{ id: PCS, category_id: "cat-unit", name: "Piece", symbol: "pcs" }],
  },
];

function useCatalogue() {
  server.use(
    http.get("*/uoms/categories", () => HttpResponse.json(onePage(catalogue))),
  );
}

const makeItem = (
  quantity: string,
  template: Partial<NonNullable<Item["template"]>> = {
    weight_value: 2,
    weight_uom_id: KG,
  },
): Item =>
  ({
    id: "item-1",
    name: "Flour",
    quantity,
    organization_id: "org-1",
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    is_deleted: false,
    uom_id: PCS,
    uom: {
      id: PCS,
      symbol: "pcs",
      name: "Piece",
      rounding: "1",
      category_name: "Unit",
    },
    template,
  }) as unknown as Item;

const tableProps = {
  storages: [],
  categories: [],
  enabledModules: [],
  onItemClick: vi.fn(),
  onConsume: vi.fn(),
  onAddOne: vi.fn(),
  onEdit: vi.fn(),
  onDelete: vi.fn(),
  onSetThreshold: vi.fn(),
  consumingId: null,
  selectedIds: [],
  onToggleSelect: vi.fn(),
  onSelectAll: vi.fn(),
};

const cardProps = {
  storages: [],
  categories: [],
  onItemClick: vi.fn(),
  onConsume: vi.fn(),
  onSetThreshold: vi.fn(),
  onOpenActions: vi.fn(),
  consumingId: null,
  isSelected: false,
  onToggleSelect: vi.fn(),
  onSwipeDelete: vi.fn(),
};

describe("a partly used package, in the list", () => {
  it("table row: the remainder in kg, the full size beside it", async () => {
    useCatalogue();
    render(<ItemTable {...tableProps} items={[makeItem("0.750")]} />);

    expect(await screen.findByText("of 2 kg")).toBeInTheDocument();
    // What the button shows leads its name (label in name), the purpose follows;
    // jsdom joins the flex items without the space a browser puts between them.
    expect(
      screen.getByRole("button", { name: /^1\.5\s*kg\s*of 2 kg .*Flour/ }),
    ).toBeInTheDocument();
  });

  it("table row: a whole number of pieces reads as it did", async () => {
    useCatalogue();
    render(<ItemTable {...tableProps} items={[makeItem("3.000")]} />);

    expect(await screen.findByText("pcs.")).toBeInTheDocument();
    expect(screen.queryByText(/of 2 kg/)).toBeNull();
  });

  it("table row: a card with no weight or volume reads as it did", async () => {
    useCatalogue();
    render(<ItemTable {...tableProps} items={[makeItem("0.750", {})]} />);

    expect(await screen.findByText("pcs.")).toBeInTheDocument();
    expect(screen.queryByText(/kg/)).toBeNull();
  });

  it("mobile card: says the full sentence", async () => {
    useCatalogue();
    render(<ItemMobileCard item={makeItem("0.750")} {...cardProps} />);

    expect(await screen.findByText("1.5 kg left of 2 kg")).toBeInTheDocument();
  });

  it("mobile card reads in Polish", async () => {
    useCatalogue();
    await withLanguage("pl", async () => {
      render(<ItemMobileCard item={makeItem("0.750")} {...cardProps} />);
      expect(
        await screen.findByText("zostało 1,5 kg z 2 kg"),
      ).toBeInTheDocument();
    });
  });

  it("detail view: the quantity field reads the sentence", async () => {
    useCatalogue();
    render(
      <ItemDetailOverview
        item={makeItem("0.750")}
        storages={[]}
        categories={[]}
      />,
    );

    expect(await screen.findByText("1.5 kg left of 2 kg")).toBeInTheDocument();
  });
});

describe("a partly used package, in the scan sheet", () => {
  const scan = (quantity: number): LabelScanView =>
    ({
      status: "product_stock",
      label_code: "STM-0001",
      message_key: "scan:result.product",
      message_params: { product: "Flour" },
      action: "show_stock_actions",
      stock_summary: {
        total_quantity: quantity,
        unit: "pcs",
        template: {
          name: "Flour",
          uom_id: PCS,
          weight_value: 2,
          weight_uom_id: KG,
        },
        items: [
          { id: "item-1", expiry_date: null, location: "Pantry", quantity },
        ],
      },
    }) as LabelScanView;

  it("names the remainder against the full size", async () => {
    useCatalogue();
    render(
      <StockActionSheet
        data={scan(0.75)}
        onClose={vi.fn()}
        onConsume={vi.fn()}
        onAddOne={vi.fn()}
        onAdd={vi.fn()}
      />,
    );

    expect(
      (await screen.findAllByText("1.5 kg left of 2 kg")).length,
    ).toBeGreaterThan(0);
  });
});
