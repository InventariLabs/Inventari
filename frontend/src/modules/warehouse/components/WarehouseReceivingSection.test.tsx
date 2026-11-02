import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { PageSaveProvider, usePageSave } from "@/module-sdk";
import { WarehouseReceivingSection } from "./WarehouseReceivingSection";

/** The page's Save, reduced to a button: the section only registers its pick. */
function SaveHarness() {
  const { dirty, saveAll } = usePageSave();
  return (
    <button type="button" disabled={!dirty} onClick={() => void saveAll()}>
      page save
    </button>
  );
}

const renderSection = (canWrite: boolean) =>
  render(
    <PageSaveProvider>
      <WarehouseReceivingSection canWrite={canWrite} />
      <SaveHarness />
    </PageSaveProvider>,
  );

const fixtures = vi.hoisted(() => ({
  tree: [] as Array<{ id: string; name: string; children: unknown[] }>,
  modes: [] as Array<Record<string, unknown>>,
  failed: false,
  mutate: vi.fn(),
  asked: [] as unknown[][],
}));

vi.mock("@/hooks/queries/useStoragesTree", () => ({
  useStoragesTree: (...args: unknown[]) => (
    fixtures.asked.push(args),
    { data: fixtures.tree }
  ),
}));

vi.mock("@/modules/settings/hooks/useOrganization", () => ({
  useShowModuleData: () => true,
}));

vi.mock("@/modules/warehouse/hooks/usePutawayRules", () => ({
  useReceivingModes: () => ({
    data: fixtures.failed ? undefined : fixtures.modes,
    isError: fixtures.failed,
    error: fixtures.failed ? new Error("down") : null,
    refetch: vi.fn(),
  }),
  useSetReceivingMode: () => ({
    mutateAsync: fixtures.mutate,
    isPending: false,
  }),
}));

describe("WarehouseReceivingSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    fixtures.asked = [];
    fixtures.tree = [
      { id: "wh-main", name: "Main Warehouse", children: [] },
      { id: "wh-cold", name: "Cold Store", children: [] },
    ];
    fixtures.modes = [
      {
        warehouse_id: "wh-cold",
        two_step: true,
        receiving_location_id: "area-1",
        receiving_location_name: "Receiving",
      },
    ];
    fixtures.failed = false;
    fixtures.mutate.mockResolvedValue({});
  });

  it("reads only the warehouses, not the whole tree and no counts", () => {
    renderSection(true);

    expect(fixtures.asked.length).toBeGreaterThan(0);
    for (const [, options] of fixtures.asked) {
      expect(options).toMatchObject({ depth: 1, counts: false });
    }
  });

  it("shows each warehouse's choice, one step where none was made", () => {
    renderSection(true);

    expect(screen.getByLabelText("How Main Warehouse receives")).toHaveValue(
      "one",
    );
    expect(screen.getByLabelText("How Cold Store receives")).toHaveValue("two");
    expect(
      screen.getByText("Deliveries land in Receiving"),
    ).toBeInTheDocument();
  });

  it("holds a pick for the page's Save and writes it only then", async () => {
    renderSection(true);

    await userEvent.selectOptions(
      screen.getByLabelText("How Main Warehouse receives"),
      "Receive to a receiving area, put away later",
    );

    expect(fixtures.mutate).not.toHaveBeenCalled();
    expect(screen.getByLabelText("How Main Warehouse receives")).toHaveValue(
      "two",
    );

    await userEvent.click(screen.getByRole("button", { name: "page save" }));

    expect(fixtures.mutate).toHaveBeenCalledWith({
      warehouseId: "wh-main",
      twoStep: true,
    });
  });

  it("keeps a place per product by default and holds the switch for Save", async () => {
    fixtures.modes = [
      { warehouse_id: "wh-main", two_step: true, free_placement: false },
      {
        warehouse_id: "wh-cold",
        two_step: true,
        free_placement: true,
        receiving_location_id: "area-1",
        receiving_location_name: "Receiving",
      },
    ];
    renderSection(true);
    const main = screen.getByLabelText(
      "Each product has its own location in Main Warehouse",
    );
    const cold = screen.getByLabelText(
      "Each product has its own location in Cold Store",
    );
    expect(main).toBeChecked();
    expect(cold).not.toBeChecked();

    await userEvent.click(main);

    expect(fixtures.mutate).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "page save" }));
    // Only the choice that changed is sent; the mode stays as it was.
    expect(fixtures.mutate).toHaveBeenCalledWith({
      warehouseId: "wh-main",
      freePlacement: true,
    });
  });

  it("offers the choice only where goods are put away later", () => {
    renderSection(true);

    expect(
      screen.queryByLabelText(
        "Each product has its own location in Main Warehouse",
      ),
    ).toBeNull();
    expect(
      screen.getByLabelText("Each product has its own location in Cold Store"),
    ).toBeChecked();
  });

  it("is not dirty when the pick is put back to what is stored", async () => {
    renderSection(true);
    const select = screen.getByLabelText("How Main Warehouse receives");

    await userEvent.selectOptions(
      select,
      "Receive to a receiving area, put away later",
    );
    await userEvent.selectOptions(select, "one");

    expect(screen.getByRole("button", { name: "page save" })).toBeDisabled();
  });

  it("lets an account that cannot write read the choice but not change it", () => {
    renderSection(false);

    expect(screen.getByLabelText("How Cold Store receives")).toBeDisabled();
  });

  it("says so when the choices could not be read", () => {
    fixtures.failed = true;
    renderSection(true);

    expect(
      screen.getByText("Could not load how each location receives."),
    ).toBeInTheDocument();
  });

  it("is absent where there is no warehouse to choose for", () => {
    fixtures.tree = [];
    renderSection(true);

    expect(screen.queryByLabelText(/How .* receives/)).toBeNull();
  });
});
