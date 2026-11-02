import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PageSaveProvider, usePageSave } from "@/module-sdk";
import { TaxRatesSection } from "./TaxRatesSection";

/** The page's Save, reduced to a button. */
function SaveHarness() {
  const { dirty, saveAll } = usePageSave();
  return (
    <button type="button" disabled={!dirty} onClick={() => void saveAll()}>
      page save
    </button>
  );
}

const fixtures = vi.hoisted(() => ({
  rates: [] as Array<Record<string, unknown>>,
  categories: [] as Array<{ category_id: string; tax_rate_id: string }>,
  offer: { country: "DE", rates: [] as Array<Record<string, unknown>> },
  canManage: true,
  offerFailed: false,
  api: {
    create: vi.fn(),
    update: vi.fn(),
    delete: vi.fn(),
    nameCategoryRate: vi.fn(),
  },
}));

vi.mock("@/modules/warehouse/api/taxRates", () => ({
  taxRatesApi: fixtures.api,
}));

vi.mock("@/modules/warehouse/hooks/useTaxRates", () => ({
  useTaxRates: () => ({ data: fixtures.rates, isError: false }),
  useCategoryTaxRates: () => ({ data: fixtures.categories, isError: false }),
  useCountryTaxRates: () =>
    fixtures.offerFailed
      ? { data: undefined, isError: true }
      : { data: fixtures.offer, isError: false },
}));

vi.mock("@/modules/shared/hooks/useCategories", () => ({
  useScopedCategories: () => {
    const categories = [
      { id: "cat-food", name: "Food" },
      { id: "cat-tools", name: "Tools" },
    ];
    return { all: categories, scoped: categories };
  },
}));

vi.mock("@/hooks/useCanWrite", () => ({
  useCanManage: () => fixtures.canManage,
}));

const renderSection = () =>
  render(
    <PageSaveProvider>
      <TaxRatesSection />
      <SaveHarness />
    </PageSaveProvider>,
  );

const standard = {
  id: "rate-19",
  name: "USt. 19%",
  rate: "19.00",
  is_default: false,
};

describe("TaxRatesSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fixtures.rates = [standard];
    fixtures.categories = [];
    fixtures.offer = {
      country: "DE",
      rates: [
        { name: "USt. 19%", rate: "19.00", is_standard: true },
        { name: "USt. 7%", rate: "7.00", is_standard: false },
      ],
    };
    fixtures.canManage = true;
    fixtures.offerFailed = false;
    fixtures.api.create.mockResolvedValue({ id: "rate-7" });
  });

  it("offers only the country's rates the table does not hold", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", { name: "Add the country's rates: 7%" }),
    );

    expect(screen.getByDisplayValue("USt. 19%")).toBeInTheDocument();
    expect(screen.getByDisplayValue("USt. 7%")).toBeInTheDocument();
    expect(screen.getByDisplayValue("7.00")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Add the country's rates/ }),
    ).not.toBeInTheDocument();
  });

  it("prints a fractional rate with its digits, in the offer and in a row's label", () => {
    fixtures.rates = [{ ...standard, id: "rate-55", name: "", rate: "5.50" }];
    fixtures.offer = {
      country: "FR",
      rates: [
        { name: "TVA 20%", rate: "20.00", is_standard: true },
        { name: "TVA 2,1%", rate: "2.10", is_standard: false },
      ],
    };
    renderSection();

    expect(
      screen.getByRole("button", {
        name: "Add the country's rates: 20%, 2.1%",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Remove the rate 5.5%" }),
    ).toBeInTheDocument();
  });

  it("writes a new rate before the category that names it", async () => {
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", { name: "Add the country's rates: 7%" }),
    );
    await user.click(screen.getByRole("button", { name: "Add a category" }));
    await user.selectOptions(screen.getByLabelText("Category"), "cat-food");
    await user.selectOptions(
      screen.getAllByRole("combobox").at(-1) as HTMLElement,
      "USt. 7%",
    );
    await user.click(screen.getByRole("button", { name: "page save" }));

    expect(fixtures.api.create).toHaveBeenCalledWith({
      name: "USt. 7%",
      rate: "7.00",
      is_default: false,
    });
    expect(fixtures.api.nameCategoryRate).toHaveBeenCalledWith(
      "cat-food",
      "rate-7",
    );
    expect(fixtures.api.update).not.toHaveBeenCalled();
  });

  it("deletes a removed rate and leaves its categories to the server", async () => {
    fixtures.categories = [{ category_id: "cat-food", tax_rate_id: "rate-19" }];
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", { name: "Remove the rate USt. 19%" }),
    );
    await user.click(screen.getByRole("button", { name: "page save" }));

    expect(fixtures.api.delete).toHaveBeenCalledWith("rate-19");
    // The deletion took the category's row with it.
    expect(fixtures.api.nameCategoryRate).not.toHaveBeenCalled();
  });

  it("clears a category's rate the reader removed", async () => {
    fixtures.categories = [{ category_id: "cat-food", tax_rate_id: "rate-19" }];
    const user = userEvent.setup();
    renderSection();

    await user.click(
      screen.getByRole("button", { name: "Remove the rate of Food" }),
    );
    await user.click(screen.getByRole("button", { name: "page save" }));

    expect(fixtures.api.nameCategoryRate).toHaveBeenCalledWith(
      "cat-food",
      null,
    );
    expect(fixtures.api.delete).not.toHaveBeenCalled();
  });

  it("offers no edits to a reader who cannot manage the settings", () => {
    fixtures.canManage = false;
    renderSection();

    expect(screen.queryByRole("button", { name: "Add a rate" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Remove the rate/ }),
    ).toBeNull();
  });

  it("offers no category row once every category names a rate", () => {
    fixtures.categories = [
      { category_id: "cat-food", tax_rate_id: "rate-19" },
      { category_id: "cat-tools", tax_rate_id: "rate-19" },
    ];
    renderSection();

    expect(
      screen.queryByRole("button", { name: "Add a category" }),
    ).not.toBeInTheDocument();
  });

  it("says the country's rates did not load, and still lets rates be added", () => {
    fixtures.offerFailed = true;
    renderSection();

    expect(
      screen.getByText(/The country's rates could not be loaded/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add a rate" })).toBeEnabled();
  });
});
