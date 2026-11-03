import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { CookForStockModal } from "./CookForStockModal";
import { QueryWrapper } from "@/test/queryWrapper";

const mocks = vi.hoisted(() => ({
  places: [] as Array<{ id: string; name: string }>,
  // The places the stock scope still offers, by id; every named one unless a
  // spec says otherwise.
  offered: null as string[] | null,
  offer: {} as Record<string, unknown>,
  scope: vi.fn(),
  createMakerRecipeFromCulinary: vi.fn(),
  createProductionOrderFromBridge: vi.fn(),
  discardBridgeRecipe: vi.fn(),
  navigate: vi.fn(),
  productSelect: vi.fn(),
}));

// What the output picker offers is the server's answer (useLocationOffer, and
// whether the stock scope still offers the remembered place); the field
// itself is LocationCombobox,
// whose own spec drives the search. Here it is the plain combobox over the
// places a spec names, so the modal's flows run in one render.
vi.mock("@/hooks/queries/useLocations", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/queries/useLocations")>()),
  useLocationOffer: () => mocks.offer,
  useOfferedLocations: (ids: ReadonlyArray<string | null | undefined>) => ({
    data: ids.filter(
      (id): id is string =>
        !!id && (mocks.offered ?? mocks.places.map((p) => p.id)).includes(id),
    ),
    isLoading: false,
  }),
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

vi.mock("@/modules/maker/api/recipeBridge", () => ({
  createMakerRecipeFromCulinary: mocks.createMakerRecipeFromCulinary,
  createProductionOrderFromBridge: mocks.createProductionOrderFromBridge,
  discardBridgeRecipe: mocks.discardBridgeRecipe,
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return { ...actual, useNavigate: () => mocks.navigate };
});

// Lightweight stand-in: renders its own label (like the real component) and
// a selectable product button that calls onSelect.
vi.mock("@/modules/maker/components/ProductSearchInput", () => ({
  ProductSearchInput: ({
    onSelect,
    label,
  }: {
    onSelect: (p: unknown) => void;
    label?: string;
  }) => (
    <div>
      {label && <span>{label}</span>}
      <button
        type="button"
        data-testid="mock-product-option"
        onClick={() =>
          onSelect({ product_template_id: "tpl-jam", name: "Jam Jar" })
        }
      >
        Jam Jar
      </button>
    </div>
  ),
}));

// Expose the shortage state via a confirm button wired to onConfirm.
vi.mock("@/modules/maker/components/ShortageModal", () => ({
  ShortageModal: ({
    open,
    shortages,
    canConfirm,
    onConfirm,
    onCancel,
  }: {
    open: boolean;
    shortages: Array<{ child_template_name: string | null; shortage: string }>;
    canConfirm: boolean;
    onConfirm: () => void;
    onCancel: () => void;
  }) =>
    open ? (
      <div data-testid="shortage-modal">
        <span>{shortages[0]?.child_template_name}</span>
        {canConfirm && (
          <button
            type="button"
            data-testid="shortage-confirm"
            onClick={onConfirm}
          >
            confirm
          </button>
        )}
        <button type="button" onClick={onCancel}>
          cancel
        </button>
      </div>
    ) : null,
}));

// The slot hands the sheet the three fields it reads, not the recipe record.
const recipe = { id: "culinary-1", name: "Fruit Jam", servings: 6 };

const shortageWarning = {
  response: {
    status: 422,
    data: {
      detail: {
        error: "shortage_warning",
        shortages: [
          {
            child_template_id: "tpl-fruit",
            child_template_name: "Fruit",
            needed: "2.000000",
            available: "0",
            shortage: "2.000000",
            uom_symbol: "kg",
            convertible: true,
          },
        ],
      },
    },
  },
};

/** The location combobox trigger — it shows the pick or the placeholder. */
function storageTrigger() {
  return screen.getByRole("combobox", { name: "To location" });
}

/** Opens the location combobox and picks the option by its visible name. */
function pickStorage(name: string) {
  fireEvent.click(storageTrigger());
  // The trigger shows the current pick, so the name can appear twice: on the
  // trigger and in the list. The list is the one that was just opened.
  const matches = screen.getAllByText(name);
  fireEvent.click(matches[matches.length - 1]);
}

/** What the stock picker offers, as `useLocationOffer` answers it. */
function serveScopedStorages(list: Array<{ id: string; name: string }>) {
  mocks.places = list;
  mocks.offered = null;
  mocks.offer = {
    total: list.length,
    first: list.slice(0, 2),
    emptyReason: list.length === 0 ? "nothing-to-offer" : null,
    isError: false,
    error: null,
    refetch: vi.fn(),
  };
}

function renderModal(onClose: () => void = vi.fn()) {
  serveScopedStorages([{ id: "loc-1", name: "Output Store" }]);
  return render(
    <MemoryRouter>
      <CookForStockModal open onClose={onClose} recipe={recipe} />
    </MemoryRouter>,
  );
}

describe("CookForStockModal (cooking-to-stock bridge)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    serveScopedStorages([{ id: "loc-1", name: "Output Store" }]);
    mocks.createMakerRecipeFromCulinary.mockResolvedValue({
      id: "maker-recipe-1",
      name: "Fruit Jam",
      output_template_id: "tpl-jam",
      source_recipe_id: "culinary-1",
      lines: [],
      created: true,
    });
    mocks.discardBridgeRecipe.mockResolvedValue(undefined);
    mocks.createProductionOrderFromBridge.mockResolvedValue({
      id: "order-1",
      status: "DRAFT",
      output_template_id: "tpl-jam",
      planned_qty: "12.000",
      output_location_id: "loc-1",
      created_at: "2026-08-09T00:00:00Z",
    });
  });

  it("renders the product label exactly once (no duplicated label)", () => {
    renderModal();
    // ProductSearchInput already renders its own label via the `label` prop;
    // a hand-written label next to it duplicated "Output product".
    expect(screen.getAllByText("Output product")).toHaveLength(1);
  });

  it("disables submit until product, scale and storage are chosen", () => {
    renderModal();
    const submit = screen.getByTestId("cook-for-stock-submit");
    expect(submit).toBeDisabled();

    fireEvent.click(screen.getByTestId("mock-product-option"));
    fireEvent.change(screen.getByTestId("cook-for-stock-scale-input"), {
      target: { value: "2" },
    });
    pickStorage("Output Store");
    expect(submit).toBeEnabled();
  });

  it("shows planned output = servings × scale", () => {
    renderModal();
    expect(screen.getByTestId("cook-for-stock-planned-qty").textContent).toBe(
      "6",
    );
    fireEvent.change(screen.getByTestId("cook-for-stock-scale-input"), {
      target: { value: "3" },
    });
    expect(screen.getByTestId("cook-for-stock-planned-qty").textContent).toBe(
      "18",
    );
  });

  it("snapshots the culinary recipe and creates a DRAFT order (happy path)", async () => {
    renderModal();
    fireEvent.click(screen.getByTestId("mock-product-option"));
    fireEvent.change(screen.getByTestId("cook-for-stock-scale-input"), {
      target: { value: "2" },
    });
    pickStorage("Output Store");
    fireEvent.click(screen.getByTestId("cook-for-stock-submit"));

    await waitFor(() => {
      expect(mocks.createMakerRecipeFromCulinary).toHaveBeenCalledWith({
        source_recipe_id: "culinary-1",
        output_template_id: "tpl-jam",
        name: "Fruit Jam",
        batch_yield_qty: "6",
      });
      // planned_qty = servings(6) × scale(2)
      expect(mocks.createProductionOrderFromBridge).toHaveBeenCalledWith({
        output_template_id: "tpl-jam",
        recipe_id: "maker-recipe-1",
        planned_qty: "12",
        output_location_id: "loc-1",
        confirm_shortage: false,
      });
      expect(mocks.navigate).toHaveBeenCalledWith("/maker/production/order-1");
    });
  });

  it("reuses an existing snapshot recipe idempotently (backend returns same id)", async () => {
    renderModal();
    fireEvent.click(screen.getByTestId("mock-product-option"));
    pickStorage("Output Store");
    fireEvent.click(screen.getByTestId("cook-for-stock-submit"));

    await waitFor(() => {
      expect(mocks.createMakerRecipeFromCulinary).toHaveBeenCalledTimes(1);
      expect(mocks.createProductionOrderFromBridge).toHaveBeenCalledWith(
        expect.objectContaining({
          recipe_id: "maker-recipe-1",
          planned_qty: "6",
        }),
      );
    });
  });

  it("shows a shortage warning and re-posts with confirm_shortage", async () => {
    mocks.createProductionOrderFromBridge
      .mockRejectedValueOnce(shortageWarning)
      .mockResolvedValueOnce({
        id: "order-2",
        status: "DRAFT",
        output_template_id: "tpl-jam",
        planned_qty: "6.000",
        output_location_id: "loc-1",
        created_at: "2026-08-09T00:00:00Z",
      });

    renderModal();
    fireEvent.click(screen.getByTestId("mock-product-option"));
    pickStorage("Output Store");
    fireEvent.click(screen.getByTestId("cook-for-stock-submit"));

    await waitFor(() => {
      expect(screen.getByTestId("shortage-modal")).toBeTruthy();
    });
    fireEvent.click(screen.getByTestId("shortage-confirm"));

    await waitFor(() => {
      expect(mocks.createProductionOrderFromBridge).toHaveBeenCalledWith(
        expect.objectContaining({ confirm_shortage: true }),
      );
      expect(mocks.navigate).toHaveBeenCalledWith("/maker/production/order-2");
    });
  });

  describe("backing out of the bridge", () => {
    /**
     * The bridge builds two records in two calls: the snapshot, then the
     * order. When the second is refused and the operator walks away, the
     * first used to stay — a formula in the production catalogue that nobody
     * created on purpose and no screen mentioned.
     */
    async function refuseTheOrderAndLeave() {
      const onClose = vi.fn();
      mocks.createProductionOrderFromBridge.mockRejectedValue(shortageWarning);

      renderModal(onClose);
      fireEvent.click(screen.getByTestId("mock-product-option"));
      pickStorage("Output Store");
      fireEvent.click(screen.getByTestId("cook-for-stock-submit"));

      await waitFor(() => {
        expect(screen.getByTestId("shortage-modal")).toBeTruthy();
      });
      fireEvent.click(screen.getByText("cancel"));
      fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
      return onClose;
    }

    it("discards the snapshot it created when the order never happened", async () => {
      const onClose = await refuseTheOrderAndLeave();

      await waitFor(() => {
        expect(mocks.discardBridgeRecipe).toHaveBeenCalledWith(
          "maker-recipe-1",
        );
      });
      expect(onClose).toHaveBeenCalled();
    });

    it("keeps a snapshot that was already there", async () => {
      // The endpoint is idempotent: a second attempt on the same pair hands
      // back the first snapshot, which this attempt did not create and has
      // no business deleting.
      mocks.createMakerRecipeFromCulinary.mockResolvedValue({
        id: "maker-recipe-1",
        name: "Fruit Jam",
        output_template_id: "tpl-jam",
        source_recipe_id: "culinary-1",
        lines: [],
        created: false,
      });

      await refuseTheOrderAndLeave();

      expect(mocks.discardBridgeRecipe).not.toHaveBeenCalled();
    });
  });

  describe("target location", () => {
    beforeEach(() => {
      localStorage.clear();
    });

    /**
     * The field is required and stays required — the order's target location
     * column is not nullable, and a finished batch needs somewhere to land.
     * Requiring an answer is not the same as asking for one, and with a single
     * location in the organization there is only one answer to give.
     */
    it("starts on the only location there is", () => {
      renderModal();

      expect(storageTrigger()).toHaveTextContent("Output Store");
    });

    it("asks for a stock flow's places, so a batch never lands on a module's shelf", () => {
      mocks.scope.mockClear();
      serveScopedStorages([
        { id: "loc-1", name: "Output Store" },
        { id: "loc-2", name: "Cold Room" },
      ]);

      render(
        <MemoryRouter>
          <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
        </MemoryRouter>,
      );

      expect(mocks.scope).toHaveBeenCalledWith({ purpose: "stock" });
    });

    it("asks when there is a real choice to make", () => {
      serveScopedStorages([
        { id: "loc-1", name: "Output Store" },
        { id: "loc-2", name: "Cold Room" },
      ]);

      render(
        <MemoryRouter>
          <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
        </MemoryRouter>,
      );

      expect(storageTrigger()).toHaveTextContent(
        "Choose where the output goes",
      );
    });

    it("offers the location the last batch went to", () => {
      // The modal reads through the validated JSON pair, so the value a
      // previous instance left behind is the JSON shape.
      localStorage.setItem(
        "inventari:cookForStock:outputLocation",
        JSON.stringify("loc-2"),
      );
      serveScopedStorages([
        { id: "loc-1", name: "Output Store" },
        { id: "loc-2", name: "Cold Room" },
      ]);

      render(
        <MemoryRouter>
          <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
        </MemoryRouter>,
      );

      expect(storageTrigger()).toHaveTextContent("Cold Room");
    });

    it("offers to create the first location instead of an empty list", () => {
      // "No location matches" answers a search. An organization with none
      // has not searched for anything — and the way to fix that used to be
      // three screens away, with this sheet abandoned on the way.
      serveScopedStorages([]);

      render(
        <QueryWrapper>
          <MemoryRouter>
            <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
          </MemoryRouter>
        </QueryWrapper>,
      );

      expect(
        screen.queryByRole("combobox", { name: "To location" }),
      ).toBeNull();
      expect(
        screen.getByRole("button", { name: "Create location" }),
      ).toBeInTheDocument();
    });

    it("ignores a remembered location the stock flow no longer offers", () => {
      // The shelf still exists and is still internal, but it has since been
      // given to a module (equipment): naming it is not offering it.
      localStorage.setItem(
        "inventari:cookForStock:outputLocation",
        JSON.stringify("loc-eq"),
      );
      serveScopedStorages([
        { id: "loc-1", name: "Output Store" },
        { id: "loc-2", name: "Cold Room" },
        { id: "loc-eq", name: "Tool Shelf" },
      ]);
      mocks.offered = ["loc-1", "loc-2"];

      render(
        <MemoryRouter>
          <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
        </MemoryRouter>,
      );

      expect(storageTrigger()).toHaveTextContent(
        "Choose where the output goes",
      );
    });

    it("ignores a remembered location that no longer exists", () => {
      localStorage.setItem(
        "inventari:cookForStock:outputLocation",
        JSON.stringify("gone"),
      );
      serveScopedStorages([
        { id: "loc-1", name: "Output Store" },
        { id: "loc-2", name: "Cold Room" },
      ]);

      render(
        <MemoryRouter>
          <CookForStockModal open onClose={vi.fn()} recipe={recipe} />
        </MemoryRouter>,
      );

      expect(storageTrigger()).toHaveTextContent(
        "Choose where the output goes",
      );
    });
  });

  /** A read-only result styled as a field read as a second thing to fill in. */
  it("shows where the planned output came from", () => {
    renderModal();
    fireEvent.change(screen.getByTestId("cook-for-stock-scale-input"), {
      target: { value: "3" },
    });

    expect(screen.getByTestId("cook-for-stock-planned-qty").tagName).toBe("P");
    expect(screen.getByText(/6 per batch × 3/)).toBeInTheDocument();
  });
});
