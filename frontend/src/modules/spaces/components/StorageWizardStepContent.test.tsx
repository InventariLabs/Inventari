import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { StepContent, type StepContentProps } from "./StorageWizardStepContent";
import type { FieldDefinition, StorageType } from "@/types";
import { tFor } from "@/test/mocks/i18n";
import { QueryWrapper } from "@/test/queryWrapper";
import { serveLocations } from "@/test/serveLocations";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const baseProps: StepContentProps = {
  step: 3,
  parentId: null,
  parentName: "Kitchen",
  locationName: "Fridge",
  selectedFields: null,
  effectiveFields: ["barcode", "price", "notes", "shelf_location"],
  customFields: [] as FieldDefinition[],
  hasParents: false,
  filteredParentSuggestions: [],
  locationSuggestions: [],
  parentInputRef: { current: null } as React.RefObject<HTMLInputElement>,
  locationInputRef: { current: null } as React.RefObject<HTMLInputElement>,
  showAdvanced: false,
  labelCode: "",
  description: "",
  storageTypes: [],
  storageTypeId: null,
  onStorageTypeChange: vi.fn(),
  onSelectParent: vi.fn(),
  onParentChip: vi.fn(),
  onParentNameChange: vi.fn(),
  onLocationNameChange: vi.fn(),
  onLocationChip: vi.fn(),
  onFieldsChange: vi.fn(),
  onCustomFieldsChange: vi.fn(),
  onCustomize: vi.fn(),
  onToggleAdvanced: vi.fn(),
  onLabelCodeChange: vi.fn(),
  onDescriptionChange: vi.fn(),
  // Real translator: field labels come from `locations:fieldLabels.<key>`,
  // the one set the storage editor reads too.
  t: tFor("locations"),
};

const renderStep = (props: Partial<StepContentProps> = {}) =>
  render(
    <QueryWrapper>
      <StepContent {...baseProps} {...props} />
    </QueryWrapper>,
  );

describe("StorageWizardStepContent — neutral base fields", () => {
  describe("step 3 (field toggles)", () => {
    it("renders only the 4 neutral toggleable fields", () => {
      renderStep({ step: 3 });
      expect(screen.getByText("Product code")).toBeInTheDocument();
      expect(screen.getByText("Price")).toBeInTheDocument();
      expect(screen.getByText("Notes")).toBeInTheDocument();
      expect(screen.getByText("Shelf / position")).toBeInTheDocument();
    });

    it("does not render any food/equipment-biased tracking fields", () => {
      renderStep({ step: 3 });
      expect(screen.queryByText("Freeze Date")).not.toBeInTheDocument();
      expect(screen.queryByText("Expiry Date")).not.toBeInTheDocument();
      expect(
        screen.queryByText("Production Date / Batch"),
      ).not.toBeInTheDocument();
      expect(
        screen.queryByText("Brand / Manufacturer"),
      ).not.toBeInTheDocument();
    });

    it("renders exactly 4 toggle buttons in step 3", () => {
      renderStep({ step: 3 });
      // The toggle list is rendered as buttons, one per neutral base field.
      const labels = ["Product code", "Price", "Notes", "Shelf / position"];
      const toggleButtons = screen
        .getAllByRole("button")
        .filter((b) => labels.some((l) => b.textContent?.startsWith(l)));
      expect(toggleButtons.length).toBe(4);
    });
  });

  describe("step 2 (preview chips)", () => {
    it("shows the effective fields as preview chips without food keys", () => {
      renderStep({
        step: 2,
        effectiveFields: ["barcode", "notes"],
      });
      expect(screen.getByText("Product code")).toBeInTheDocument();
      expect(screen.getByText("Notes")).toBeInTheDocument();
      expect(screen.queryByText("Freeze Date")).not.toBeInTheDocument();
    });
  });
});

describe("StorageWizardStepContent — step 1 copy", () => {
  it("greets a first storage as a first storage", () => {
    renderStep({ step: 1, hasParents: false });

    expect(screen.getByText(/your first location/i)).toBeInTheDocument();
  });

  it("does not call the eleventh storage the first one", () => {
    serveLocations([{ id: "z1", name: "Main Warehouse" }]);
    renderStep({
      step: 1,
      hasParents: true,
    });

    expect(screen.queryByText(/your first location/i)).not.toBeInTheDocument();
    expect(
      screen.getByText(/name the location you are adding/i),
    ).toBeInTheDocument();
  });
});

describe("field labels are one set", () => {
  it("names a field the same way the storage editor does", () => {
    // The editor reads `locations:fieldLabels.<key>`; so does the wizard now.
    const t = tFor("locations");
    renderStep({ step: 3 });

    expect(
      screen.getByText(t("locations:fieldLabels.barcode") as string),
    ).toBeInTheDocument();
    expect(
      screen.getByText(t("locations:fieldLabels.shelf_location") as string),
    ).toBeInTheDocument();
  });
});

describe("step 3 storage types", () => {
  const seeded = [
    {
      id: "t-shelf",
      name: "Półka / szafa",
      type_code: "SHELF",
      behavior_mode: "STOCK",
    },
    {
      id: "t-freezer",
      name: "Zamrażarka",
      type_code: "FREEZER",
      behavior_mode: "FREEZING",
    },
    {
      id: "t-server",
      name: "Serwerownia",
      type_code: "SERVER_ROOM",
      behavior_mode: "NONE",
    },
  ] as StorageType[];

  it("offers each type under the name the seed wrote, and adds no name of its own", () => {
    // A guard, not the fix, and worth saying which: the type's name arrives
    // from the API and this screen renders it as it comes, so the English
    // seeds passed this test too. What it holds is the other half of the
    // contract — the wizard must never grow a name map of its own. That is
    // the mistake the storage *locations* had (a client translating a code at
    // display time, covering React screens and nothing else), and the reason
    // the name is written once, in the language of the reader who seeded it.
    renderStep({ step: 3, storageTypes: seeded });

    const t = tFor("locations");
    const select = screen.getByRole("combobox", {
      name: t("locations:onboarding.storageTypeLabel") as string,
    });

    expect(
      within(select)
        .getAllByRole("option")
        .map((option) => option.textContent),
    ).toEqual([
      t("locations:onboarding.storageTypeNone"),
      "Półka / szafa",
      "Zamrażarka",
      "Serwerownia",
    ]);
    for (const english of ["Shelf / Cabinet", "Freezer", "Server Room"]) {
      expect(
        within(select).queryByRole("option", { name: english }),
      ).not.toBeInTheDocument();
    }
  });
});

describe("StorageWizardStepContent — lists that did not arrive", () => {
  it("step 1 offers a retry for the parents instead of silently dropping the picker", () => {
    const onRetryParents = vi.fn();
    renderStep({ step: 1, parentsError: new Error("down"), onRetryParents });

    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetryParents).toHaveBeenCalledTimes(1);
  });

  it("step 3 swaps the storage type picker for a retry", () => {
    const onRetryTypes = vi.fn();
    renderStep({ step: 3, typesError: new Error("down"), onRetryTypes });

    const t = tFor("locations");
    expect(
      screen.queryByRole("combobox", {
        name: t("locations:onboarding.storageTypeLabel") as string,
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(onRetryTypes).toHaveBeenCalledTimes(1);
  });
});
