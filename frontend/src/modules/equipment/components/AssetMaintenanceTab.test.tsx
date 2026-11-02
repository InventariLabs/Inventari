import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";

// The tab's network is not what this measures: the rows come back empty and
// the only question is whether the service state offers its way out.
vi.mock("@/modules/equipment/hooks/useEquipment", () => ({
  useItemMaintenanceLogs: () => ({
    data: [],
    isLoading: false,
    isError: false,
    error: null,
    refetch: vi.fn(),
  }),
  useDeleteMaintenanceLog: () => ({ mutate: vi.fn(), isPending: false }),
}));
vi.mock("@/hooks/useOrganizationCurrency", () => ({
  useOrganizationCurrency: () => "USD",
}));

import { render, screen } from "@/test/utils";
import { MaintenanceTab } from "./AssetMaintenanceTab";
import type { Item } from "@/types";

function makeItem(status: string | null): Item {
  return {
    id: "asset-1",
    name: "ThinkPad T14s",
    quantity: 1,
    metadata: { equipment: { equipment_status: status } },
  } as unknown as Item;
}

describe("MaintenanceTab — the way out of service", () => {
  it("offers End service on an asset that is in service", async () => {
    const onEndService = vi.fn();
    render(
      <MaintenanceTab
        item={makeItem("MAINTENANCE")}
        onAdd={() => {}}
        onEndService={onEndService}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: /end service/i }));

    expect(onEndService).toHaveBeenCalledTimes(1);
  });

  it("keeps the offer off an asset that is not in service", () => {
    render(
      <MaintenanceTab
        item={makeItem("AVAILABLE")}
        onAdd={() => {}}
        onEndService={vi.fn()}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /end service/i }),
    ).not.toBeInTheDocument();
  });

  it("does not offer a write to a reader", () => {
    render(
      <MaintenanceTab
        item={makeItem("MAINTENANCE")}
        onAdd={() => {}}
        onEndService={vi.fn()}
        canWrite={false}
      />,
    );

    expect(
      screen.queryByRole("button", { name: /end service/i }),
    ).not.toBeInTheDocument();
  });
});
