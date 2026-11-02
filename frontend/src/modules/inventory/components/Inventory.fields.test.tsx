import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { DateField } from "./FieldRenderers/DateField";
import { DefaultInputField } from "./FieldRenderers/DefaultInputField";
import { CategoryField } from "./FieldRenderers/CategoryField";
import { TextareaField } from "./FieldRenderers/TextareaField";
import { SelectField } from "./FieldRenderers/SelectField";
import { MoneyField } from "./FieldRenderers/MoneyFieldView";
import type { CategoryDTO, FieldDefinition, UomCategory } from "@/types";
import { withLanguage, default as i18n } from "@/test/mocks/i18n";

/** The translator SelectField receives as a prop in production. */
const tDynItems = (key: string, opts?: Record<string, unknown>): string =>
  i18n.t(key, { ns: "items", ...opts });

vi.mock("@/components/ui/SearchableCombobox", () => ({
  SearchableCombobox: ({
    value,
    onChange,
    placeholder,
  }: {
    value: string;
    onChange: (v: unknown) => void;
    placeholder: string;
  }) => (
    <button
      role="combobox"
      aria-label={placeholder}
      onClick={() => onChange("cat-1")}
    >
      {value || placeholder}
    </button>
  ),
}));

vi.mock("@/components/ui/Button", () => ({
  Button: (props: React.ButtonHTMLAttributes<HTMLButtonElement>) => (
    <button {...props} />
  ),
}));

const noop = vi.fn();

// ─── DateField ────────────────────────────────────────────────────────────────

const mockDateField: FieldDefinition = {
  key: "expiry_date",
  label: "items:expiryDate",
  type: "date",
  visible: true,
  required: false,
  is_system: false,
};

describe("DateField", () => {
  // The native date input is gone; the shared DateInput shows a
  // trigger formatted for the interface language and opens a panel.
  it("shows the date in the interface language", () => {
    render(
      <DateField field={mockDateField} value="2025-06-15" onChange={noop} />,
    );

    expect(screen.getByRole("combobox")).toHaveTextContent(/Jun 15, 2025/);
  });

  it("picks a date from the panel", () => {
    const onChange = vi.fn();
    render(
      <DateField
        field={mockDateField}
        value="2026-01-15"
        onChange={onChange}
      />,
    );

    fireEvent.click(screen.getByRole("combobox"));
    fireEvent.click(screen.getByRole("button", { name: /January 20, 2026/i }));

    expect(onChange).toHaveBeenCalledWith("2026-01-20");
  });

  // An expiry date offers intervals, not "−1Y"
  it("offers the presets this field declares", () => {
    render(
      <DateField
        field={{ ...mockDateField, date_presets: ["plus1Week", "plus1Month"] }}
        value=""
        onChange={noop}
      />,
    );

    fireEvent.click(screen.getByRole("combobox"));
    expect(screen.getAllByTestId("date-preset")).toHaveLength(2);
  });
});

// ─── DefaultInputField ────────────────────────────────────────────────────────

describe("DefaultInputField", () => {
  const textField: FieldDefinition = {
    key: "name",
    label: "items:name",
    type: "text",
    visible: true,
    required: true,
    is_system: false,
  };

  const numberField: FieldDefinition = {
    key: "quantity",
    label: "items:quantity",
    type: "number",
    visible: true,
    required: true,
    is_system: false,
  };

  it("renders a text input with current value", () => {
    render(
      <DefaultInputField
        field={textField}
        value="Test Product"
        onChange={noop}
      />,
    );
    expect(screen.getByDisplayValue("Test Product")).toBeInTheDocument();
  });

  it("renders a number input for numeric fields", () => {
    render(<DefaultInputField field={numberField} value={5} onChange={noop} />);
    const input = screen.getByDisplayValue("5");
    expect(input).toHaveAttribute("type", "number");
  });

  it("calls onChange when value changes", () => {
    const onChange = vi.fn();
    render(
      <DefaultInputField field={textField} value="" onChange={onChange} />,
    );
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "Milk" },
    });
    expect(onChange).toHaveBeenCalled();
  });

  /**
   * The calculated total under a per-piece weight used `toLocaleString` with
   * no locale — the browser's mark, not the interface language's. On a Polish
   * screen a browser set to English kept the dot.
   */
  it("writes the calculated total with the language's decimal mark", async () => {
    const weightField: FieldDefinition = {
      key: "weight",
      label: "items:weightPerPiece",
      type: "number",
      visible: true,
      required: false,
      is_system: false,
    };
    const categories: UomCategory[] = [
      {
        id: "cat-unit",
        name: "Unit",
        uoms: [
          {
            id: "uom-pcs",
            name: "Piece",
            symbol: "pcs",
            factor: "1",
            rounding: "1",
            is_reference: true,
            is_system: false,
            category_id: "cat-unit",
          },
        ],
      },
    ];

    await withLanguage("pl", () => {
      render(
        <DefaultInputField
          field={weightField}
          value={100}
          quantity={3}
          uomId="uom-pcs"
          uomCategories={categories}
          onChange={noop}
        />,
      );

      expect(screen.getByText(/≈ 300 g \(0,3 kg\)/)).toBeInTheDocument();
      expect(screen.queryByText(/\(0\.3 kg\)/)).not.toBeInTheDocument();
    });
  });

  it("renders MapPin icon for shelf_location field", () => {
    const shelfField: FieldDefinition = {
      key: "shelf_location",
      label: "items:shelfLocation",
      type: "text",
      visible: true,
      required: false,
      is_system: false,
    };
    const { container } = render(
      <DefaultInputField field={shelfField} value="" onChange={noop} />,
    );
    // MapPin SVG icon should be in DOM
    expect(container.querySelector("svg")).toBeInTheDocument();
  });
});

