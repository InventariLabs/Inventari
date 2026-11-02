import { describe, expect, it, vi } from "vitest";
import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { render } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";

import * as profileHooks from "@/modules/warehouse/hooks/useDocumentProfile";

import { NewDocumentMenu } from "./NewDocumentMenu";

vi.mock("@/modules/warehouse/hooks/useDocumentProfile", () => ({
  useDocumentProfile: vi.fn(() => ({ data: undefined })),
}));

/**
 * The menu is where a document type is chosen, so it says what the type IS.
 *
 * It used to render `typesShort.<CODE>`, which in Polish is the paperwork
 * code alone — the menu offered "PZ", "WZ", "MM", "PW", "RW", "Złom" with no
 * expansion anywhere, while the same file held "Przyjęcie (PZ)" and
 * "Złomowanie" one key over. English readers got full names out of the same
 * component, so only Polish was encrypted — and a reader whose organization
 * runs the "home" profile is never assumed to have warehouse training.
 *
 * The approval-thresholds screen showed the same abbreviations while an
 * administrator decided which types need a workflow; it reads `types` too
 * now. The dense register rows keep `typesShort` deliberately.
 */
async function openMenu(triggerName: string) {
  const user = userEvent.setup();
  render(<NewDocumentMenu onSelect={() => {}} />);
  await act(async () => {
    await user.click(screen.getByRole("button", { name: triggerName }));
  });
}

describe("NewDocumentMenu — the type is named, not only coded", () => {
  it("offers the Polish name with its code in brackets (pl)", async () => {
    await withLanguage("pl", async () => {
      await openMenu("Nowy dokument");

      for (const name of [
        "Przyjęcie (PZ)",
        "Wydanie (WZ)",
        "Przesunięcie (MM)",
        "Przyjęcie wewnętrzne (PW)",
        "Rozchód wewnętrzny (RW)",
        "Złomowanie (ZL)",
      ]) {
        expect(screen.getByRole("menuitem", { name })).toBeInTheDocument();
      }
      // The code alone is not a menu entry any more.
      expect(screen.queryByRole("menuitem", { name: "PZ" })).toBeNull();
      expect(screen.queryByRole("menuitem", { name: "Złom" })).toBeNull();
    });
  });

  it("keeps the bare name in the languages that never had a code (en)", async () => {
    await openMenu("New document");

    expect(
      screen.getByRole("menuitem", { name: "Receipt" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("menuitem", { name: "Scrap" })).toBeInTheDocument();
  });
});

describe("NewDocumentMenu — the organization's own names", () => {
  it("adds the name the organization gave a type to its stock name", async () => {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { type_labels: { IN: "TESTNAME" } },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    await openMenu("New document");

    expect(
      screen.getByRole("menuitem", { name: "Receipt (TESTNAME)" }),
    ).toBeInTheDocument();
    // A type left unnamed keeps its stock name.
    expect(
      screen.getByRole("menuitem", { name: "Delivery" }),
    ).toBeInTheDocument();
  });

  it("never lets a bare preset code stand in for the name (en)", async () => {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { type_labels: { OUT: "WA", INT: "UML" } },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    await openMenu("New document");

    expect(
      screen.getByRole("menuitem", { name: "Delivery (WA)" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: "WA" })).toBeNull();
  });

  it("does not repeat a code the Polish name already carries (pl)", async () => {
    vi.mocked(profileHooks.useDocumentProfile).mockReturnValue({
      data: { type_labels: { IN: "PZ", OUT: "WZ" } },
    } as unknown as ReturnType<typeof profileHooks.useDocumentProfile>);
    await withLanguage("pl", async () => {
      await openMenu("Nowy dokument");

      expect(
        screen.getByRole("menuitem", { name: "Przyjęcie (PZ)" }),
      ).toBeInTheDocument();
      expect(
        screen.getByRole("menuitem", { name: "Wydanie (WZ)" }),
      ).toBeInTheDocument();
    });
  });
});
