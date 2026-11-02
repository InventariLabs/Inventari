import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { ProductionCreateSheet } from "./ProductionCreateSheet";
import { QueryWrapper } from "@/test/queryWrapper";

const mocks = vi.hoisted(() => ({
  mutate: vi.fn(),
  madeMutate: vi.fn(),
  addMutate: vi.fn(),
  preview: { data: undefined as unknown, isFetching: false, error: null },
  offer: {} as Record<string, unknown>,
  places: [] as { id: string; name: string; path?: string }[],
  scope: vi.fn(),
  navigate: vi.fn(),
  settings: { reference_direction: "MARGIN" },
}));

// What the stock picker offers is the server's answer (useLocationOffer); the
// field itself is LocationCombobox, whose own spec drives the search. Here it
// is the plain combobox over the places a spec names, so the sheet's flows
// can be driven in one render.
vi.mock("@/hooks/queries/useLocations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/queries/useLocations")>()),
  useLocationOffer: () => mocks.offer,
}));
vi.mock("@/components/LocationCombobox", async () => {
  const { SearchableCombobox } =
    await import("@/components/ui/SearchableCombobox");
  return {
    LocationCombobox: ({
      scope,
      ...props
    }: { scope?: unknown } & Record<string, unknown>) => {
      mocks.scope(scope);
      return (
        <SearchableCombobox
          {...(props as unknown as import("react").ComponentProps<
            typeof SearchableCombobox
          >)}
          options={mocks.places as never}
        />
      );
    },
  };
});

vi.mock("@/modules/maker/hooks/useProduction", () => ({
  useCreateProductionOrder: () => ({ mutate: mocks.mutate }),
  useRecordMadeProduction: () => ({ mutate: mocks.madeMutate }),
  useAddShortagesToShoppingList: () => ({
    mutate: mocks.addMutate,
    isPending: false,
  }),
  useProductionPreview: () => mocks.preview,
}));

vi.mock("@/modules/maker/hooks/useRecipes", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("@/modules/maker/hooks/useRecipes")
  >()),
  useMakerSettings: () => ({ data: mocks.settings }),
}));

vi.mock("@/contexts/ModulesContext", () => ({
  useModules: () => ({ isModuleEnabled: () => true }),
}));
vi.mock("@/hooks/useCanWrite", () => ({
  useCanWrite: () => true,
  useCanManage: () => true,
}));
vi.mock("@/hooks/useMoney", () => ({
  useMoney: () => (amount: unknown) => `${Number(amount).toFixed(2)} zł`,
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mocks.navigate };
});

vi.mock("@/modules/maker/api/bom", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/modules/maker/api/bom")>();
  return {
    ...actual,
    bomApi: {
      ...actual.bomApi,
      templateIdsWithBom: vi.fn().mockResolvedValue({ template_ids: [] }),
    },
  };
});

// Heavy child sheets are irrelevant for the shortage flows.
vi.mock("./PricingCalculator", () => ({ PricingCalculator: () => null }));
vi.mock("./ProductionPreviewSheet", () => ({
  ProductionPreviewSheet: () => null,
}));

const shortageWarning = {
  response: {
    status: 422,
    data: {
      detail: {
        error: "shortage_warning",
        shortages: [
          {
            child_template_id: "tpl-flour",
            child_template_name: "Flour",
            needed: "5.000000",
            available: "0",
            shortage: "5.000000",
            uom_symbol: "kg",
            convertible: true,
          },
        ],
      },
    },
  },
};

const STORAGES = [
  { id: "loc-1", name: "Warehouse", path: "Site A" },
  { id: "loc-2", name: "Shelf B", path: "Receiving / Dock" },
];

/** What the stock picker has to offer, as `useLocationOffer` answers it. */
function offer(
  places: { id: string; name: string; path?: string }[],
  extra: Record<string, unknown> = {},
) {
  mocks.places = places;
  mocks.offer = {
    total: places.length,
    first: places.slice(0, 2),
    emptyReason: places.length === 0 ? "nothing-to-offer" : null,
    isError: false,
    error: null,
    refetch: vi.fn(),
    ...extra,
  };
}

function renderSheet() {
  offer(STORAGES);
  render(
    <QueryWrapper>
      <MemoryRouter>
        <ProductionCreateSheet
          open
          onClose={vi.fn()}
          preselectedProduct={{
            output_template_id: "tpl-bread",
            name: "Bread",
            recipe_id: "recipe-1",
          }}
        />
      </MemoryRouter>
    </QueryWrapper>,
  );
}

