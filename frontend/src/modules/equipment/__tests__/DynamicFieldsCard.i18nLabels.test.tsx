import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import { DynamicField } from "../components/DynamicFieldsCard";
import type { FieldDefinition } from "@/types";

/**
 * Dynamic field labels come from the persisted English
 * literals — they must resolve through i18n.
 * Placeholders must not leak raw database keys.
 */

const textField = (overrides: Partial<FieldDefinition> = {}): FieldDefinition =>
  ({
    key: "serial_number",
    type: "text",
    label: "Serial Number",
    visible: true,
    required: false,
    is_system: false,
    ...overrides,
  }) as FieldDefinition;

const renderField = (field: FieldDefinition) =>
  render(<DynamicField field={field} value="" onChange={vi.fn()} />);

describe("DynamicField — i18n labels", () => {
  it("resolves the persisted English label through the i18n catalog", async () => {
    await withLanguage("pl", async () => {
      renderField(textField());
      // pl catalog: form.fields.serialNumber = "Numer seryjny".
      expect(screen.getByText("Numer seryjny")).toBeInTheDocument();
      expect(screen.queryByText("Serial Number")).not.toBeInTheDocument();
    });
  });

  it("falls back to the literal for org-defined custom fields", async () => {
    renderField(textField({ key: "custom_field", label: "My Custom Field" }));
    expect(screen.getByText("My Custom Field")).toBeInTheDocument();
  });
});

describe("DynamicField — placeholders", () => {
  it("does not leak the raw database key as a placeholder", () => {
    renderField(
      textField({ key: "ram_gb", label: "RAM (GB)", placeholder: null }),
    );
    const input = screen.getByRole("textbox");
    expect(input).toHaveAttribute("placeholder", "");
  });

  it("keeps an explicit placeholder when provided", () => {
    renderField(
      textField({ key: "ram_gb", label: "RAM (GB)", placeholder: "e.g. 16" }),
    );
    expect(screen.getByRole("textbox")).toHaveAttribute(
      "placeholder",
      "e.g. 16",
    );
  });
});
