import type { ComponentProps } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import userEvent from "@testing-library/user-event";
import type { StorageType } from "@/types";
import { MemoryRouter } from "react-router-dom";
import { StorageEditFields } from "./StorageEditFields";
import { tFor } from "@/test/mocks/i18n";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";
import type { StorageEditFormData } from "@/modules/spaces/hooks/useStorageEditForm";

const storageTypesData: StorageType[] = [];

const formData: StorageEditFormData = {
  name: "Kitchen Shelf",
  description: "",
  location_details: "",
  parent_id: null,
  location_type_id: null,
  context_schema: [],
  field_definitions: [],
  short_code: "KS1",
  label_show_description: true,
  is_reserve: false,
};

function renderFields(
  typesError?: unknown,
  extra: Partial<ComponentProps<typeof StorageEditFields>> = {},
) {
  return render(
    <QueryWrapper>
      <MemoryRouter>
        <StorageEditFields
          formData={formData}
          setFormData={vi.fn()}
          storageTypes={storageTypesData}
          typesError={typesError}
          onRetryTypes={vi.fn()}
          locationId="me"
          isGeneratingCode={false}
          onGenerateCode={vi.fn()}
          onQrDownload={vi.fn()}
          insideCount={0}
          t={tFor("locations")}
          {...extra}
        />
      </MemoryRouter>
    </QueryWrapper>,
  );
}

describe("StorageEditFields — neutral base fields", () => {
  it("does not render any food-biased tracking fields", () => {
    renderFields();
    expect(screen.queryByText("Freeze Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Expiry Date")).not.toBeInTheDocument();
    expect(screen.queryByText("Brand")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Production Date / Batch"),
    ).not.toBeInTheDocument();
  });

  it("renders the neutral toggleable fields", () => {
    renderFields();
    expect(screen.getByText("Product code")).toBeInTheDocument();
    expect(screen.getByText("Price")).toBeInTheDocument();
    expect(screen.getByText("Notes")).toBeInTheDocument();
    expect(screen.getByText("Shelf / position")).toBeInTheDocument();
  });

  it("lets a shelf say it is reserve stock for pick faces", () => {
    const setFormData = vi.fn();
    renderFields(undefined, { setFormData });
    const reserve = screen.getByRole("checkbox", { name: "Reserve location" });
    expect(reserve).not.toBeChecked();
    reserve.click();
    expect(setFormData).toHaveBeenCalledWith({
      ...formData,
      is_reserve: true,
    });
  });

  it("keeps the product fields on a location that also holds locations", () => {
    // A warehouse's own products record the same fields a shelf's do. The
    // fields used to be hidden unless the location had no children.
    renderFields();
    expect(screen.getByText("Product fields here")).toBeInTheDocument();
    expect(screen.getByText("Tracked fields")).toBeInTheDocument();
    expect(screen.getByText("Custom fields")).toBeInTheDocument();
  });
});

describe("StorageEditFields — every field on it is a field you can fill in", () => {
  it("offers the description the label prints", () => {
    renderFields();
    expect(
      screen.getByLabelText("Show description on label"),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Description")).toBeInTheDocument();
  });

  it("names the storage's own whereabouts, not a shelf inside it", () => {
    renderFields();
    expect(
      screen.getByLabelText("How to get there (optional)"),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Exact location/)).not.toBeInTheDocument();
  });

  it("does not offer to take the shelf out of stock", () => {
    renderFields();
    expect(screen.queryByLabelText(/Purpose/i)).not.toBeInTheDocument();
    expect(
      screen.queryByText(/counts towards your stock/),
    ).not.toBeInTheDocument();
  });

  // The search answers only after the 300 ms debounce, a server round trip and
  // a render of 100 buttons, and every role query walks that many buttons to
  // compute their names: seconds, not milliseconds, in a full run on a loaded
  // host. The wait for the answer and the test's own budget say so.
  const SEARCH_ANSWER_MS = 20_000;

  it("says where the location lies, in one searchable control", async () => {
    // More zones than one page holds, so the picker has to ask the server.
    const requests = serveLocations([
      { id: "home", name: "Home", parent_id: null },
      { id: "me", name: "Kitchen Shelf", parent_id: "home" },
      { id: "inside", name: "Drawer", parent_id: "me" },
      ...Array.from({ length: 150 }, (_, i) => ({
        id: `z${i}`,
        name: `Zone ${i}`,
        parent_id: "home",
      })),
    ]);
    renderFields();

    await userEvent.click(screen.getByLabelText("Lies in"));
    expect(screen.getByPlaceholderText(/search/i)).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Zone 7(?!\d)/ }),
    ).toBeInTheDocument();
    // The place itself and what stands inside it are not places it can go.
    expect(screen.queryByRole("button", { name: /Kitchen Shelf/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Drawer/ })).toBeNull();
    // The last zone is not on the page; typing asks the server for it.
    expect(screen.queryByRole("button", { name: /Zone 149/ })).toBeNull();
    await userEvent.type(screen.getByPlaceholderText(/search/i), "Zone 149");
    expect(
      await screen.findByRole(
        "button",
        { name: /Zone 149/ },
        { timeout: SEARCH_ANSWER_MS },
      ),
    ).toBeInTheDocument();
    expect(requests.some((r) => r.get("q") === "Zone 149")).toBe(true);
    expect(requests.every((r) => r.get("limit") === "100")).toBe(true);
  }, 30_000);
});

