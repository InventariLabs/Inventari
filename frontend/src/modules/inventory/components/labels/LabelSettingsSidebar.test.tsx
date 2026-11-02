/**
 * The size fields on the print window looked switched off: a filled inset
 * background, no border of its own — the shape this app uses for a disabled
 * control — even though every one of them accepts typing.
 */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { Input } from "@/components/ui/Input";
import { tFor } from "@/test/mocks/i18n";
import enLabels from "@/i18n/locales/en/labels.json";
import type { LabelPool } from "@/types";
import { LabelSettingsSidebar } from "./LabelSettingsSidebar";

// No printer registered: the sidebar as it is for a downloaded file. With a
// printer it is LabelPreviewPrinter.test.tsx's.
vi.mock("@/modules/shared/hooks/usePrintQueue", () => ({
  usePrintAgents: () => ({ data: [] }),
}));

const settings = {
  width: 50,
  height: 24,
  publicUrl: "https://example.test",
  customDescription: "",
  qrOnly: false,
  copiesPerLabel: 1,
  showCode: false,
};

// A real translator, not `(key) => key`: under the identity stub every
// assertion on a label asserts the key, and passes whether the translation
// exists or not.
const t = tFor("labels") as never;

const renderSidebar = () =>
  render(
    <LabelSettingsSidebar
      selectedLabels={[] as LabelPool[]}
      printSettings={settings}
      setPrintSettings={vi.fn()}
      t={t}
    />,
  );

/** Classes a plain field in this app carries — the storage edit sheet's. */
const referenceClasses = () => {
  const { container, unmount } = render(<Input label="reference" />);
  const classes = (container.querySelector("input") as HTMLInputElement)
    .className;
  unmount();
  return classes.split(" ").filter(Boolean);
};

describe("LabelSettingsSidebar", () => {
  it("styles the size fields like every other field in the app", () => {
    const reference = referenceClasses();
    renderSidebar();

    const width = screen.getByLabelText(`${enLabels.previewModal.width} (mm)`);
    for (const cls of reference) {
      expect(width.className.split(" ")).toContain(cls);
    }
    expect(width.className).not.toContain("bg-surface-inset");
  });

  it("names each field for a reader, not just for the eye", () => {
    renderSidebar();

    // The labels used to be loose <span>s above the inputs, associated with
    // nothing.
    expect(
      screen.getByLabelText(enLabels.previewModal.labelDescription),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(`${enLabels.previewModal.height} (mm)`),
    ).toBeInTheDocument();
    expect(
      screen.getByLabelText(enLabels.previewModal.copies),
    ).toBeInTheDocument();
  });
});

/**
 * What goes on the label used to be two independent switches, and between
 * them the word "code" meant two things: the QR square in one, the string
 * STM-K9XP in the other. They also described the choice badly — the fourth
 * arrangement, a short code with no caption, could not be asked for at all,
 * because "QR code only" was read as "no text" rather than "no caption".
 */
describe("what goes on the label", () => {
  const renderWith = (
    printSettings: typeof settings,
    setPrintSettings = vi.fn(),
  ) => {
    const view = render(
      <LabelSettingsSidebar
        selectedLabels={[] as LabelPool[]}
        printSettings={printSettings}
        setPrintSettings={setPrintSettings}
        t={t}
      />,
    );
    return { ...view, setPrintSettings };
  };

  // Exact names, not a regex: "description" is a prefix of
  // "descriptionAndCode" and matched both.
  const option = (name: string) => screen.getByRole("radio", { name });

  it("offers every arrangement, whichever one is current", () => {
    renderWith({ ...settings, qrOnly: true, showCode: true });

    // Nothing is conditional: the row that used to vanish took the panel's
    // height with it and moved every control under it.
    expect(screen.getAllByRole("radio")).toHaveLength(4);
    expect(option(enLabels.previewModal.content.codeOnly)).toBeChecked();
  });

  it.each([
    [
      enLabels.previewModal.content.description,
      { qrOnly: false, showCode: false },
    ],
    [
      enLabels.previewModal.content.descriptionAndCode,
      { qrOnly: false, showCode: true },
    ],
    [enLabels.previewModal.content.codeOnly, { qrOnly: true, showCode: true }],
    [enLabels.previewModal.content.qrOnly, { qrOnly: true, showCode: false }],
  ])("sends %s as the pair the renderer understands", (key, expected) => {
    const { setPrintSettings } = renderWith({
      ...settings,
      qrOnly: false,
      showCode: false,
    });

    option(key).click();

    expect(setPrintSettings).toHaveBeenCalledWith(
      expect.objectContaining(expected),
    );
  });
});

/**
 * A preset is a guess about the stock in the printer. Every one of them was
 * wider than it was tall, so a label carrying nothing but a QR had no size
 * that fitted it: 30 mm of a 50 x 24 die-cut label left blank, and on a
 * sheet there is nothing to trim.
 */
