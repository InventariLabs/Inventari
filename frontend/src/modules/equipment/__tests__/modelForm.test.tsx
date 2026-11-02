/**
 * regression: a model is a reusable template.
 *
 * - The model form must not ask for per-unit fields (serial number,
 *   asset tag) and must offer a category.
 * - The model select label must not duplicate the brand.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@/test/utils";
import ModelEditModal from "@/modules/equipment/components/ModelEditModal";
import { formatModelDisplayName } from "@/modules/equipment/components/assetUtils";

describe(" model form", () => {
  it("does not render per-unit fields", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText("Serial Number")).not.toBeInTheDocument();
    expect(screen.queryByText("Asset Tag")).not.toBeInTheDocument();
  });

  it("does not point at an asset the model list does not have", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText(/for this asset/)).not.toBeInTheDocument();
    expect(
      screen.getByText("Save a reusable template for new assets."),
    ).toBeInTheDocument();
  });

  it("offers a category select", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getByLabelText("Category")).toBeInTheDocument();
  });

  it("does not ask for what belongs to one unit", () => {
    // Every asset built from a model inherited these, so a new laptop
    // arrived carrying somebody else's purchase date.
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText("Purchase Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Warranty Until")).not.toBeInTheDocument();
    expect(screen.queryByText("Status")).not.toBeInTheDocument();
    expect(
      screen.getByText(/belong to the individual asset/),
    ).toBeInTheDocument();
  });

  it("asks for the manufacturer once, not as brand and manufacturer", () => {
    render(
      <ModelEditModal
        isOpen
        model={null}
        isSubmitting={false}
        onSave={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.getAllByText("Manufacturer")).toHaveLength(1);
    expect(screen.queryByText("Brand")).not.toBeInTheDocument();
  });

  it("drops per-unit leftovers when an older model is saved", () => {
    const onSave = vi.fn();
    render(
      <ModelEditModal
        isOpen
        model={
          {
            id: "m-1",
            name: "Latitude 5540",
            brand: "Dell",
            description: null,
            category_id: null,
            equipment_meta: {
              model: "5540",
              purchase_date: "2024-01-01",
              equipment_status: "DEPLOYED",
              manufacturer: "Dell",
            },
          } as never
        }
        isSubmitting={false}
        onSave={onSave}
        onClose={vi.fn()}
      />,
    );

    fireEvent.submit(screen.getByRole("button", { name: "Save" }));

    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ equipment_meta: { model: "5540" } }),
    );
  });

  it("does not duplicate the brand in the display name", () => {
    expect(
      formatModelDisplayName({
        brand: "Dell",
        name: "Dell Latitude 5540 (standard)",
      }),
    ).toBe("Dell Latitude 5540 (standard)");
    expect(
      formatModelDisplayName({ brand: "Dell", name: "Latitude 5540" }),
    ).toBe("Dell Latitude 5540");
  });
});
