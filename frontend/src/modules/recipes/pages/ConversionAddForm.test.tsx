import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import i18n from "@/i18n/config";
import type { UnitConversionCreate } from "@/modules/recipes/types/nutrition-defaults";
import { ConversionAddForm, categoryLabel } from "./ConversionAddForm";

const t = i18n.getFixedT("en", "recipes");

/** Holds the form state the page would, and exposes it for assertions. */
function Harness({
  onAdd,
  onCancel,
  seen,
}: {
  onAdd: () => void;
  onCancel: () => void;
  seen: (form: Partial<UnitConversionCreate>) => void;
}) {
  const [form, setForm] = useState<Partial<UnitConversionCreate>>({});
  seen(form);
  return (
    <ConversionAddForm
      form={form}
      onFormChange={setForm}
      onAdd={onAdd}
      onCancel={onCancel}
      t={t}
    />
  );
}

const setup = () => {
  const onAdd = vi.fn();
  const onCancel = vi.fn();
  let latest: Partial<UnitConversionCreate> = {};
  render(
    <Harness
      onAdd={onAdd}
      onCancel={onCancel}
      seen={(f) => {
        latest = f;
      }}
    />,
  );
  return { onAdd, onCancel, form: () => latest };
};

describe("categoryLabel", () => {
  it("uses the translation when there is one", () => {
    expect(categoryLabel(t, "dry")).toBe("Dry goods");
  });

  it("falls back to the raw category when it is not translated", () => {
    expect(categoryLabel(t, "spices")).toBe("spices");
  });
});

/**
 * The "add a unit conversion" row. Each input must write its own field of the
 * draft, and only that field; the page sends the draft as typed.
 */
describe("ConversionAddForm", () => {
  it("writes each input to its own field and keeps the others", () => {
    const { form } = setup();
    fireEvent.change(screen.getByLabelText("Ingredient key (e.g. flour)"), {
      target: { value: "flour" },
    });
    fireEvent.change(
      screen.getByLabelText("Display name (e.g. Flour, wheat)"),
      {
        target: { value: "Flour, wheat" },
      },
    );
    fireEvent.change(screen.getByLabelText("Source unit (e.g. cup)"), {
      target: { value: "cup" },
    });
    fireEvent.change(screen.getByLabelText("Metric quantity"), {
      target: { value: "120" },
    });
    fireEvent.change(screen.getByLabelText("Metric unit"), {
      target: { value: "ml" },
    });
    fireEvent.change(screen.getByLabelText("Category"), {
      target: { value: "fat" },
    });
    expect(form()).toEqual({
      ingredient_key: "flour",
      ingredient_name: "Flour, wheat",
      source_unit: "cup",
      metric_quantity: 120,
      metric_unit: "ml",
      category: "fat",
    });
  });

  it("starts on grams and dry goods when the draft says nothing", () => {
    setup();
    expect(screen.getByLabelText("Metric unit")).toHaveValue("g");
    expect(screen.getByLabelText("Category")).toHaveValue("dry");
  });

  it("offers every category, translated", () => {
    setup();
    const options = Array.from(
      (screen.getByLabelText("Category") as HTMLSelectElement).options,
    ).map((o) => o.textContent);
    expect(options).toEqual(["Dry goods", "Liquids", "Fats", "Other"]);
  });

  it("adds and cancels through its own buttons", () => {
    const { onAdd, onCancel } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Add conversion" }));
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(onCancel).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
