import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import deCategories from "@/i18n/locales/de/categories.json";
import enCategories from "@/i18n/locales/en/categories.json";
import esCategories from "@/i18n/locales/es/categories.json";
import frCategories from "@/i18n/locales/fr/categories.json";
import plCategories from "@/i18n/locales/pl/categories.json";
import { render, screen } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import { FALLBACK_COLORS } from "./CategoryAvatar";
import { ColorSwatchPicker, PALETTE_KEYS } from "./ColorSwatchPicker";

/**
 * A swatch used to answer to the palette key it stores — "sky", "violet",
 * "slate", and "accent", which is not even a colour but the role a token
 * plays. A screen reader announced those tokens in a Polish dialog.
 */
const CATALOGUES: Record<string, Record<string, string>> = {
  en: enCategories.modal.colors,
  pl: plCategories.modal.colors,
  de: deCategories.modal.colors,
  fr: frCategories.modal.colors,
  es: esCategories.modal.colors,
};

describe("what a colour swatch is called", () => {
  it("is a name in every language, for every key of the palette", () => {
    for (const [language, names] of Object.entries(CATALOGUES)) {
      for (const key of PALETTE_KEYS) {
        expect(names[key], `${language}: ${key} has no name`).toBeTruthy();
      }
    }
  });

  it("names each colour apart, and none of them after its token", () => {
    // Polish is the language the defect was reported in — a dialog
    // announcing "slate" — and no Polish colour word is spelled like a
    // Tailwind token, so the two sets cannot meet. English is the one
    // language where `violet`, `slate` and `amber` are the colour's own
    // name; holding it to this rule would ask for a synonym nobody uses.
    const names = CATALOGUES.pl;
    for (const key of PALETTE_KEYS) {
      expect(names[key].toLowerCase(), `${key} answers to its key`).not.toBe(
        key,
      );
    }
    for (const [language, catalogue] of Object.entries(CATALOGUES)) {
      const spoken = PALETTE_KEYS.map((key) => catalogue[key]);
      expect(new Set(spoken).size, `${language} repeats a name`).toBe(
        spoken.length,
      );
    }
  });

  it("reaches the button, and the tooltip says the same thing", async () => {
    await withLanguage("pl", async () => {
      // A stored legacy key renders its swatch too, so the row shows the
      // curated seven plus `purple`.
      render(<ColorSwatchPicker value="purple" onChange={() => {}} />);

      const slate = screen.getByRole("radio", { name: "Grafitowy" });
      expect(slate).toHaveAttribute("title", "Grafitowy");
      expect(
        screen.getByRole("radio", { name: "Purpurowy" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("radio", { name: "slate" })).toBeNull();
      expect(screen.queryByRole("radio", { name: "purple" })).toBeNull();
    });
  });

  it("keeps a 44px target below md, with the dot itself still 24px", () => {
    // The row offers eight adjacent colours. At 24px the gap between two
    // neighbours was smaller than a fingertip, and a miss sets a different
    // colour for the category. The dot stays 24px above `md`, where a
    // pointer aims it.
    render(<ColorSwatchPicker value={null} onChange={() => {}} />);

    const swatch = screen.getByRole("radio", { name: "Violet" });
    expect(swatch).toHaveClass("h-11", "w-11", "md:h-6", "md:w-6");
    expect(swatch.querySelector("span")).toHaveClass("h-6", "w-6");
    expect(screen.getByRole("radio", { name: "Auto" })).toHaveClass(
      "h-11",
      "md:h-6",
    );
  });
});

const colorName = (key: string) =>
  (enCategories.modal.colors as Record<string, string>)[key];

describe("choosing a colour", () => {
  it("reports the swatch the reader presses", async () => {
    const onChange = vi.fn();
    render(<ColorSwatchPicker value={null} onChange={onChange} />);

    await userEvent.click(
      screen.getByRole("radio", { name: colorName(FALLBACK_COLORS[1]) }),
    );

    expect(onChange).toHaveBeenCalledExactlyOnceWith(FALLBACK_COLORS[1]);
  });

  it("reports null for Auto so the colour falls back to the name's hash", async () => {
    const onChange = vi.fn();
    render(<ColorSwatchPicker value={PALETTE_KEYS[0]} onChange={onChange} />);

    await userEvent.click(screen.getByRole("radio", { name: "Auto" }));

    expect(onChange).toHaveBeenCalledExactlyOnceWith(null);
  });

  it("offers no Auto choice where the colour cannot be left unset", () => {
    render(
      <ColorSwatchPicker
        value={PALETTE_KEYS[0]}
        onChange={vi.fn()}
        showAuto={false}
      />,
    );

    expect(screen.queryByRole("radio", { name: "Auto" })).toBeNull();
  });
});
