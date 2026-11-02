import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/mocks/server";
import { onePage } from "@/test/mocks/page";
import { QueryWrapper } from "@/test/queryWrapper";
import type { EquipmentModel } from "@/modules/equipment/api/equipment";

import ModelEditModal from "./ModelEditModal";

beforeEach(() => {
  server.use(
    http.get("/api/v1/categories", () =>
      HttpResponse.json(
        onePage([
          { id: "cat-lap", name: "Laptops", context_tag: "equipment" },
          { id: "cat-milk", name: "Dairy", context_tag: null },
        ]),
      ),
    ),
  );
});

const existing = {
  id: "model-1",
  name: "XPS 15",
  brand: "Dell",
  description: "High-end laptop",
  category_id: "cat-lap",
  image_url: null,
  equipment_meta: { model: "9530", group_tag: "DEV-KIT", serial_number: "x" },
} as unknown as EquipmentModel;

function renderModal(model: EquipmentModel | null, onSave = vi.fn()) {
  render(
    <QueryWrapper>
      <ModelEditModal
        isOpen
        model={model}
        isSubmitting={false}
        onSave={onSave}
        onClose={vi.fn()}
      />
    </QueryWrapper>,
  );
  return onSave;
}

/**
 * What the model editor hands to the save is the record: every field the
 * reader filled, trimmed, with empty metadata left out. The failures
 * caught: a field whose edit never reaches the payload, a category list
 * that offers the organization's grocery categories, and blank metadata
 * saved as empty strings that later read as "set".
 */
describe("ModelEditModal — what a save carries", () => {
  it("sends every field of a new model, with blank metadata left out", async () => {
    const user = userEvent.setup();
    const onSave = renderModal(null);

    await user.type(screen.getByLabelText(/^Name/), "  ThinkPad T14  ");
    await user.type(screen.getByLabelText("Manufacturer"), "Lenovo");
    await user.type(screen.getByLabelText("Description"), "Office laptop");
    await waitFor(() =>
      expect(screen.getByRole("option", { name: "Laptops" })).toBeVisible(),
    );
    expect(
      screen.queryByRole("option", { name: "Dairy" }),
    ).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Category"), "cat-lap");
    await user.type(screen.getByLabelText("Model number"), "Gen 4");
    await user.click(screen.getByRole("button", { name: "Create Model" }));

    expect(onSave).toHaveBeenCalledWith({
      name: "ThinkPad T14",
      brand: "Lenovo",
      description: "Office laptop",
      category_id: "cat-lap",
      equipment_meta: { model: "Gen 4" },
    });
  });

  it("starts from the record being edited and keeps per-unit keys out of the model", async () => {
    const user = userEvent.setup();
    const onSave = renderModal(existing);

    expect(screen.getByLabelText(/^Name/)).toHaveValue("XPS 15");
    expect(screen.getByLabelText("Group / Kit Tag")).toHaveValue("DEV-KIT");

    await user.clear(screen.getByLabelText("Group / Kit Tag"));
    await user.selectOptions(screen.getByLabelText("Category"), "");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith({
      name: "XPS 15",
      brand: "Dell",
      description: "High-end laptop",
      category_id: null,
      equipment_meta: { model: "9530" },
    });
  });

  it("will not save a model without a name", async () => {
    const user = userEvent.setup();
    const onSave = renderModal(null);

    await user.type(screen.getByLabelText(/^Name/), "   ");
    expect(screen.getByRole("button", { name: "Create Model" })).toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });
});
