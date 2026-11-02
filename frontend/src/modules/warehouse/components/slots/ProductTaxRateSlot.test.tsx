import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import type { Item } from "@/types";
import ProductTaxRateSlot from "./ProductTaxRateSlot";

const fixtures = vi.hoisted(() => ({
  rates: [] as Array<{ id: string; name: string; rate: string }>,
  named: null as null | {
    product_template_id: string;
    tax_rate_id: string | null;
    category_tax_rate_id: string | null;
  },
  mutateAsync: vi.fn(),
  canManage: true,
}));

vi.mock("@/modules/warehouse/hooks/useTaxRates", () => ({
  useTaxRates: () => ({ data: fixtures.rates }),
  useProductTaxRate: () => ({ data: fixtures.named ?? undefined }),
  useNameProductTaxRate: () => ({
    mutateAsync: fixtures.mutateAsync,
    isPending: false,
  }),
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanManage: () => fixtures.canManage,
}));

const item = { id: "item-1", template_id: "tpl-bread" } as Item;

describe("ProductTaxRateSlot", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fixtures.rates = [
      { id: "rate-19", name: "USt. 19%", rate: "19.00" },
      { id: "rate-7", name: "USt. 7%", rate: "7.00" },
    ];
    fixtures.named = {
      product_template_id: "tpl-bread",
      tax_rate_id: null,
      category_tax_rate_id: "rate-7",
    };
    fixtures.canManage = true;
    fixtures.mutateAsync.mockResolvedValue({});
  });

  it("says which rate the product takes from its category", () => {
    render(<ProductTaxRateSlot data={{ item }} />);

    const select = screen.getByLabelText("Tax rate");
    expect(select).toHaveValue("");
    expect(
      screen.getByRole("option", { name: "From the category: USt. 7%" }),
    ).toBeInTheDocument();
  });

  it("saves the rate the moment it is picked", async () => {
    const user = userEvent.setup();
    render(<ProductTaxRateSlot data={{ item }} />);

    await user.selectOptions(screen.getByLabelText("Tax rate"), "rate-19");
    expect(fixtures.mutateAsync).toHaveBeenLastCalledWith("rate-19");
  });

  it("hands a product back to its category with a null", async () => {
    fixtures.named = {
      product_template_id: "tpl-bread",
      tax_rate_id: "rate-19",
      category_tax_rate_id: "rate-7",
    };
    const user = userEvent.setup();
    render(<ProductTaxRateSlot data={{ item }} />);

    await user.selectOptions(screen.getByLabelText("Tax rate"), "");
    expect(fixtures.mutateAsync).toHaveBeenLastCalledWith(null);
  });

  it("offers nothing while the organization keeps no rates", () => {
    fixtures.rates = [];
    const { container } = render(<ProductTaxRateSlot data={{ item }} />);

    expect(container).toBeEmptyDOMElement();
  });

  it("is read-only without the right to manage the settings", () => {
    fixtures.canManage = false;
    render(<ProductTaxRateSlot data={{ item }} />);

    expect(screen.getByLabelText("Tax rate")).toBeDisabled();
  });
});