/** Switches the sheet to planning a run instead of recording one made. */
function planInstead() {
  fireEvent.click(screen.getByRole("radio", { name: "Planning to make" }));
}

function typeQuantity(value: string) {
  fireEvent.change(screen.getByTestId("maker-create-qty-input"), {
    target: { value },
  });
}

/** Opens the storage combobox and picks the option by its visible name. */
function pickStorage(name: string, query?: string) {
  fireEvent.click(screen.getByRole("combobox", { name: "To location" }));
  if (query !== undefined) {
    fireEvent.change(screen.getByPlaceholderText("Search by name or path…"), {
      target: { value: query },
    });
  }
  fireEvent.click(screen.getByText(name));
}

describe("ProductionCreateSheet — shortage strategy flows", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.navigate.mockReset();
    mocks.preview.data = undefined;
  });

  it("WARN: shows the shortage modal, then re-posts with confirm_shortage", () => {
    mocks.mutate.mockImplementation((payload, callbacks) => {
      if (!payload.confirm_shortage) {
        callbacks.onError(shortageWarning);
      } else {
        callbacks.onSuccess({ id: "order-1" });
      }
    });

    renderSheet();
    planInstead();
    typeQuantity("5");
    pickStorage("Warehouse");
    fireEvent.click(screen.getByTestId("maker-create-submit-button"));

    // First attempt: no confirm flag → backend warning → modal shown.
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(mocks.mutate.mock.calls[0][0].confirm_shortage).toBe(false);
    expect(screen.getByText("Some ingredients are short")).toBeInTheDocument();

    // Confirm → re-POST with confirm_shortage=true.
    fireEvent.click(screen.getByRole("button", { name: "Create anyway" }));
    expect(mocks.mutate).toHaveBeenCalledTimes(2);
    expect(mocks.mutate.mock.calls[1][0].confirm_shortage).toBe(true);
    expect(mocks.navigate).toHaveBeenCalledWith("/maker/production/order-1");
  });

  it("BLOCK: shows the danger modal and never creates the order", () => {
    mocks.mutate.mockImplementation((_payload, callbacks) => {
      callbacks.onError({
        response: {
          status: 422,
          data: {
            detail: {
              error: "shortage_blocked",
              shortages: shortageWarning.response.data.detail.shortages,
            },
          },
        },
      });
    });

    renderSheet();
    planInstead();
    typeQuantity("5");
    pickStorage("Warehouse");
    fireEvent.click(screen.getByTestId("maker-create-submit-button"));

    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(
      screen.getByText("Cannot create — ingredients missing"),
    ).toBeInTheDocument();
    // BLOCK offers no "Create anyway" action.
    expect(
      screen.queryByRole("button", { name: "Create anyway" }),
    ).not.toBeInTheDocument();

    // Closing the modal must not retry the create.
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(mocks.mutate).toHaveBeenCalledTimes(1);
    expect(mocks.navigate).not.toHaveBeenCalled();
  });
});

