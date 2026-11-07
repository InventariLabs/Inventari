import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { toast } from "sonner";
import { withLanguage } from "@/test/mocks/i18n";
import FieldBuilder from "@/components/ui/FieldBuilder";
import type { FieldDefinition } from "@/types";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const sampleFields: FieldDefinition[] = [
  {
    key: "serial",
    label: "Serial Number",
    type: "text",
    required: false,
    is_system: false,
    visible: true,
    placeholder: null,
  },
];

describe("FieldBuilder", () => {
  it("renders toggle button", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    expect(screen.getByRole("button")).toBeInTheDocument();
  });

  it("opens the panel when toggle is clicked", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    const toggle = screen.getByRole("button");
    fireEvent.click(toggle);
    expect(screen.getByText("Add custom field")).toBeInTheDocument();
  });

  it("shows existing fields in the panel", () => {
    render(<FieldBuilder fields={sampleFields} onChange={vi.fn()} />);
    // Open the panel first
    fireEvent.click(screen.getByRole("button"));
    expect(screen.getByText("Serial Number")).toBeInTheDocument();
  });

  it("calls onChange when a field is removed", () => {
    const handleChange = vi.fn();
    render(<FieldBuilder fields={sampleFields} onChange={handleChange} />);
    // Open the panel
    fireEvent.click(screen.getAllByRole("button")[0]);

    // Find the remove button by its title attribute
    const removeBtn = screen.getByTitle("Delete");
    fireEvent.click(removeBtn);
    expect(handleChange).toHaveBeenCalled();
  });

  it("keeps a catalog-owned field's row locked — no delete, no edit", () => {
    const mixedFields: FieldDefinition[] = [
      {
        key: "cut_type",
        label: "Cut type",
        type: "text",
        required: false,
        visible: true,
        is_system: true,
      },
      {
        key: "note",
        label: "Note",
        type: "text",
        required: false,
        is_system: false,
        visible: true,
      },
    ];
    render(<FieldBuilder fields={mixedFields} onChange={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button")[0]);

    expect(screen.getByText("Cut type")).toBeInTheDocument();
    expect(
      screen.getByText(/Belongs to the product catalog/),
    ).toBeInTheDocument();

    // Only the user's own field offers deletion.
    expect(screen.getAllByTitle("Delete")).toHaveLength(1);

    // Clicking the locked row opens no edit form.
    fireEvent.click(screen.getByText("Cut type"));
    expect(screen.queryByDisplayValue("Cut type")).not.toBeInTheDocument();
  });

  it("names a catalog-owned field with the catalog's word in the reader's language", async () => {
    const fields: FieldDefinition[] = [
      {
        key: "asset_tag",
        // The words the seed stored, in the language the seeding ran in.
        label: "Asset Tag",
        type: "text",
        required: true,
        visible: true,
        is_system: true,
      },
    ];
    await withLanguage("pl", () => {
      render(<FieldBuilder fields={fields} onChange={vi.fn()} />);
      fireEvent.click(screen.getAllByRole("button")[0]);

      expect(screen.getByText("Numer inwentarzowy")).toBeInTheDocument();
      expect(screen.queryByText("Asset Tag")).not.toBeInTheDocument();
    });
  });

  it("lists no row for a visibility flag that declares no type", async () => {
    // A module's flag ({key, label, visible}) switches a built-in column on;
    // it is not a field the reader can edit, and its stored label is English
    // platform copy that no catalogue translates.
    const fields = [
      { key: "category_id", label: "Category", visible: true, is_system: true },
      ...sampleFields,
    ] as FieldDefinition[];
    await withLanguage("pl", () => {
      render(<FieldBuilder fields={fields} onChange={vi.fn()} />);
      fireEvent.click(screen.getAllByRole("button")[0]);

      expect(screen.getByText("Serial Number")).toBeInTheDocument();
      expect(screen.queryByText("Category")).not.toBeInTheDocument();
    });
  });

  it("leaves a user's own field named by the user's words, even when a catalog key matches", async () => {
    const fields: FieldDefinition[] = [
      {
        key: "asset_tag",
        label: "My own tag",
        type: "text",
        required: false,
        is_system: false,
        visible: true,
      },
    ];
    await withLanguage("pl", () => {
      render(<FieldBuilder fields={fields} onChange={vi.fn()} />);
      fireEvent.click(screen.getAllByRole("button")[0]);

      expect(screen.getByText("My own tag")).toBeInTheDocument();
      expect(screen.queryByText("Numer inwentarzowy")).not.toBeInTheDocument();
    });
  });

  it("lets a keyboard reach a locked row and hear why it is locked", () => {
    const fields: FieldDefinition[] = [
      {
        key: "asset_tag",
        label: "Asset Tag",
        type: "text",
        required: false,
        visible: true,
        is_system: true,
      },
    ];
    render(<FieldBuilder fields={fields} onChange={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button")[0]);

    const row = screen.getByRole("group", { name: "Asset Tag" });
    expect(row).toHaveAttribute("tabindex", "0");
    expect(row).toHaveAccessibleDescription(
      /Belongs to the product catalog — its name, type and requirement are fixed/,
    );
  });

  it("says nothing about a lock when no field is locked", () => {
    render(<FieldBuilder fields={sampleFields} onChange={vi.fn()} />);
    fireEvent.click(screen.getAllByRole("button")[0]);

    expect(
      screen.queryByText(/Belongs to the product catalog/),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("does not add a field when label is empty", () => {
    const handleChange = vi.fn();
    render(<FieldBuilder fields={[]} onChange={handleChange} />);
    fireEvent.click(screen.getAllByRole("button")[0]);

    // Click add without filling in label
    const addButton = screen
      .getAllByRole("button")
      .find(
        (btn) =>
          btn.textContent?.toLowerCase().includes("add") ||
          btn.getAttribute("data-testid") === "add-field",
      );
    if (addButton) {
      fireEvent.click(addButton);
      expect(handleChange).not.toHaveBeenCalled();
    }
  });

  it("exposes money, select, boolean and multi-select in the type dropdown", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByText("Add custom field"));

    const select = screen.getByDisplayValue("Text") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);

    expect(optionValues).toEqual(
      expect.arrayContaining(["money", "select", "boolean", "multi-select"]),
    );
  });

  it("shows the options editor when select type is chosen", () => {
    render(<FieldBuilder fields={[]} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByText("Add custom field"));

    fireEvent.change(screen.getByDisplayValue("Text"), {
      target: { value: "select" },
    });

    // The options editor renders its labelled header.
    expect(screen.getByText("Options")).toBeInTheDocument();
    // And the empty-state hint.
    expect(
      screen.getByText("At least one option is required"),
    ).toBeInTheDocument();
  });

  it("blocks adding a select field with no options", () => {
    const handleChange = vi.fn();
    render(<FieldBuilder fields={[]} onChange={handleChange} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByText("Add custom field"));

    // Fill label, switch to select, but add NO options.
    fireEvent.change(screen.getByPlaceholderText("e.g. Voltage"), {
      target: { value: "Color" },
    });
    fireEvent.change(screen.getByDisplayValue("Text"), {
      target: { value: "select" },
    });

    // The submit button reads "Add field" (fieldBuilder.addField).
    fireEvent.click(screen.getByText("Add field"));
    // optionsRequired guard fires toast.error and bails before onChange.
    expect(handleChange).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalled();
  });

  it("adds a select field when options are provided", () => {
    const handleChange = vi.fn();
    render(<FieldBuilder fields={[]} onChange={handleChange} />);
    fireEvent.click(screen.getByRole("button"));
    fireEvent.click(screen.getByText("Add custom field"));

    fireEvent.change(screen.getByPlaceholderText("e.g. Voltage"), {
      target: { value: "Color" },
    });
    fireEvent.change(screen.getByDisplayValue("Text"), {
      target: { value: "select" },
    });

    // Type an option and press Enter to add it.
    const optionInput = screen.getByPlaceholderText(
      "Add an option and press Enter",
    );
    fireEvent.change(optionInput, { target: { value: "Red" } });
    fireEvent.keyDown(optionInput, { key: "Enter" });

    fireEvent.click(screen.getByText("Add field"));
    expect(handleChange).toHaveBeenCalledTimes(1);
    const added = handleChange.mock.calls[0][0] as Array<{
      type: string;
      options?: string[];
    }>;
    expect(added[0].type).toBe("select");
    expect(added[0].options).toEqual(["Red"]);
  });
});

describe("FieldBuilder editing and the add form", () => {
  function openBuilder(onChange = vi.fn(), fields = sampleFields) {
    render(<FieldBuilder fields={fields} onChange={onChange} />);
    fireEvent.click(screen.getAllByRole("button")[0]);
    return onChange;
  }

  it("saves a renamed field and closes the edit form", () => {
    const onChange = openBuilder();

    fireEvent.click(screen.getByRole("button", { name: /Serial Number/ }));
    fireEvent.change(screen.getByDisplayValue("Serial Number"), {
      target: { value: "Serial No." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(onChange).toHaveBeenCalledTimes(1);
    const saved = onChange.mock.calls[0][0] as FieldDefinition[];
    expect(saved).toHaveLength(1);
    expect(saved[0]).toMatchObject({ key: "serial", label: "Serial No." });
    expect(screen.queryByDisplayValue("Serial No.")).not.toBeInTheDocument();
  });

  it("drops an edit on Cancel without telling the host anything changed", () => {
    const onChange = openBuilder();

    fireEvent.click(screen.getByRole("button", { name: /Serial Number/ }));
    fireEvent.change(screen.getByDisplayValue("Serial Number"), {
      target: { value: "Something else" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(onChange).not.toHaveBeenCalled();
    expect(
      screen.queryByDisplayValue("Something else"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Serial Number/ }),
    ).toBeInTheDocument();
  });

  it("closes the add form from its cross without adding anything", () => {
    const onChange = openBuilder(vi.fn(), []);
    fireEvent.click(screen.getByText("Add custom field"));
    const heading = screen.getByText("Add custom field", {
      selector: "span",
    });
    expect(screen.getByPlaceholderText("e.g. Voltage")).toBeInTheDocument();

    fireEvent.click(heading.parentElement!.querySelector("button")!);

    expect(
      screen.queryByPlaceholderText("e.g. Voltage"),
    ).not.toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("adds the field when Enter is pressed in the label, as a required one when switched on", () => {
    const onChange = openBuilder(vi.fn(), []);
    fireEvent.click(screen.getByText("Add custom field"));

    const label = screen.getByPlaceholderText("e.g. Voltage");
    fireEvent.change(label, { target: { value: "Voltage" } });
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.keyDown(label, { key: "Enter" });

    expect(onChange).toHaveBeenCalledTimes(1);
    const added = onChange.mock.calls[0][0] as FieldDefinition[];
    expect(added[0]).toMatchObject({
      key: "voltage",
      label: "Voltage",
      required: true,
    });
  });

  it("ignores Enter in an empty label", () => {
    const onChange = openBuilder(vi.fn(), []);
    fireEvent.click(screen.getByText("Add custom field"));

    fireEvent.keyDown(screen.getByPlaceholderText("e.g. Voltage"), {
      key: "Enter",
    });

    expect(onChange).not.toHaveBeenCalled();
  });

  it("keeps each option once however it is capitalised, and lets the reader remove one", () => {
    const onChange = openBuilder(vi.fn(), []);
    fireEvent.click(screen.getByText("Add custom field"));
    fireEvent.change(screen.getByPlaceholderText("e.g. Voltage"), {
      target: { value: "Color" },
    });
    fireEvent.change(screen.getByDisplayValue("Text"), {
      target: { value: "select" },
    });
    const optionInput = screen.getByPlaceholderText(
      "Add an option and press Enter",
    );
    for (const typed of ["Red", "red", "Blue"]) {
      fireEvent.change(optionInput, { target: { value: typed } });
      fireEvent.keyDown(optionInput, { key: "Enter" });
    }
    expect(optionInput).toHaveValue("");
    // Each chip's remove button says whose it is.
    expect(
      screen.getByRole("button", { name: "Remove option Blue" }),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove option Red" }));
    fireEvent.click(screen.getByText("Add field"));

    const added = onChange.mock.calls[0][0] as Array<{ options?: string[] }>;
    expect(added[0].options).toEqual(["Blue"]);
  });

  it("takes an option that was typed and not confirmed, instead of refusing the field", () => {
    const onChange = openBuilder(vi.fn(), []);
    fireEvent.click(screen.getByText("Add custom field"));
    fireEvent.change(screen.getByPlaceholderText("e.g. Voltage"), {
      target: { value: "Color" },
    });
    fireEvent.change(screen.getByDisplayValue("Text"), {
      target: { value: "select" },
    });
    fireEvent.change(
      screen.getByPlaceholderText("Add an option and press Enter"),
      { target: { value: "Red" } },
    );

    fireEvent.click(screen.getByText("Add field"));

    expect(toast.error).not.toHaveBeenCalled();
    const added = onChange.mock.calls[0][0] as Array<{ options?: string[] }>;
    expect(added[0].options).toEqual(["Red"]);
  });
});
