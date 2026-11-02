import React from "react";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";
import { describe, it, expect } from "vitest";
import UnifiedFieldRenderer from "./UnifiedFieldRenderer";
import type { FieldDefinition } from "@/types";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>
    <BrowserRouter>{children}</BrowserRouter>
  </QueryClientProvider>
);

const custom = (
  key: string,
  type: FieldDefinition["type"],
  extra: Partial<FieldDefinition> = {},
): FieldDefinition => ({
  key,
  type,
  label: `Field ${key}`,
  visible: true,
  required: true,
  is_system: false,
  is_custom: true,
  ...extra,
});

const FIELDS: [string, FieldDefinition][] = [
  ["text", custom("a_text", "text")],
  ["number", custom("a_number", "number")],
  ["textarea", custom("a_textarea", "textarea")],
  ["select", custom("a_select", "select", { options: ["M6", "M8"] })],
  ["date", custom("a_date", "date")],
  ["money", custom("a_money", "money", { default_currency: "EUR" })],
  [
    "multi-select",
    custom("a_multi", "multi-select", { options: ["nuts", "milk"] }),
  ],
  ["boolean", custom("a_bool", "boolean")],
  ["weight", custom("weight", "number", { is_custom: false, label: "Weight" })],
];

describe("UnifiedFieldRenderer — an invalid field says so once", () => {
  it.each(FIELDS)("a %s field prints its message once", (_name, field) => {
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[field]}
        formData={{}}
        onChange={() => {}}
        errors={{ [field.key]: "Required" }}
      />,
      { wrapper },
    );

    expect(screen.getAllByText("Required")).toHaveLength(1);
  });

  it("marks an errored select invalid and links its message to it", () => {
    const field = FIELDS[3][1];
    render(
      <UnifiedFieldRenderer
        fieldDefinitions={[field]}
        formData={{}}
        onChange={() => {}}
        errors={{ [field.key]: "Required" }}
      />,
      { wrapper },
    );

    const select = screen.getByRole("combobox");
    expect(select).toHaveAttribute("aria-invalid", "true");
    const message = screen.getByText("Required");
    expect(select.getAttribute("aria-describedby")).toContain(message.id);
  });
});