describe("the sizes on offer follow what the label carries", () => {
  const renderWith = (printSettings: typeof settings) => {
    const setPrintSettings = vi.fn();
    render(
      <LabelSettingsSidebar
        selectedLabels={[] as LabelPool[]}
        printSettings={printSettings}
        setPrintSettings={setPrintSettings}
        t={t}
      />,
    );
    return setPrintSettings;
  };

  it("offers square sizes once nothing but the square is printed", () => {
    renderWith({ ...settings, qrOnly: true, showCode: false });

    expect(
      screen.getByRole("button", {
        name: `${enLabels.previewModal.preset.square} 24×24`,
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", {
        name: `${enLabels.previewModal.preset.standard} 50×24`,
      }),
    ).toBeNull();
  });

  it("carries the size along when the current one was a preset", () => {
    const setPrintSettings = renderWith(settings);

    screen
      .getByRole("radio", { name: enLabels.previewModal.content.qrOnly })
      .click();

    expect(setPrintSettings).toHaveBeenCalledWith(
      expect.objectContaining({ qrOnly: true, width: 24, height: 24 }),
    );
  });

  it("leaves a size somebody typed exactly where it is", () => {
    // Not a guess about the stock — somebody measured their labels.
    const setPrintSettings = renderWith({ ...settings, width: 47, height: 19 });

    screen
      .getByRole("radio", { name: enLabels.previewModal.content.qrOnly })
      .click();

    expect(setPrintSettings).toHaveBeenCalledWith(
      expect.objectContaining({ qrOnly: true, width: 47, height: 19 }),
    );
  });
});

/**
 * The page keeps the settings in one object and the sidebar writes the whole
 * of it back on every edit, so an edit that dropped a sibling field would
 * quietly reset it.
 */
describe("what the sidebar writes back", () => {
  const renderWith = (
    overrides: Partial<typeof settings> = {},
    selectedLabels: LabelPool[] = [],
  ) => {
    const setPrintSettings = vi.fn();
    render(
      <LabelSettingsSidebar
        selectedLabels={selectedLabels}
        printSettings={{ ...settings, ...overrides }}
        setPrintSettings={setPrintSettings}
        t={t}
      />,
    );
    return setPrintSettings;
  };

  it("takes a preset's two numbers and leaves the rest alone", () => {
    const setPrintSettings = renderWith({ customDescription: "Jam" });

    screen
      .getByRole("button", {
        name: `${enLabels.previewModal.preset.narrow} 50×12`,
      })
      .click();

    expect(setPrintSettings).toHaveBeenCalledWith({
      ...settings,
      customDescription: "Jam",
      width: 50,
      height: 12,
    });
  });

  it("writes the description as typed", () => {
    const setPrintSettings = renderWith();

    fireEvent.change(
      screen.getByLabelText(enLabels.previewModal.labelDescription),
      { target: { value: "Grandma's jam" } },
    );

    expect(setPrintSettings).toHaveBeenCalledWith({
      ...settings,
      customDescription: "Grandma's jam",
    });
  });

  it("writes the width and the height as numbers, and zero for a cleared field", () => {
    const setPrintSettings = renderWith();

    fireEvent.change(
      screen.getByLabelText(`${enLabels.previewModal.width} (mm)`),
      {
        target: { value: "45.5" },
      },
    );
    expect(setPrintSettings).toHaveBeenLastCalledWith({
      ...settings,
      width: 45.5,
    });

    fireEvent.change(
      screen.getByLabelText(`${enLabels.previewModal.height} (mm)`),
      { target: { value: "19" } },
    );
    expect(setPrintSettings).toHaveBeenLastCalledWith({
      ...settings,
      height: 19,
    });

    fireEvent.change(
      screen.getByLabelText(`${enLabels.previewModal.height} (mm)`),
      { target: { value: "" } },
    );
    expect(setPrintSettings).toHaveBeenLastCalledWith({
      ...settings,
      height: 0,
    });
  });

  describe("copies per label", () => {
    it("steps up by one", () => {
      const up = renderWith({ copiesPerLabel: 3 });
      screen.getByRole("button", { name: "Increase" }).click();
      expect(up).toHaveBeenCalledWith({ ...settings, copiesPerLabel: 4 });
    });

    it("stops at one when the minus is pressed on a single copy", () => {
      const setPrintSettings = renderWith({ copiesPerLabel: 1 });

      screen.getByRole("button", { name: "Decrease" }).click();

      expect(setPrintSettings).toHaveBeenCalledWith({
        ...settings,
        copiesPerLabel: 1,
      });
    });

    it("steps down from three to two", () => {
      const setPrintSettings = renderWith({ copiesPerLabel: 3 });

      screen.getByRole("button", { name: "Decrease" }).click();

      expect(setPrintSettings).toHaveBeenCalledWith({
        ...settings,
        copiesPerLabel: 2,
      });
    });

    it("stops at 200 when the plus is pressed on the most the printer is asked for", () => {
      const setPrintSettings = renderWith({ copiesPerLabel: 200 });

      screen.getByRole("button", { name: "Increase" }).click();

      expect(setPrintSettings).toHaveBeenCalledWith({
        ...settings,
        copiesPerLabel: 200,
      });
    });

    it("offers the stock quantity of a single assigned product as the copy count", () => {
      // One sticker per unit on the shelf is what a goods-in bench prints.
      const setPrintSettings = renderWith({}, [
        {
          id: "1",
          short_code: "STM-0001",
          assigned_item_quantity: 12,
          assigned_item_unit: "pcs",
        } as LabelPool,
      ]);

      fireEvent.click(
        screen.getByRole("button", { name: /Set to product qty/ }),
      );

      expect(setPrintSettings).toHaveBeenCalledWith({
        ...settings,
        copiesPerLabel: 12,
      });
    });

    it("holds a typed count between one and 200", () => {
      const setPrintSettings = renderWith({ copiesPerLabel: 5 });
      const field = screen.getByLabelText("Copies per label");

      fireEvent.change(field, { target: { value: "0" } });
      expect(setPrintSettings).toHaveBeenLastCalledWith({
        ...settings,
        copiesPerLabel: 1,
      });
      fireEvent.change(field, { target: { value: "5000" } });
      expect(setPrintSettings).toHaveBeenLastCalledWith({
        ...settings,
        copiesPerLabel: 200,
      });
    });
  });
});
