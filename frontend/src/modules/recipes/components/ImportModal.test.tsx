import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import ImportIngredientRow from "./ImportIngredientRow";
import { ImportModal } from "./ImportModal";
import { renderWithProviders } from "@/test/utils";
import type { IngredientDraft } from "./importReviewUtils";

const t = (key: string) =>
  key === "recipes:import_export.unit_not_recognized"
    ? "Unit not recognized — pick manually"
    : key === "recipes:import_export.review_unit_unrecognized_label"
      ? "Unrecognized"
      : key;

const baseDraft: IngredientDraft = {
  _key: 0,
  name: "Flour",
  quantity: "300",
  uom_id: "uom-g",
  original_text: null,
  group_name: null,
  template_id: null,
  template_name: null,
  is_optional: false,
  is_spice_forced: false,
  allergens: [],
  original_unit_text: "g",
  unread_unit: null,
  unit_display: "g",
  metric_quantity: "300",
  conversion_ratio: 1,
};

const flatUoms = [{ id: "uom-g", symbol: "g", name: "Gram" }] as never[];

describe("ImportIngredientRow — unit warning", () => {
  const noop = vi.fn();

  it("shows warning when original unit is not linked to a UOM", () => {
    renderWithProviders(
      <ImportIngredientRow
        ing={{ ...baseDraft, uom_id: null }}
        idx={0}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={noop}
        onRemove={noop}
        t={t}
      />,
    );
    const badge = screen.getByTestId("unit-not-recognized");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveAttribute(
      "title",
      "Unit not recognized — pick manually",
    );
    expect(screen.getByText("Unrecognized")).toBeInTheDocument();
    // The unrecognised unit is not the end of the row: a unit can be picked.
    expect(screen.getByRole("button", { name: /Choose/ })).toBeInTheDocument();
  });

  it("does not show warning when unit is recognized", () => {
    render(
      <ImportIngredientRow
        ing={baseDraft}
        idx={0}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={noop}
        onRemove={noop}
        t={t}
      />,
    );
    expect(screen.queryByTestId("unit-not-recognized")).not.toBeInTheDocument();
  });
});

describe("ImportIngredientRow — the spice chip announces its state", () => {
  const noop = vi.fn();

  function renderRow(ing: IngredientDraft) {
    render(
      <ImportIngredientRow
        ing={ing}
        idx={0}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={noop}
        onRemove={noop}
        t={t}
      />,
    );
    return screen.getByRole("button", {
      name: /recipes:import_export\.review_spice_label/,
    });
  }

  /**
   * The state used to travel in the background colour alone: a screen reader
   * heard "Spice, button" whether the ingredient was one or not, and so did
   * anyone who does not separate amber from grey.
   */
  it("is pressed when the ingredient counts as a spice", () => {
    // 5 g is under the 10 g/ml threshold the import derives from.
    expect(
      renderRow({ ...baseDraft, quantity: "5", metric_quantity: "5" }),
    ).toHaveAttribute("aria-pressed", "true");
  });

  it("is not pressed for a plain ingredient", () => {
    expect(renderRow(baseDraft)).toHaveAttribute("aria-pressed", "false");
  });

  it("cannot be switched off on an amount-derived spice", () => {
    // The recipe screens treat a small amount as a spice whatever the stored
    // mark says, so a press that appeared to clear it would be a lie.
    const onUpdate = vi.fn();
    render(
      <ImportIngredientRow
        ing={{ ...baseDraft, quantity: "5", metric_quantity: "5" }}
        idx={0}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={onUpdate}
        onRemove={noop}
        t={t}
      />,
    );
    const chip = screen.getByRole("button", {
      name: /recipes:import_export\.review_spice_label/,
    });
    expect(chip).toBeDisabled();
    fireEvent.click(chip);
    expect(onUpdate).not.toHaveBeenCalled();
  });

  it("points at an explanation that does not need a mouse", () => {
    // `title` only ever showed on hover — a touch screen never saw it.
    const chip = renderRow({
      ...baseDraft,
      quantity: "5",
      metric_quantity: "5",
    });
    expect(chip).not.toHaveAttribute("title");
    const hintId = chip.getAttribute("aria-describedby");
    expect(hintId).toBeTruthy();
    expect(document.getElementById(hintId!)).toHaveTextContent(
      "recipes:import_export.review_spice_hint",
    );
  });

  // The note sat once above the whole list, so it read as a remark about the
  // first line — 200 g of rice. It stands under the line whose small amount
  // it explains, and nowhere else.
  it("explains the spices section under the small amount, not under a plain line", () => {
    const { container: spiceRow } = render(
      <ImportIngredientRow
        ing={{ ...baseDraft, quantity: "5", metric_quantity: "5" }}
        idx={0}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={noop}
        onRemove={noop}
        t={t}
      />,
    );
    expect(spiceRow).toHaveTextContent(
      "recipes:import_export.review_spice_hint",
    );

    const { container: plainRow } = render(
      <ImportIngredientRow
        ing={baseDraft}
        idx={1}
        showOriginal={false}
        flatUoms={flatUoms}
        onUpdate={noop}
        onRemove={noop}
        t={t}
      />,
    );
    expect(plainRow).not.toHaveTextContent(
      "recipes:import_export.review_spice_hint",
    );
  });
});

