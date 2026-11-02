/**
 * DynamicField must render money, multi-select, and boolean
 * (in addition to the existing text/number/date/select/textarea types).
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { DynamicField } from "./DynamicFieldsCard";
import type { FieldDefinition } from "@/types";

const createWrapper = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
};

const moneyField: FieldDefinition = {
  key: "deposit",
  type: "money",
  label: "Deposit",
  default_currency: "EUR",
  visible: true,
  required: false,
  is_system: false,
};

const multiSelectField: FieldDefinition = {
  key: "allergens",
  type: "multi-select",
  label: "Allergens",
  options: ["Gluten", "Lactose"],
  visible: true,
  required: false,
  is_system: false,
};

const booleanField: FieldDefinition = {
  key: "lactose_free",
  type: "boolean",
  label: "Lactose free",
  visible: true,
  required: false,
  is_system: false,
};

describe("DynamicField — money, multi-select and boolean types", () => {
  it("renders money field with amount + currency", () => {
    render(
      <DynamicField
        field={moneyField}
        value={{ amount: "5.00", currency: "EUR" }}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByDisplayValue("5.00")).toBeInTheDocument();
    expect(screen.getByText("EUR")).toBeInTheDocument();
  });

  it("emits {amount, currency} when money changes", () => {
    const onChange = vi.fn();
    render(
      <DynamicField
        field={moneyField}
        value={{ amount: "", currency: "EUR" }}
        onChange={onChange}
      />,
      { wrapper: createWrapper() },
    );
    fireEvent.change(screen.getByRole("spinbutton"), {
      target: { value: "9.99" },
    });
    expect(onChange).toHaveBeenCalledWith({ amount: "9.99", currency: "EUR" });
  });

  it("renders multi-select with checkboxes", () => {
    render(
      <DynamicField
        field={multiSelectField}
        value={["Gluten"]}
        onChange={vi.fn()}
      />,
      { wrapper: createWrapper() },
    );
    expect(screen.getByText("Gluten")).toBeInTheDocument();
    expect(screen.getByText("Lactose")).toBeInTheDocument();
  });

  it("emits string[] when multi-select toggles", () => {
    const onChange = vi.fn();
    render(
      <DynamicField field={multiSelectField} value={[]} onChange={onChange} />,
      { wrapper: createWrapper() },
    );
    fireEvent.click(screen.getByText("Gluten"));
    expect(onChange).toHaveBeenCalledWith(["Gluten"]);
  });

  it("renders boolean as a checkbox", () => {
    const onChange = vi.fn();
    render(
      <DynamicField field={booleanField} value={false} onChange={onChange} />,
      { wrapper: createWrapper() },
    );
    const cb = screen.getByRole("checkbox");
    expect(cb).not.toBeChecked();
    fireEvent.click(cb);
    expect(onChange).toHaveBeenCalledWith(true);
  });
});
