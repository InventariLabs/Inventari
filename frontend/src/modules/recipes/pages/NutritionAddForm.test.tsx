import { describe, it, expect, vi } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import i18n from "@/i18n/config";
import type { IngredientDefaultCreate } from "@/modules/recipes/types/nutrition-defaults";
import { NutritionAddForm } from "./NutritionAddForm";

vi.mock("@/modules/recipes/pages/NutritionLabelScan", () => ({
  NutritionLabelScan: ({
    onRead,
  }: {
    onRead: (values: Partial<IngredientDefaultCreate>) => void;
  }) => (
    <button onClick={() => onRead({ protein_g: 7, fat_g: 3 })}>
      scan label
    </button>
  ),
}));

const t = i18n.t.bind(i18n);

function Harness({
  initial = {},
  isPending = false,
  canScanLabel = false,
  onAdd,
  onCancel,
  seen,
}: {
  initial?: Partial<IngredientDefaultCreate>;
  isPending?: boolean;
  canScanLabel?: boolean;
  onAdd: () => void;
  onCancel: () => void;
  seen: (form: Partial<IngredientDefaultCreate>) => void;
}) {
  const [form, setForm] = useState(initial);
  seen(form);
  return (
    <NutritionAddForm
      form={form}
      isPending={isPending}
      canScanLabel={canScanLabel}
      onFormChange={setForm}
      onAdd={onAdd}
      onCancel={onCancel}
      t={t}
    />
  );
}

const setup = (props: Partial<Parameters<typeof Harness>[0]> = {}) => {
  const onAdd = vi.fn();
  const onCancel = vi.fn();
  let latest: Partial<IngredientDefaultCreate> = {};
  render(
    <Harness
      onAdd={onAdd}
      onCancel={onCancel}
      seen={(f) => {
        latest = f;
      }}
      {...props}
    />,
  );
  return { onAdd, onCancel, form: () => latest };
};

/**
 * The "add a nutrition override" form: the name and seven figures per 100 g.
 * A cleared figure must become "no value", not zero, and a label scan must
 * fill only what the label carried.
 */
describe("NutritionAddForm", () => {
  it("writes the name and a figure to the draft", () => {
    const { form } = setup();
    fireEvent.change(screen.getByLabelText("Ingredient name"), {
      target: { value: "Butter" },
    });
    fireEvent.change(screen.getByLabelText("Fat (g)"), {
      target: { value: "81.5" },
    });
    expect(form()).toEqual({ name: "Butter", fat_g: 81.5 });
  });

  it("turns a cleared figure back into no value instead of zero", () => {
    const { form } = setup({ initial: { protein_g: 12 } });
    fireEvent.change(screen.getByLabelText("Protein (g)"), {
      target: { value: "" },
    });
    expect(form().protein_g).toBeUndefined();
  });

  it("keeps a typed zero, which is a value", () => {
    const { form } = setup();
    fireEvent.change(screen.getByLabelText("Fat (g)"), {
      target: { value: "0" },
    });
    expect(form().fat_g).toBe(0);
  });

  it("offers the label scan only where it is available", () => {
    setup();
    expect(screen.queryByText("scan label")).not.toBeInTheDocument();
  });

  it("merges a label reading into the draft without wiping what was typed", () => {
    const { form } = setup({
      canScanLabel: true,
      initial: { name: "Butter", calories_kcal: 717 },
    });
    fireEvent.click(screen.getByText("scan label"));
    expect(form()).toEqual({
      name: "Butter",
      calories_kcal: 717,
      protein_g: 7,
      fat_g: 3,
    });
  });

  it("saves and cancels through its own buttons", () => {
    const { onAdd, onCancel } = setup();
    fireEvent.click(screen.getByRole("button", { name: "Save" }));
    expect(onAdd).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("cannot be saved twice while the first save is pending", () => {
    setup({ isPending: true });
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});
