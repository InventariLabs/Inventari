import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import { LocationCombobox } from "./LocationCombobox";

const SHELVES = Array.from({ length: 300 }, (_, i) => ({
  id: `shelf-${i}`,
  name: `Shelf ${i}`,
  parent_id: "wh",
}));
const FLOOR = [{ id: "wh", name: "Warehouse", parent_id: null }, ...SHELVES];

function renderPicker(value = "") {
  const onChange = vi.fn();
  render(
    <QueryWrapper>
      <LocationCombobox
        label="To"
        value={value}
        onChange={onChange}
        scope={{ purpose: "stock" }}
      />
    </QueryWrapper>,
  );
  return onChange;
}

describe("LocationCombobox", () => {
  it("offers one page and finds the last of 300 shelves by asking the server", async () => {
    const requests = serveLocations(FLOOR);
    const onChange = renderPicker();

    fireEvent.click(screen.getByRole("combobox", { name: "To" }));
    await screen.findByText("Shelf 0");
    expect(screen.queryByText("Shelf 299")).not.toBeInTheDocument();
    expect(requests.every((r) => r.get("limit") === "30")).toBe(true);

    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Shelf 299" },
    });
    const row = await screen.findByText("Shelf 299");
    expect(requests.at(-1)?.get("q")).toBe("Shelf 299");

    fireEvent.click(row);
    expect(onChange).toHaveBeenCalledWith("shelf-299");
  });

  it("names a place that is not on the first page", async () => {
    serveLocations(FLOOR);
    renderPicker("shelf-250");

    await waitFor(() =>
      expect(screen.getByRole("combobox", { name: "To" })).toHaveTextContent(
        "Shelf 250",
      ),
    );
  });

  it("puts the way to a place under its name", async () => {
    serveLocations(FLOOR);
    renderPicker();

    fireEvent.click(screen.getByRole("combobox", { name: "To" }));
    const row = await screen.findByText("Shelf 0");
    expect(row.closest("button")).toHaveTextContent("Warehouse");
  });
});