describe("ProductionCreateSheet — nowhere to put the batch", () => {
  it("keeps the picker on the form and offers to create the first location", () => {
    // The picker used to leave the form for a banner, which blocked the
    // module's only save path and left the footer hint asking for a control
    // that was not on the screen. The control stays; the way forward —
    // creating the first location without leaving the sheet — sits under it.
    offer([]);
    render(
      <QueryWrapper>
        <MemoryRouter>
          <ProductionCreateSheet
            open
            onClose={vi.fn()}
            preselectedProduct={{
              output_template_id: "tpl-bread",
              name: "Bread",
              recipe_id: "recipe-1",
            }}
          />
        </MemoryRouter>
      </QueryWrapper>,
    );

    expect(
      screen.getByRole("combobox", { name: "To location" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create location" }),
    ).toBeInTheDocument();
  });

  it("names the module-data switch when the existing locations are hidden, and still offers to create one", () => {
    // Every location the organization has belongs to a module, so the scoped
    // picker is empty while the flat list is not. The note names the setting
    // that keeps them out and links to it; creating a new location stays the
    // primary way to finish the order.
    offer([], { emptyReason: "module-data-hidden" });
    render(
      <QueryWrapper>
        <MemoryRouter>
          <ProductionCreateSheet
            open
            onClose={vi.fn()}
            preselectedProduct={{
              output_template_id: "tpl-bread",
              name: "Bread",
              recipe_id: "recipe-1",
            }}
          />
        </MemoryRouter>
      </QueryWrapper>,
    );

    expect(
      screen.getByRole("combobox", { name: "To location" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/belong to a module/i)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create location" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /open settings/i }),
    ).toBeInTheDocument();
  });

  it("asks for a stock flow's set, so the empty note never blames the switch", () => {
    // Every location the organization has belongs to a module, so the scoped
    // picker is empty while the flat list is not. This flow hides those
    // places with its own purpose — the switch would reveal nothing in this
    // sheet — so the note under the picker names the way out that works:
    // create a location, right here.
    mocks.scope.mockClear();
    offer([]);
    render(
      <QueryWrapper>
        <MemoryRouter>
          <ProductionCreateSheet
            open
            onClose={vi.fn()}
            preselectedProduct={{
              output_template_id: "tpl-bread",
              name: "Bread",
              recipe_id: "recipe-1",
            }}
          />
        </MemoryRouter>
      </QueryWrapper>,
    );

    expect(mocks.scope).toHaveBeenCalledWith({ purpose: "stock" });
    expect(
      screen.getByRole("combobox", { name: "To location" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Create location" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /open settings/i }),
    ).not.toBeInTheDocument();
  });
});

describe("ProductionCreateSheet — target location picker", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.navigate.mockReset();
  });

  it("narrows the list by the location path, not just its name", () => {
    mocks.madeMutate.mockImplementation((_payload, callbacks) =>
      callbacks.onSuccess({ id: "order-2" }),
    );

    renderSheet();
    typeQuantity("2");
    pickStorage("Shelf B", "receiving");
    fireEvent.click(screen.getByTestId("maker-create-submit-button"));

    expect(mocks.madeMutate.mock.calls[0][0].output_location_id).toBe("loc-2");
  });

  it("asks for a stock flow's places, so a module's racks are never offered", () => {
    // The walkthrough was offered the equipment module's server racks as the
    // place to put plum butter, with the organization showing module data in
    // its lists. The picker is asked with the stock purpose, which keeps a
    // module's places out whatever the lists mix.
    mocks.scope.mockClear();

    renderSheet();

    expect(mocks.scope).toHaveBeenCalledWith({ purpose: "stock" });
  });

  it("takes the only warehouse location without asking", () => {
    offer([STORAGES[0]]);
    mocks.madeMutate.mockImplementation((_payload, callbacks) =>
      callbacks.onSuccess({ id: "order-3" }),
    );
    render(
      <QueryWrapper>
        <MemoryRouter>
          <ProductionCreateSheet
            open
            onClose={vi.fn()}
            preselectedProduct={{
              output_template_id: "tpl-bread",
              name: "Bread",
              recipe_id: "recipe-1",
            }}
          />
        </MemoryRouter>
      </QueryWrapper>,
    );
    typeQuantity("2");
    fireEvent.click(screen.getByTestId("maker-create-submit-button"));

    expect(mocks.madeMutate.mock.calls[0][0].output_location_id).toBe("loc-1");
  });
});

describe("ProductionCreateSheet — one action in the footer", () => {
  it("leaves cancel and the create CTA in the footer, tools in the body", () => {
    renderSheet();
    const footer = screen.getByTestId("maker-create-footer");

    expect(
      within(footer).getByTestId("maker-create-submit-button"),
    ).toBeInTheDocument();
    expect(within(footer).getAllByRole("button")).toHaveLength(2);

    // The two inspection tools still exist — just not competing with the CTA.
    expect(
      within(footer).queryByTestId("maker-create-preview-button"),
    ).not.toBeInTheDocument();
    expect(
      within(footer).queryByTestId("maker-create-pricing-button"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("maker-create-preview-button"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("maker-create-pricing-button"),
    ).toBeInTheDocument();
  });
});

describe("ProductionCreateSheet — remaining preview requirements", () => {
  it("asks only for the location when the product and quantity are ready", () => {
    renderSheet();
    typeQuantity("1");
    expect(
      screen.getByText("Select a target location to enable preview."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Pick an output product to enable preview."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Enter a planned quantity greater than zero to enable preview.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("maker-create-preview-button")).toBeDisabled();
  });

  it("tracks a missing quantity and location separately as the fields change", () => {
    renderSheet();
    const quantity = screen.getByTestId("maker-create-qty-input");
    fireEvent.change(quantity, { target: { value: "0" } });
    expect(
      screen.getByText(
        "Enter a planned quantity greater than zero to enable preview.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Select a target location to enable preview."),
    ).toBeInTheDocument();
    pickStorage("Warehouse");
    expect(
      screen.queryByText("Select a target location to enable preview."),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(
        "Enter a planned quantity greater than zero to enable preview.",
      ),
    ).toBeInTheDocument();
    fireEvent.change(quantity, { target: { value: "2" } });
    expect(screen.queryByText(/to enable preview\./)).not.toBeInTheDocument();
    expect(screen.getByTestId("maker-create-preview-button")).toBeEnabled();
    fireEvent.change(quantity, { target: { value: "" } });
    expect(
      screen.getByText(
        "Enter a planned quantity greater than zero to enable preview.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByTestId("maker-create-preview-button")).toBeDisabled();
  });

  it("asks only for the product after the selected product is cleared", () => {
    renderSheet();
    typeQuantity("1");
    pickStorage("Warehouse");
    fireEvent.click(screen.getByRole("button", { name: "Change" }));
    expect(
      screen.getByText("Pick an output product to enable preview."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("Select a target location to enable preview."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText(
        "Enter a planned quantity greater than zero to enable preview.",
      ),
    ).not.toBeInTheDocument();
    expect(screen.getByTestId("maker-create-preview-button")).toBeDisabled();
  });
});

const PLUM_PREVIEW = {
  output_template_id: "tpl-bread",
  planned_qty: "20",
  planned_uom_symbol: "kg",
  total_cost: "150.00",
  entries: [],
  missing_cost_lines: [],
  recipe_state: "has_lines",
  recipe_id: "recipe-1",
  batch_yield_qty: "1",
  fixed_cost: "9.00",
  unit_cost: "7.9500",
  reference_price: "18.00",
  result_per_unit: "10.05",
  has_shortage: true,
  ingredients: [
    {
      child_template_id: "tpl-plums",
      child_template_name: "Damson Plums",
      needed: "22",
      available: "18",
      shortage: "4",
      uom_symbol: "kg",
      convertible: true,
    },
    {
      child_template_id: "tpl-sugar",
      child_template_name: "Cane Sugar",
      needed: "9",
      available: "25",
      shortage: "0",
      uom_symbol: "kg",
      convertible: true,
    },
  ],
};

describe("ProductionCreateSheet — already made, in one step", () => {
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.madeMutate.mockReset();
    mocks.addMutate.mockReset();
    mocks.navigate.mockReset();
    mocks.preview.data = PLUM_PREVIEW;
  });

  it("records the run as made by default, in the product's unit", () => {
    mocks.madeMutate.mockImplementation((_payload, callbacks) =>
      callbacks.onSuccess({ id: "order-9" }),
    );
    renderSheet();
    typeQuantity("20");
    pickStorage("Warehouse");

    expect(screen.getByText("kg")).toBeInTheDocument();
    expect(
      screen.getByText(
        "One batch of the BOM makes 1 kg. Enter what came out, not the number of batches.",
      ),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Save as made" }));

    expect(mocks.mutate).not.toHaveBeenCalled();
    expect(mocks.madeMutate).toHaveBeenCalledTimes(1);
    const payload = mocks.madeMutate.mock.calls[0][0];
    expect(payload.planned_qty).toBe("20");
    expect(payload.recipe_id).toBe("recipe-1");
    expect(payload).not.toHaveProperty("production_date");
    expect(mocks.navigate).toHaveBeenCalledWith("/maker/production/order-9");
  });

  it("shows need, have and short before saving, and says the shortfall gets counted", () => {
    renderSheet();
    typeQuantity("20");
    pickStorage("Warehouse");
    const needs = screen.getByTestId("maker-create-needs");

    expect(within(needs).getByText("Comes off stock")).toBeInTheDocument();
    expect(
      within(needs).getByText("18 kg in stock, 4 kg short"),
    ).toBeInTheDocument();
    expect(within(needs).getByText("25 kg in stock")).toBeInTheDocument();
    expect(
      within(needs).getByText("Costs you 7.95 zł per kg · 159.00 zł in total"),
    ).toBeInTheDocument();
    expect(
      within(needs).getByText(
        "You sell at 18.00 zł, which leaves 10.05 zł on each kg you make.",
      ),
    ).toBeInTheDocument();
    expect(within(needs).getByText(/put up for a count/)).toBeInTheDocument();
    expect(
      within(needs).queryByTestId("maker-create-add-shortfall"),
    ).not.toBeInTheDocument();
  });

  it("calls the reference price the shop's when the result is savings", () => {
    // The reference price is the shop price for a savings organization; the
    // sentence said "You sell at 18.00 zł" to someone who sells nothing.
    mocks.settings = { reference_direction: "SAVINGS" };
    try {
      renderSheet();
      typeQuantity("20");
      pickStorage("Warehouse");
      const needs = screen.getByTestId("maker-create-needs");

      expect(
        within(needs).getByText(
          "In a shop it costs 18.00 zł; each kg you make saves 10.05 zł.",
        ),
      ).toBeInTheDocument();
      expect(within(needs).queryByText(/You sell at/)).not.toBeInTheDocument();
    } finally {
      mocks.settings = { reference_direction: "MARGIN" };
    }
  });

  it("plans the run for a day and offers the shortfall to the shopping list", () => {
    mocks.mutate.mockImplementation((_payload, callbacks) =>
      callbacks.onSuccess({ id: "order-10" }),
    );
    renderSheet();
    planInstead();
    typeQuantity("20");
    pickStorage("Warehouse");

    const add = screen.getByRole("button", {
      name: "Add 4 kg of Damson Plums to the shopping list",
    });
    fireEvent.click(add);
    expect(mocks.addMutate.mock.calls[0][0]).toMatchObject({
      output_template_id: "tpl-bread",
      planned_qty: "20",
      output_location_id: "loc-1",
    });

    fireEvent.click(screen.getByRole("button", { name: "Plan the run" }));
    expect(mocks.madeMutate).not.toHaveBeenCalled();
    expect(mocks.mutate.mock.calls[0][0].production_date).toMatch(
      /^\d{4}-\d{2}-\d{2}$/,
    );
  });

  it("says when nothing is short", () => {
    mocks.preview.data = {
      ...PLUM_PREVIEW,
      has_shortage: false,
      ingredients: [PLUM_PREVIEW.ingredients[1]],
    };
    renderSheet();
    typeQuantity("20");
    pickStorage("Warehouse");

    expect(screen.getByText("Everything is in stock.")).toBeInTheDocument();
  });
});

describe("ProductionCreateSheet — nothing to make it from", () => {
  // The button must not offer what the server refuses: a product with no
  // BOM is refused in both modes (no recipe to plan from), a BOM that lists
  // no ingredients only when saved as made — the run would put output on
  // the shelf against zero consumption. A planned draft of it is accepted;
  // its completion refuses until ingredients are added.
  beforeEach(() => {
    mocks.mutate.mockReset();
    mocks.madeMutate.mockReset();
  });

  it("does not offer Save as made for a product with no BOM, and says why", () => {
    mocks.preview.data = {
      ...PLUM_PREVIEW,
      recipe_state: "no_recipe",
      recipe_id: null,
      ingredients: [],
    };
    renderSheet();
    typeQuantity("1");
    pickStorage("Warehouse");

    const save = screen.getByRole("button", { name: "Save as made" });
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription("Needs a BOM first");
    planInstead();
    expect(screen.getByRole("button", { name: "Plan the run" })).toBeDisabled();
  });

  it("does not offer Save as made for a BOM that lists no ingredients, and says why", () => {
    mocks.preview.data = {
      ...PLUM_PREVIEW,
      recipe_state: "empty",
      ingredients: [],
      has_shortage: false,
    };
    renderSheet();
    typeQuantity("1");
    pickStorage("Warehouse");

    const save = screen.getByRole("button", { name: "Save as made" });
    expect(save).toBeDisabled();
    expect(save).toHaveAccessibleDescription(
      "Add ingredients to the BOM first",
    );
    fireEvent.click(save);
    expect(mocks.madeMutate).not.toHaveBeenCalled();
  });

  it("still plans a run on a BOM with no ingredients yet", () => {
    mocks.preview.data = {
      ...PLUM_PREVIEW,
      recipe_state: "empty",
      ingredients: [],
      has_shortage: false,
    };
    renderSheet();
    planInstead();
    typeQuantity("1");
    pickStorage("Warehouse");

    const plan = screen.getByRole("button", { name: "Plan the run" });
    expect(plan).toBeEnabled();
    expect(plan).not.toHaveAccessibleDescription();
  });
});
