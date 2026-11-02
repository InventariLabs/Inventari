import { beforeEach, describe, it, expect, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen, waitFor } from "@/test/utils";
import { serveLocations } from "@/test/serveLocations";
import ProductFormContent from "./ProductFormContent";
import type { FieldDefinition } from "@/types";

vi.mock("../UnifiedFieldRenderer", () => ({
  default: () => <div data-testid="renderer" />,
}));

const nameField: FieldDefinition = {
  key: "name",
  label: "Product name",
  type: "text",
  visible: true,
  required: true,
  is_system: false,
};

beforeEach(() => {
  serveLocations([{ id: "loc-1", name: "Shelf A" }]);
});

function renderForm(
  formData: Record<string, unknown>,
  onAddStorage?: (query: string) => void,
) {
  return render(
    <ProductFormContent
      formData={formData}
      onChange={vi.fn()}
      errors={{}}
      fieldDefinitions={[nameField]}
      onAddStorage={onAddStorage}
    />,
  );
}

describe("ProductFormContent — the row above the sections", () => {
  /**
   * The name used to carry a hand-written label while the storage picker drew
   * its own, so two fields side by side had two label voices and sat ~24px
   * apart. The control owns the label (UI_GUIDELINES §2.10); a label written
   * beside it is the thing that drifts.
   */
  it("names the product through the control, not a label beside it", () => {
    renderForm({ name: "" });

    const input = screen.getByLabelText(/product name/i);
    expect(input).toHaveAttribute("id");
    // The required mark travels on the control, never baked into the string.
    expect(input).toBeRequired();
    expect(screen.queryByText("Product name *")).not.toBeInTheDocument();
  });

  it("opens the chosen location in the mode the link promises", () => {
    // "Configure" used to open the location's product list, leaving the
    // person to find Edit themselves — while the target page already knew
    // how to open the sheet, through a parameter nobody passed.
    renderForm({ name: "", location_id: "loc-1" });

    expect(screen.getByRole("link", { name: /configure/i })).toHaveAttribute(
      "href",
      "/inventory/locations/loc-1?configure=true",
    );
  });

  it("falls back to the list, and says so, when nothing is chosen", () => {
    renderForm({ name: "" });

    const link = screen.getByRole("link", { name: /manage locations/i });
    expect(link).toHaveAttribute("href", "/inventory/locations");
  });

  // A place missing from the list used to be made on the Storages screen, in
  // another tab, and the form reloaded on return.
  it("offers a new location from the picker itself", async () => {
    const onAddStorage = vi.fn();
    renderForm({ name: "" }, onAddStorage);

    await userEvent.click(
      screen.getByRole("button", { name: /add new location/i }),
    );

    expect(onAddStorage).toHaveBeenCalledWith("");
  });

  it("carries a search that found nothing into the new location", async () => {
    const onAddStorage = vi.fn();
    renderForm({ name: "" }, onAddStorage);
    const underPicker = screen.getByRole("button", {
      name: /add new location/i,
    });

    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.type(
      screen.getByRole("textbox", { name: /search/i }),
      "Cold room",
    );
    // The panel's door, not the button under the picker — it opens once the
    // server has answered that nothing is called that.
    const doorOf = () =>
      screen
        .getAllByRole("button", { name: /add new location/i })
        .find((button) => button !== underPicker);
    await waitFor(() => expect(doorOf()).toBeDefined());
    await userEvent.click(doorOf() as HTMLElement);

    expect(onAddStorage).toHaveBeenCalledWith("Cold room");
  });

  // The product form sits inside a <form>; a button there without a type
  // is a submit, and this one saved a valid product instead of opening the
  // new location.
  it("asks for a new location without submitting the product", async () => {
    const onAddStorage = vi.fn();
    const onSubmit = vi.fn((event: React.FormEvent) => event.preventDefault());
    render(
      <form onSubmit={onSubmit}>
        <ProductFormContent
          formData={{ name: "Bolts", location_id: "loc-1" }}
          onChange={vi.fn()}
          errors={{}}
          fieldDefinitions={[nameField]}
          onAddStorage={onAddStorage}
        />
      </form>,
    );

    await userEvent.click(
      screen.getByRole("button", { name: /add new location/i }),
    );

    expect(onAddStorage).toHaveBeenCalledWith("");
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("offers no new location where the caller cannot make one", () => {
    renderForm({ name: "" });

    expect(
      screen.queryByRole("button", { name: /add new location/i }),
    ).not.toBeInTheDocument();
  });
});