// ─── CategoryField ────────────────────────────────────────────────────────────

const mockCategories: CategoryDTO[] = [
  {
    is_active: true,
    is_module_owned: false,
    id: "cat-1",
    name: "Dairy",
    icon: "🥛",
    organization_id: "org-1",
    code: null,
    sort_order: 0,
    field_definitions: [],
    context_tag: null,
  },
  {
    is_active: true,
    is_module_owned: false,
    id: "cat-2",
    name: "Fruits",
    icon: "🍎",
    organization_id: "org-1",
    code: null,
    sort_order: 1,
    field_definitions: [],
    context_tag: null,
  },
];

describe("CategoryField", () => {
  it("renders the combobox with placeholder when no value", () => {
    render(
      <CategoryField value="" categories={mockCategories} onChange={noop} />,
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
  });

  it("calls onChange when a category is selected", () => {
    const onChange = vi.fn();
    render(
      <CategoryField
        value=""
        categories={mockCategories}
        onChange={onChange}
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    expect(onChange).toHaveBeenCalledWith("cat-1");
  });

  it("renders add-category button when onAddCategory is provided", () => {
    const onAdd = vi.fn();
    render(
      <CategoryField
        value=""
        categories={mockCategories}
        onChange={noop}
        onAddCategory={onAdd}
      />,
    );
    // The combobox + the add-category button both exist
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    const addBtn = screen.getByRole("button");
    fireEvent.click(addBtn);
    expect(onAdd).toHaveBeenCalled();
  });

  it("does NOT render add-category button when onAddCategory is absent", () => {
    render(
      <CategoryField value="" categories={mockCategories} onChange={noop} />,
    );
    // Only the combobox (role=combobox), no plain button
    expect(screen.queryByRole("button")).toBeNull();
  });
});

// ─── Accessible names ─────────────────────────────────────────────

/**
 * The visible label is rendered by UnifiedFieldRenderer, across a file
 * boundary the field-names gate cannot read — so each renderer carries the
 * accessible name itself, resolved from the same source the visible label
 * is rendered from (`getLabel`).
 */
describe("field renderers give their control an accessible name", () => {
  const systemField = (
    key: string,
    type: FieldDefinition["type"],
    extra: Partial<FieldDefinition> = {},
  ): FieldDefinition => ({
    key,
    label: key,
    is_system: true,
    type,
    visible: true,
    required: false,
    ...extra,
  });

  it("DefaultInputField names its input after the field's label", () => {
    render(
      <DefaultInputField
        field={systemField("purchase_price", "text")}
        value="12.50"
        onChange={noop}
      />,
    );
    expect(
      screen.getByRole("textbox", { name: "Purchase price per unit" }),
    ).toBeInTheDocument();
  });

  it("TextareaField names its textarea after the field's label", () => {
    render(
      <TextareaField
        field={systemField("manufacturer", "textarea")}
        value="Acme"
        commonClasses=""
        onChange={noop}
      />,
    );
    expect(
      screen.getByRole("textbox", { name: "Manufacturer" }),
    ).toBeInTheDocument();
  });

  it("SelectField names its select after the field's label", () => {
    render(
      <SelectField
        id="test-select"
        field={systemField("equipment_status", "select", {
          options: ["in_use"],
        })}
        value=""
        onChange={noop}
        tDyn={tDynItems}
      />,
    );
    expect(
      screen.getByRole("combobox", { name: "Status" }),
    ).toBeInTheDocument();
  });

  it("MoneyField names its amount input after the field's label", () => {
    render(
      <MoneyField
        field={systemField("purchase_price", "money")}
        value=""
        commonClasses=""
        onChange={noop}
      />,
    );
    expect(
      screen.getByRole("spinbutton", { name: "Purchase price per unit" }),
    ).toBeInTheDocument();
  });
});
