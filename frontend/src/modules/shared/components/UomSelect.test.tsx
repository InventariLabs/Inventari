import { describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { render, screen } from "@/test/utils";
import { withLanguage } from "@/test/mocks/i18n";
import { UomSelect } from "./UomSelect";
import { Sheet } from "@/components/ui/Sheet";
import type { Uom } from "@/types";

// The catalogue the picker offers; what this spec measures is the word it
// writes for one of them, not how the list is fetched.
vi.mock("@/modules/shared/hooks/useUoms", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  useUoms: () => ({
    data: [
      {
        id: "cat-units",
        name: "Units",
        uoms: [
          {
            id: "uom-pcs",
            name: "Piece",
            symbol: "pcs",
            category_id: "cat-units",
            factor: 1,
            rounding: "1.000000",
          },
        ],
      },
    ],
    isLoading: false,
  }),
}));

const PIECE = {
  id: "uom-pcs",
  name: "Piece",
  symbol: "pcs",
  category_id: "cat-units",
  category_name: "Units",
  factor: 1,
  rounding: "1.000000",
} as unknown as Uom;

/**
 * The word for a unit comes from one catalogue, and every reader takes it
 * from there.
 *
 * This picker used to read its own — `items:uomSymbols`, keyed by the unit's
 * *name* rather than its symbol, and neither mirrored in the backend nor
 * covered by `check-units-labels`. Both said "szt." on the day they were
 * written, which is exactly the state a guard exists for: a word changed on
 * the canonical side would have left the picker saying the old one, beside a
 * list that had moved on.
 */
describe("UomSelect", () => {
  it("writes the unit the way the canonical catalogue does", async () => {
    await withLanguage("pl", () => {
      render(<UomSelect value={PIECE.id} onChange={() => {}} />);

      // common:units.pcs — the one the backend mirrors and the gate guards.
      expect(screen.getAllByText("szt.").length).toBeGreaterThan(0);
      expect(screen.queryByText("pcs")).toBeNull();
      // and the unit's name from the catalogue that translates names
      expect(screen.getByText("Sztuka")).toBeInTheDocument();
    });
  });

  /**
   * The compact trigger shows a symbol, and an `aria-label` of "Unit"
   * replaced it in the name: a voice user saying "pcs" reached nothing
   * (WCAG 2.5.3). The field's name leads and the shown symbol follows.
   */
  it("keeps the shown symbol in the compact trigger's name", () => {
    render(<UomSelect compact value={PIECE.id} onChange={() => {}} />);

    const trigger = screen.getByRole("button", { name: /^Unit pcs/ });
    expect(trigger).not.toHaveAttribute("aria-label");
  });

  it("closes the modal sheet on Escape", async () => {
    const user = userEvent.setup();
    render(<UomSelect value={PIECE.id} onChange={() => {}} />);

    await user.click(screen.getAllByRole("button")[0]);
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("leaves the form sheet around it open when Escape closes the picker", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Sheet open onClose={onClose} aria-label="Add to list">
        <UomSelect value={PIECE.id} onChange={() => {}} />
      </Sheet>,
    );

    await user.click(screen.getByRole("button", { name: /piece/i }));
    expect(screen.getByRole("dialog", { name: "Unit" })).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Unit" })).toBeNull();
    expect(onClose).not.toHaveBeenCalled();
    expect(
      screen.getByRole("dialog", { name: "Add to list" }),
    ).toBeInTheDocument();

    // The next press is the form's.
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