describe("ImportModal — show example format", () => {
  it("invokes onShowExample when the link is clicked", () => {
    const onShowExample = vi.fn();
    render(
      <ImportModal
        isOpen
        importMode="json"
        importUrl=""
        importJson=""
        isPreviewPending={false}
        onModeChange={vi.fn()}
        onUrlChange={vi.fn()}
        onJsonChange={vi.fn()}
        onShowExample={onShowExample}
        onImport={vi.fn()}
        onClose={vi.fn()}
        titleText="Import recipe"
        urlTabText="URL"
        jsonTabText="JSON"
        urlLabel="Recipe URL"
        jsonLabel="Recipe JSON"
        urlPlaceholder="url"
        jsonPlaceholder="paste"
        showExampleText="Show example format"
        cancelText="Cancel"
        submitText="Import"
        parsingText="Parsing…"
      />,
    );
    fireEvent.click(screen.getByText("Show example format"));
    expect(onShowExample).toHaveBeenCalledTimes(1);
  });
});

describe("ImportModal — mode switch is a tablist", () => {
  it("exposes the two import modes as tabs, with the active one selected", () => {
    render(
      <ImportModal
        isOpen
        importMode="json"
        importUrl=""
        importJson=""
        isPreviewPending={false}
        onModeChange={vi.fn()}
        onUrlChange={vi.fn()}
        onJsonChange={vi.fn()}
        onShowExample={vi.fn()}
        onImport={vi.fn()}
        onClose={vi.fn()}
        titleText="Import recipe"
        urlTabText="URL"
        jsonTabText="JSON"
        urlLabel="Recipe URL"
        jsonLabel="Recipe JSON"
        urlPlaceholder="url"
        jsonPlaceholder="paste"
        showExampleText="Show example format"
        cancelText="Cancel"
        submitText="Import"
        parsingText="Parsing…"
      />,
    );
    expect(screen.getAllByRole("tab")).toHaveLength(2);
    expect(screen.getByRole("tab", { name: "JSON" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(screen.getByRole("tab", { name: "URL" })).toHaveAttribute(
      "aria-selected",
      "false",
    );
  });
});

describe("ImportModal — padded content", () => {
  it("keeps the title off the sheet edge via a padded container", () => {
    render(
      <ImportModal
        isOpen
        importMode="url"
        importUrl=""
        importJson=""
        isPreviewPending={false}
        onModeChange={vi.fn()}
        onUrlChange={vi.fn()}
        onJsonChange={vi.fn()}
        onShowExample={vi.fn()}
        onImport={vi.fn()}
        onClose={vi.fn()}
        titleText="Import recipe"
        urlTabText="URL"
        jsonTabText="JSON"
        urlLabel="Recipe URL"
        jsonLabel="Recipe JSON"
        urlPlaceholder="url"
        jsonPlaceholder="paste"
        showExampleText="Show example format"
        cancelText="Cancel"
        submitText="Import"
        parsingText="Parsing…"
      />,
    );
    const title = screen.getByText("Import recipe");
    // Same padding container as the other Sheets in this module
    expect(title.parentElement).toHaveClass("p-5");
  });
});

describe("ImportModal — the import fields are named by labels, not placeholders", () => {
  // Both fields carried only a placeholder before, so a screen reader
  // announced an unnamed field and the placeholder stood in for a name.
  function renderModal(
    overrides: Partial<Parameters<typeof ImportModal>[0]> = {},
  ) {
    return render(
      <MemoryRouter>
        <ImportModal
          isOpen
          importMode="url"
          importUrl=""
          importJson=""
          isPreviewPending={false}
          onModeChange={vi.fn()}
          onUrlChange={vi.fn()}
          onJsonChange={vi.fn()}
          onShowExample={vi.fn()}
          onImport={vi.fn()}
          onClose={vi.fn()}
          titleText="Import recipe"
          urlTabText="URL"
          jsonTabText="JSON"
          urlLabel="Recipe URL"
          jsonLabel="Recipe JSON"
          urlPlaceholder="https://example.com/recipe"
          jsonPlaceholder="Paste recipe JSON here…"
          showExampleText="Show example format"
          cancelText="Cancel"
          submitText="Import"
          parsingText="Parsing…"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("reaches the URL field by its label", () => {
    renderModal();
    const field = screen.getByLabelText("Recipe URL");
    expect(field).toHaveAttribute("placeholder", "https://example.com/recipe");
  });

  it("reaches the JSON field by its label", () => {
    renderModal({ importMode: "json" });
    const field = screen.getByLabelText("Recipe JSON");
    expect(field).toHaveAttribute("placeholder", "Paste recipe JSON here…");
  });
});

describe("ImportModal — URL tab refuses to offer what cannot work", () => {
  const aiBlockedProps = {
    urlNeedsAi: true,
    urlNeedsAiNotice:
      'Reading a page needs an AI connection — "Read a recipe from text" is not configured yet.',
    urlNeedsAiCtaText: "Set one up in Settings → AI Connections",
  };

  function renderModal(
    overrides: Partial<Parameters<typeof ImportModal>[0]> = {},
  ) {
    return render(
      <MemoryRouter>
        <ImportModal
          isOpen
          importMode="url"
          importUrl="https://example.com/recipe"
          importJson=""
          isPreviewPending={false}
          onModeChange={vi.fn()}
          onUrlChange={vi.fn()}
          onJsonChange={vi.fn()}
          onShowExample={vi.fn()}
          onImport={vi.fn()}
          onClose={vi.fn()}
          titleText="Import recipe"
          urlTabText="URL"
          jsonTabText="JSON"
          urlLabel="Recipe URL"
          jsonLabel="Recipe JSON"
          urlPlaceholder="url"
          jsonPlaceholder="paste"
          showExampleText="Show example format"
          cancelText="Cancel"
          submitText="Import"
          parsingText="Parsing…"
          {...overrides}
        />
      </MemoryRouter>,
    );
  }

  it("explains itself and holds the submit back while no connection is bound", () => {
    renderModal(aiBlockedProps);
    expect(screen.getByText(/is not configured yet/)).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: aiBlockedProps.urlNeedsAiCtaText }),
    ).toHaveAttribute("href", "/settings/ai");
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("does not let a typed URL buy back the submit", () => {
    renderModal({ ...aiBlockedProps, importUrl: "" });
    fireEvent.change(screen.getByPlaceholderText("url"), {
      target: { value: "https://example.com/recipe" },
    });
    expect(screen.getByRole("button", { name: "Import" })).toBeDisabled();
  });

  it("leaves the JSON tab working — the paste path needs no connection", () => {
    renderModal({
      ...aiBlockedProps,
      importMode: "json",
      importJson: '{"name": "Soup"}',
    });
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
  });

  it("stays silent when the registry says the purpose is bound", () => {
    renderModal({
      urlNeedsAi: false,
      urlNeedsAiNotice: null,
      urlNeedsAiCtaText: aiBlockedProps.urlNeedsAiCtaText,
    });
    expect(screen.queryByText(/is not configured yet/)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Import" })).toBeEnabled();
  });
});

describe("ImportModal — one height for both modes", () => {
  it("keeps both panels mounted in one grid cell, so the sheet does not jump between modes", () => {
    render(
      <ImportModal
        isOpen
        importMode="url"
        importUrl=""
        importJson=""
        isPreviewPending={false}
        onModeChange={vi.fn()}
        onUrlChange={vi.fn()}
        onJsonChange={vi.fn()}
        onShowExample={vi.fn()}
        onImport={vi.fn()}
        onClose={vi.fn()}
        titleText="Import recipe"
        urlTabText="URL"
        jsonTabText="JSON"
        urlLabel="Recipe URL"
        jsonLabel="Recipe JSON"
        urlPlaceholder="url"
        jsonPlaceholder="paste"
        showExampleText="Show example format"
        cancelText="Cancel"
        submitText="Import"
        parsingText="Parsing…"
      />,
    );
    // The JSON mode is taller than the URL mode; each in turn used to size
    // the sheet, which moved on every switch. Both stay in the layout now.
    const panels = screen.getAllByRole("tabpanel", { hidden: true });
    expect(panels).toHaveLength(2);
    for (const panel of panels) {
      expect(panel.className).toContain("col-start-1");
      expect(panel.parentElement?.className).toContain("grid");
    }
  });
});
