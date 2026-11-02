import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@/test/utils";
import userEvent from "@testing-library/user-event";
import { WarehouseSelect } from "./WarehouseSelect";
import type { StorageLocationNode } from "@/types";

const warehouses = [
  { id: "w-main", name: "Main Warehouse" },
  { id: "w-north", name: "North Warehouse" },
] as unknown as StorageLocationNode[];

describe("the warehouse selector", () => {
  it("lists every top-level location and the whole organization", () => {
    render(
      <WarehouseSelect
        warehouses={warehouses}
        value={null}
        onChange={vi.fn()}
      />,
    );

    const select = screen.getByRole("combobox", { name: "Location" });
    expect(select).toHaveValue("");
    expect(
      screen.getByRole("option", { name: "All locations" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "Main Warehouse" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("option", { name: "North Warehouse" }),
    ).toBeInTheDocument();
  });

  it("hands over the chosen place, and the whole organization back", async () => {
    const onChange = vi.fn();
    render(
      <WarehouseSelect
        warehouses={warehouses}
        value={null}
        onChange={onChange}
      />,
    );

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Location" }),
      "w-north",
    );
    expect(onChange).toHaveBeenLastCalledWith("w-north");

    await userEvent.selectOptions(
      screen.getByRole("combobox", { name: "Location" }),
      "",
    );
    expect(onChange).toHaveBeenLastCalledWith(null);
  });
});
