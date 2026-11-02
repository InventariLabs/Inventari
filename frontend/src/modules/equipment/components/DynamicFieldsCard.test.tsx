import { describe, it, expect, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { QueryWrapper as wrapper } from "@/test/queryWrapper";
import i18n from "@/i18n/config";
import type { CategoryDTO, FieldDefinition } from "@/types";
import { DynamicField, DynamicFieldsCard } from "./DynamicFieldsCard";

function field(overrides: Partial<FieldDefinition>): FieldDefinition {
  return {
    key: "custom",
    type: "text",
    label: "Custom",
    visible: true,
    required: false,
    is_system: false,
    ...overrides,
  } as FieldDefinition;
}

const statusField = field({
  key: "equipment_status",
  type: "select",
  label: "Status",
  options: ["AVAILABLE", "DEPLOYED", "MAINTENANCE", "RETIRED"],
});

function optionsOf(select: HTMLElement) {
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

/**
 * DEPLOYED and RETIRED are what a checkout and the guarded retire action
 * leave behind; a form that offered them would let a unit be "checked out"
 * to nobody. The failure caught: the status select offering a consequence
 * as a choice, or hiding the status a unit actually carries.
 */
describe("DynamicField — the asset status select", () => {
  it("offers only the statuses a person may set, in the reader's words", () => {
    render(<DynamicField field={statusField} value="" onChange={vi.fn()} />, {
      wrapper,
    });
    expect(optionsOf(screen.getByRole("combobox"))).toEqual([
      "Select…",
      "Available",
      "Maintenance",
    ]);
  });

  it("keeps a unit's current consequence status visible at the top", () => {
    render(
      <DynamicField field={statusField} value="DEPLOYED" onChange={vi.fn()} />,
      { wrapper },
    );
    expect(optionsOf(screen.getByRole("combobox"))).toEqual([
      "Select…",
      "Checked Out",
      "Available",
      "Maintenance",
    ]);
  });

  it("passes other selects' options through untouched", () => {
    const onChange = vi.fn();
    render(
      <DynamicField
        field={field({
          key: "os",
          type: "select",
          label: "OS",
          options: ["Linux", "RETIRED"],
        })}
        value=""
        onChange={onChange}
      />,
      { wrapper },
    );
    const select = screen.getByRole("combobox");
    expect(optionsOf(select)).toEqual(["Select…", "Linux", "RETIRED"]);
    fireEvent.change(select, { target: { value: "Linux" } });
    expect(onChange).toHaveBeenCalledWith("Linux");
  });
});

/**
 * Each field type hands its value back as the type the form stores. The
 * failure caught: an edit that never reaches the form state, so the saved
 * asset silently keeps the old value.
 */
describe("DynamicField — editing reaches the form", () => {
  it.each([
    ["text", "Asset note"],
    ["number", "42"],
    ["textarea", "Two\nlines"],
  ] as const)("a %s field reports what was typed", (type, typed) => {
    const onChange = vi.fn();
    render(
      <DynamicField
        field={field({ key: "custom_field", type, label: "Custom field" })}
        value=""
        onChange={onChange}
      />,
      { wrapper },
    );
    fireEvent.change(screen.getByLabelText("Custom field"), {
      target: { value: typed },
    });
    expect(onChange).toHaveBeenCalledWith(typed);
  });

  it("shows a stored value in the field and marks a required one", () => {
    render(
      <DynamicField
        field={field({
          key: "cost_centre",
          label: "Cost centre",
          required: true,
        })}
        value="CC-7"
        onChange={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByLabelText(/Cost centre/)).toHaveValue("CC-7");
    expect(screen.getByText("*")).toBeInTheDocument();
  });
});

describe("DynamicFieldsCard", () => {
  const t = i18n.getFixedT("en", "equipment");

  it("renders nothing when the category shows no fields", () => {
    const { container } = render(
      <DynamicFieldsCard
        visibleFields={[]}
        activeCategory={undefined}
        formDynamic={{}}
        onSetDynamic={vi.fn()}
        t={t}
      />,
      { wrapper },
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("titles the fields after the category and routes each edit to its own key", () => {
    const onSetDynamic = vi.fn();
    render(
      <DynamicFieldsCard
        visibleFields={[
          field({ key: "cpu", label: "CPU" }),
          field({ key: "ram", label: "RAM" }),
        ]}
        activeCategory={{ id: "cat-1", name: "Workstations" } as CategoryDTO}
        formDynamic={{ cpu: "i7" }}
        onSetDynamic={onSetDynamic}
        t={t}
      />,
      { wrapper },
    );
    expect(screen.getByText("Workstations")).toBeInTheDocument();
    expect(screen.getByLabelText("CPU")).toHaveValue("i7");

    fireEvent.change(screen.getByLabelText("RAM"), {
      target: { value: "32 GB" },
    });
    expect(onSetDynamic).toHaveBeenCalledWith("ram", "32 GB");
  });

  it("falls back to a generic title without a category", () => {
    render(
      <DynamicFieldsCard
        visibleFields={[field({ key: "cpu", label: "CPU" })]}
        activeCategory={undefined}
        formDynamic={{}}
        onSetDynamic={vi.fn()}
        t={t}
      />,
      { wrapper },
    );
    expect(screen.getByText("Details")).toBeInTheDocument();
  });
});
