import { render, screen } from "@/test/utils";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ValuationSection } from "./ValuationSection";
import type { ProductTemplate } from "@/lib/api/productTemplates";

// The one switch every stock-value surface reads.
const showInventoryValue = vi.hoisted(() => ({ current: true }));
vi.mock("@/modules/shared/hooks/useShowInventoryValue", () => ({
  useShowInventoryValue: () => showInventoryValue.current,
}));

vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (value: unknown) => `$${value}`,
}));

const template = { current_valuation_rate: 12.5 } as ProductTemplate;

function renderSection() {
  return render(
    <ValuationSection
      template={template}
      isLoading={false}
      uomSymbol="kg"
      hasTemplate
    />,
  );
}

/**
 * The average rate of the cost layers is a stock-value figure. The home
 * profile presets `stats.show_inventory_value` off, and the edit form kept
 * reading the layers back to a profile that keeps none.
 */
describe("ValuationSection — the value follows the profile's switch", () => {
  beforeEach(() => {
    showInventoryValue.current = true;
  });

  it("shows the average rate of the layers on hand where the value is on", () => {
    renderSection();

    expect(screen.getByText("Valuation")).toBeInTheDocument();
    expect(screen.getByText("$12.5")).toBeInTheDocument();
  });

  it("renders nothing where the profile does not show stock value", () => {
    showInventoryValue.current = false;
    const { container } = renderSection();

    expect(container).toBeEmptyDOMElement();
  });

  it("still renders nothing for a record with no template", () => {
    render(
      <ValuationSection
        template={template}
        isLoading={false}
        uomSymbol="kg"
        hasTemplate={false}
      />,
    );

    expect(screen.queryByText("Valuation")).toBeNull();
  });
});
