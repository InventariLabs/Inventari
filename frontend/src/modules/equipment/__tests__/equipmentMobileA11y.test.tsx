/**
 * Mobile + a11y regressions.
 *
 * - The Export button on the asset list dropped its label below `sm:`,
 *   leaving an icon-only button with no accessible name (WCAG 4.1.2).
 * - "Select all" was a 16 px tap target (WCAG 2.5.8 minimum: 24 px).
 * - "Fleet Valuation" forced three columns at 390 px, so 85 px columns
 *   held 101 px of text.
 * - Name / Barcode / Label Code / both date fields had `<label>` elements
 *   with no `htmlFor` and inputs with no `id`, so the labels were not
 *   programmatically associated (labels[0] === null).
 */
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { http, HttpResponse } from "msw";
import { render, screen, waitFor } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { signInWith, signOut } from "@/test/auth";
import { withModules } from "@/test/moduleList";
import { FleetValuationWidget } from "@/modules/equipment/components/FleetValuationWidget";
import { BasicInfoSection } from "@/modules/equipment/components/BasicInfoSection";
import { PurchaseNotesSection } from "@/modules/equipment/components/PurchaseNotesSection";
import AssetListPage from "@/modules/equipment/pages/AssetListPage";
import type { EquipmentFormData } from "@/modules/equipment/pages/AddEquipmentPage";

// These pages hide their write actions from an account that cannot write,
// so a spec about the actions has to say who is looking at them.
beforeEach(() => {
  withModules("equipment");
  signInWith([
    "equipment:read",
    "equipment:write",
    "items:read",
    "locations:read",
    "locations:write",
    "categories:read",
    "categories:write",
  ]);
});

afterEach(() => {
  signOut();
});

vi.mock("@/hooks/useModulePageHeader", () => ({
  useModulePageHeader: () => ({ setHeader: vi.fn() }),
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const emptyForm: EquipmentFormData = {
  name: "",
  category_id: "",
  location_id: "",
  barcode: "",
  label_code: "",
  purchase_price: "",
  purchase_date: "",
  warranty_until: "",
  notes: "",
  dynamic: {},
};

const mockItem = (i: number) => ({
  id: `item-${i}`,
  name: `Asset ${i}`,
  brand: "Dell",
  barcode: `barcode-${i}`,
  status: "ACTIVE",
  category_id: "cat-1",
  location_id: "loc-1",
  context_tag: "equipment",
  created_at: "2024-01-01T00:00:00Z",
  updated_at: "2024-01-01T00:00:00Z",
  metadata: { equipment: { status: "AVAILABLE" } },
});

const mockValuation = {
  total_purchase_value: 5000,
  total_book_value: 3500,
  total_depreciation: 1500,
  by_category: [],
  asset_count: 3,
  depreciable_count: 3,
};

describe(" mobile + a11y regressions", () => {
  it("select-all keeps a touch target of at least 24 px", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [mockItem(1), mockItem(2)],
          total: 2,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    render(<AssetListPage />);

    // The merged page renders the table on desktop and cards on
    // mobile; both carry a select-all control. Wait for the table's
    // checkbox (24 px touch target) and assert its size class.
    await waitFor(() => {
      expect(
        screen.getByRole("checkbox", { name: /select all/i }),
      ).toBeInTheDocument();
    });
    const selectAll = screen.getByRole("checkbox", { name: /select all/i });
    expect(selectAll.className).toContain("h-6");
  });

  it("fleet valuation totals stack on narrow screens", async () => {
    server.use(
      http.get("/api/v1/equipment/valuation", () =>
        HttpResponse.json(mockValuation),
      ),
    );
    const { container } = render(<FleetValuationWidget />);

    await waitFor(() => {
      expect(screen.getByText("Fleet Valuation")).toBeInTheDocument();
    });
    const grid = container.querySelector(
      '[class*="grid-cols-1"][class*="sm:grid-cols-3"]',
    );
    expect(grid).not.toBeNull();
  });

  it("basic info fields expose programmatically associated labels", () => {
    render(
      <BasicInfoSection
        form={emptyForm}
        equipmentCategories={[]}
        onSet={vi.fn()}
        onShowAddLocation={vi.fn()}
      />,
    );

    expect(screen.getByLabelText(/Name/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Category/)).toBeInTheDocument();
    expect(screen.getByLabelText(/^Location/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Barcode/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Label \/ QR Code/)).toBeInTheDocument();
  });

  it("purchase and warranty date fields expose associated labels", () => {
    render(<PurchaseNotesSection form={emptyForm} onSet={vi.fn()} />);

    expect(screen.getByLabelText("Purchase Date")).toBeInTheDocument();
    expect(screen.getByLabelText("Warranty Until")).toBeInTheDocument();
  });
});

describe("status filter chips", () => {
  it("gives the status chips a mobile touch target", async () => {
    server.use(
      http.get("/api/v1/equipment/assets", () =>
        HttpResponse.json({
          items: [mockItem(1)],
          total: 1,
          offset: 0,
          limit: 50,
          has_more: false,
        }),
      ),
    );
    render(<AssetListPage />);

    await waitFor(() => {
      expect(screen.getByTestId("filter-all")).toBeInTheDocument();
    });

    // Measured at 390 px before the fix: 26 px tall, below the 44 px the
    // rest of the app uses below `md:` (Button `h-11 md:h-10`).
    for (const key of ["all", "AVAILABLE", "DEPLOYED", "MAINTENANCE"]) {
      const chip = screen.getByTestId(`filter-${key}`);
      expect(chip.className).toContain("h-11");
      expect(chip.className).toContain("md:h-7");
    }
  });
});
