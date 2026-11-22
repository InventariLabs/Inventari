/**
 * The language menu offers every language the app ships as an equal: each
 * arrives with its own name and nothing else. A language the community class
 * marks carries the share of the interface it holds; none does, so Portuguese
 * stands beside the other five with no mark and no percentage.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LanguageSelector } from "@/components/LanguageSelector";
import { LANGUAGES, communityCoverage } from "@/i18n/languages";

describe("LanguageSelector", () => {
  it("lists Português (Brasil) plain, like every other language", async () => {
    render(<LanguageSelector />);

    await userEvent.click(screen.getByRole("button", { name: /Language/ }));

    const portuguese = screen.getByRole("button", { name: /Português/ });
    expect(within(portuguese).queryByText(/community/i)).toBeNull();
    expect(within(portuguese).queryByText(/%/)).toBeNull();

    const polish = screen.getByRole("button", { name: "Polski" });
    expect(within(polish).queryByText(/community/i)).toBeNull();
  });

  it("marks no language as a community translation", () => {
    for (const language of LANGUAGES) {
      expect(communityCoverage(language.code)).toBeNull();
    }
  });
});
