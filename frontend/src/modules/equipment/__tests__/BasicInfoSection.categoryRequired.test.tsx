import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@/test/utils";
import { serveLocations } from "@/test/serveLocations";
import { BasicInfoSection } from "../components/BasicInfoSection";
import type { EquipmentFormData } from "../pages/AddEquipmentPage";
import type { CategoryDTO } from "@/types";

const form: EquipmentFormData = {
  name: "",
  category_id: "",
  location_id: "",
  barcode: "",
  label_code: "",
  purchase_price: "",
  purchase_date: "",
  warranty_until: "",
  notes: "",
  dynamic: {},
};

const categories = [
  {
    id: "cat-1",
    name: "Laptops",
    code: "LAPTOPS",
    is_active: true,
    is_module_owned: false,
    context_tag: "equipment",
    icon: null,
  },
] as unknown as CategoryDTO[];

const renderSection = (props: Record<string, unknown> = {}) =>
  render(
    <BasicInfoSection
      form={form}
      equipmentCategories={categories}
      showLabelCode={false}
      onSet={vi.fn()}
      onShowAddLocation={vi.fn()}
      {...props}
    />,
  );

describe("BasicInfoSection — the category the asset list needs", () => {
  it("marks the category required when there is one to pick", () => {
    // An asset saved without a category was invisible in its own module, and
    // the field carried no asterisk to warn anyone.
    renderSection({ categoryRequired: true });
    const select = screen.getByLabelText(/Category/);
    expect(select).toBeRequired();
  });

  it("leaves the category optional when the org has no equipment categories", () => {
    // Requiring it unconditionally would make the first asset uncreatable.
    renderSection({ categoryRequired: false, equipmentCategories: [] });
    expect(screen.getByLabelText(/Category/)).not.toBeRequired();
  });

  it("shows the category error next to the field", () => {
    renderSection({
      categoryRequired: true,
      fieldErrors: { category_id: "Category is required" },
    });
    expect(screen.getByRole("alert")).toHaveTextContent("Category is required");
  });
});

/**
 * The section owns no state: each control hands its value to the page
 * under its own form key. The failure caught: a control wired to the
 * wrong key, so a typed name or a picked location never reaches the save.
 */
describe("BasicInfoSection — every control reports under its own key", () => {
  it("routes name, category, location and barcode to the form", async () => {
    serveLocations([{ id: "loc-1", name: "Server Room" }]);
    const onSet = vi.fn();
    renderSection({ onSet });

    fireEvent.change(document.getElementById("equipment-name")!, {
      target: { value: "Dell Latitude" },
    });
    fireEvent.change(document.getElementById("equipment-category")!, {
      target: { value: "cat-1" },
    });
    fireEvent.click(document.getElementById("equipment-location")!);
    fireEvent.click(await screen.findByText("Server Room"));
    fireEvent.change(document.getElementById("equipment-barcode")!, {
      target: { value: "5901234123457" },
    });

    expect(onSet).toHaveBeenCalledWith("name", "Dell Latitude");
    expect(onSet).toHaveBeenCalledWith("category_id", "cat-1");
    expect(onSet).toHaveBeenCalledWith("location_id", "loc-1");
    expect(onSet).toHaveBeenCalledWith("barcode", "5901234123457");
  });

  it("asks the page for the quick location form", () => {
    const onShowAddLocation = vi.fn();
    renderSection({ onShowAddLocation });
    fireEvent.click(screen.getByRole("button", { name: "Add Location" }));
    expect(onShowAddLocation).toHaveBeenCalledTimes(1);
  });
});
