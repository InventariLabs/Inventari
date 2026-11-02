import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, it, expect, vi } from "vitest";
import { ImportMappingStep } from "./ImportMappingStep";

describe("ImportMappingStep", () => {
  const mockProps = {
    file: new File(["test"], "test.xlsx"),
    headers: ["name", "quantity", "unit"],
    fields: [
      { key: "name", label: "Product name", required: true },
      { key: "quantity", label: "Quantity" },
      { key: "unit", label: "Unit" },
    ],
    mapping: { name: "name", quantity: "quantity", unit: "unit" },
    onMappingChange: vi.fn(),
  };

  it("renders file confirmation", () => {
    render(<ImportMappingStep {...mockProps} />);
    expect(screen.getByText(/File analyzed/)).toBeInTheDocument();
    expect(screen.getByText("test.xlsx")).toBeInTheDocument();
  });

  it("renders the fields it was given, marking the required one", () => {
    render(<ImportMappingStep {...mockProps} />);
    expect(screen.getByText("Product name")).toBeInTheDocument();
    expect(screen.getByText("Quantity")).toBeInTheDocument();
    expect(screen.getByText("*")).toBeInTheDocument();
  });

  it("renders select options with headers", () => {
    render(<ImportMappingStep {...mockProps} />);
    const selects = screen.getAllByRole("combobox");
    expect(selects).toHaveLength(3);
  });

  it("shows the first rows under the mapping, in the mapped columns", () => {
    // The step used to ask for a mapping and show no data at all, so a sheet
    // with a shifted header row looked correctly mapped and the mismatch
    // only turned up after the rows had been written.
    render(
      <ImportMappingStep
        {...mockProps}
        previewRows={[
          { name: "Mąka", quantity: 2, unit: "kg" },
          { name: "Cukier", quantity: 4, unit: "kg" },
        ]}
      />,
    );
    expect(screen.getByText("Mąka")).toBeInTheDocument();
    expect(screen.getByText("Cukier")).toBeInTheDocument();
    // Numbered as the refusals are: data rows from 1, no header counted.
    const rows = screen.getAllByRole("row");
    expect(rows[1]).toHaveTextContent("1");
  });

  it("shows no preview table when the server sent no rows", () => {
    render(<ImportMappingStep {...mockProps} />);
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("places the entity's extras beside the file name and under the grid", () => {
    render(
      <ImportMappingStep
        {...mockProps}
        headerExtras={<button type="button">Preset</button>}
      >
        <p>Only adds rows.</p>
      </ImportMappingStep>,
    );
    expect(screen.getByRole("button", { name: "Preset" })).toBeInTheDocument();
    expect(screen.getByText("Only adds rows.")).toBeInTheDocument();
  });

  it("reports the column the reader picks for a field, keeping the other fields as they were", async () => {
    const onMappingChange = vi.fn();
    render(
      <ImportMappingStep
        {...mockProps}
        mapping={{ name: "name", quantity: "", unit: "" }}
        onMappingChange={onMappingChange}
      />,
    );

    await userEvent.click(screen.getAllByRole("combobox")[1]);
    await userEvent.click(screen.getByRole("option", { name: "quantity" }));

    expect(onMappingChange).toHaveBeenCalledExactlyOnceWith({
      name: "name",
      quantity: "quantity",
      unit: "",
    });
  });

  it("clears a field's column when the reader picks 'skip'", async () => {
    const onMappingChange = vi.fn();
    render(
      <ImportMappingStep {...mockProps} onMappingChange={onMappingChange} />,
    );

    await userEvent.click(screen.getAllByRole("combobox")[2]);
    await userEvent.click(
      screen.getByRole("option", { name: "— Skip / default —" }),
    );

    expect(onMappingChange).toHaveBeenCalledExactlyOnceWith({
      name: "name",
      quantity: "quantity",
      unit: "",
    });
  });
});
