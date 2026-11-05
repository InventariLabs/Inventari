import { afterEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n/config";
import { act, render, screen } from "@/test/utils";
import { UnitChoiceDialog } from "./UnitChoiceDialog";
import type { PendingUnitChoice } from "@/modules/inventory/hooks/useItemForm";

const choice = {
  template: { productName: "Mąka", uomSymbol: "pcs" },
  chosenSymbol: "pcs",
} as unknown as PendingUnitChoice;

describe("UnitChoiceDialog", () => {
  afterEach(async () => {
    await act(() => i18n.changeLanguage("en"));
  });

  it("names both units the way the reader's language writes them", async () => {
    await act(() => i18n.changeLanguage("pl"));

    render(<UnitChoiceDialog choice={choice} onResolve={vi.fn()} />);

    expect(
      screen.getByRole("button", { name: "Wpisz w szt." }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Zostaw szt." }),
    ).toBeInTheDocument();
    expect(screen.getByText(/jest prowadzony w szt\./)).toBeInTheDocument();
    expect(screen.queryByText(/\bpcs\b/)).not.toBeInTheDocument();
  });
});
