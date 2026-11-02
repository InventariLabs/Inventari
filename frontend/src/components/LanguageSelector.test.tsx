/**
 * The language menu tells a reader which translations are the community's:
 * a language that ships below full coverage carries a mark and the share of
 * the interface it has, a maintained one carries nothing.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { LanguageSelector } from "@/components/LanguageSelector";
import { communityCoverage } from "@/i18n/languages";

describe("LanguageSelector", () => {
  it("marks a community language with its coverage and leaves the others plain", async () => {
    render(<LanguageSelector />);

    await userEvent.click(screen.getByRole("button", { name: /Language/ }));

    const community = screen.getByRole("button", { name: /Português/ });
    expect(
      within(community).getByText(
        `Community translation · ${communityCoverage("pt")}%`,
      ),
    ).toBeTruthy();

    const maintained = screen.getByRole("button", { name: "Polski" });
    expect(within(maintained).queryByText(/Community translation/)).toBeNull();
  });

  it("states no coverage for a maintained language", () => {
    expect(communityCoverage("pl")).toBeNull();
    expect(communityCoverage("pt")).toBeTypeOf("number");
  });
});