describe("StorageEditFields — the storage types did not arrive", () => {
  afterEach(() => {
    storageTypesData.length = 0;
  });

  it("swaps the type picker for a retry instead of offering 'None' alone", async () => {
    const refetch = vi.fn();
    render(
      <QueryWrapper>
        <MemoryRouter>
          <StorageEditFields
            formData={formData}
            setFormData={vi.fn()}
            storageTypes={[]}
            typesError={new Error("down")}
            onRetryTypes={refetch}
            locationId="me"
            isGeneratingCode={false}
            onGenerateCode={vi.fn()}
            onQrDownload={vi.fn()}
            insideCount={0}
            t={tFor("locations")}
          />
        </MemoryRouter>
      </QueryWrapper>,
    );

    expect(screen.queryByLabelText(/storage type/i)).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe("StorageEditFields — fields a level above set", () => {
  const rack = { from_id: "rack", from_name: "Cold rack" };

  it("says how far the fields set here reach", () => {
    renderFields(undefined, { insideCount: 20 });
    expect(
      screen.getByText(/Applies to this location and 20 locations inside/),
    ).toBeInTheDocument();
  });

  it("says a location with nothing inside sets fields for itself only", () => {
    renderFields();
    expect(
      screen.getByText(/Applies to this location only/),
    ).toBeInTheDocument();
  });

  it("shows an inherited tracked field on and locked, naming its level", () => {
    renderFields(undefined, {
      inherited: {
        inherited_context_schema: [{ key: "notes", ...rack }],
        inherited_field_definitions: [],
      },
    });
    const notes = screen.getByRole("button", { name: /Notes/ });
    expect(notes).toBeDisabled();
    expect(notes).toHaveTextContent("from Cold rack");
    // A field nobody above set stays a toggle of this location's own.
    expect(screen.getByRole("button", { name: /Price/ })).toBeEnabled();
  });

  it("lists an inherited custom field read-only with its level", () => {
    renderFields(undefined, {
      inherited: {
        inherited_context_schema: [],
        inherited_field_definitions: [
          {
            key: "opened_on",
            label: "Opened on",
            type: "date",
            required: false,
            visible: true,
            is_system: false,
            ...rack,
          },
        ],
      },
    });
    const list = screen.getByRole("list", { name: "Set on a level above" });
    expect(list).toHaveTextContent("Opened on");
    expect(list).toHaveTextContent("from Cold rack");
  });
});

describe("StorageEditFields — each control hands its change to the form", () => {
  it("passes a new type on and 'None' back as no type", () => {
    const setFormData = vi.fn();
    renderFields(undefined, {
      setFormData,
      storageTypes: [
        { id: "t-shelf", name: "Shelf" } as StorageType,
        { id: "t-fridge", name: "Fridge" } as StorageType,
      ],
      formData: { ...formData, location_type_id: "t-shelf" },
    });
    const select = screen.getByLabelText("Location type");

    fireEvent.change(select, { target: { value: "t-fridge" } });
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      location_type_id: "t-fridge",
    });

    fireEvent.change(select, { target: { value: "" } });
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      location_type_id: null,
    });
  });

  it("passes the typed description, location details and short code on, so Save sends what the person typed", () => {
    const setFormData = vi.fn();
    renderFields(undefined, { setFormData });

    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "Top shelf" },
    });
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      description: "Top shelf",
    });

    fireEvent.change(screen.getByLabelText("How to get there (optional)"), {
      target: { value: "Behind the door" },
    });
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      location_details: "Behind the door",
    });

    fireEvent.change(screen.getByPlaceholderText(/LOC-001/), {
      target: { value: "ks-2" },
    });
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      short_code: "KS-2",
    });
  });

  it("turns the label description off when its box is unticked", () => {
    const setFormData = vi.fn();
    renderFields(undefined, { setFormData });

    fireEvent.click(screen.getByLabelText("Show description on label"));

    expect(setFormData).toHaveBeenCalledWith({
      ...formData,
      label_show_description: false,
    });
  });

  it("adds a tracked field to the schema when its row is pressed", async () => {
    const setFormData = vi.fn();
    renderFields(undefined, { setFormData });

    await userEvent.click(screen.getByText("Price"));

    expect(setFormData).toHaveBeenCalledWith({
      ...formData,
      context_schema: ["price"],
    });
  });

  it("passes a custom field built in the form on, so it is saved with the location", async () => {
    const setFormData = vi.fn();
    renderFields(undefined, { setFormData });

    await userEvent.click(screen.getByText("Custom Field Definitions"));
    await userEvent.click(screen.getByText("Add custom field"));
    await userEvent.type(
      screen.getByPlaceholderText("e.g. Voltage"),
      "Voltage",
    );
    await userEvent.click(screen.getByText("Add field"));

    expect(setFormData).toHaveBeenCalledTimes(1);
    const sent = setFormData.mock.calls[0][0] as StorageEditFormData;
    expect(sent.field_definitions).toHaveLength(1);
    expect(sent.field_definitions[0]).toMatchObject({
      label: "Voltage",
      type: "text",
    });
  });

  it("passes the chosen parent on, and no parent when the place is cleared", async () => {
    serveLocations([
      { id: "home", name: "Home", parent_id: null },
      { id: "me", name: "Kitchen Shelf", parent_id: "home" },
      { id: "garage", name: "Garage", parent_id: "home" },
    ]);
    const setFormData = vi.fn();
    renderFields(undefined, {
      setFormData,
      formData: { ...formData, parent_id: "home" },
    });

    await userEvent.click(screen.getByLabelText("Lies in"));
    await userEvent.click(
      await screen.findByRole("button", { name: /Garage/ }),
    );
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      parent_id: "garage",
    });

    await userEvent.click(screen.getByLabelText("Lies in"));
    await userEvent.click(
      await screen.findByRole("button", { name: "No parent location" }),
    );
    expect(setFormData).toHaveBeenLastCalledWith({
      ...formData,
      parent_id: null,
    });
  });
});
