import { describe, expect, it } from "vitest";
// The consume dialog reads the unit catalogue for its step, which is a
// query — so it needs the providers the app gives it.
import { render, screen } from "@/test/utils";
import { ConsumeDialog } from "@/modules/inventory/components/ConsumeDialog";
import { DeleteReasonDialog } from "@/modules/inventory/components/DeleteReasonDialog";
import i18n from "@/test/mocks/i18n";
import {
  CONSUMPTION_REASONS,
  DELETION_REASONS,
  STOCK_REASONS,
} from "@/modules/inventory/constants/stockReasons";
import type { Item } from "@/types";

const item = {
  id: "1",
  name: "Milk",
  quantity: 4,
} as unknown as Item;

/**
 * Two dialogs of one module asked "where did it go" with two lists of their
 * own, drawn from two key families — so "Used" was written twice and could
 * drift apart. The questions differ; the vocabulary must not.
 */
describe("the reasons a thing leaves the inventory", () => {
  it("draws both dialogs from one vocabulary", () => {
    for (const reason of [...DELETION_REASONS, ...CONSUMPTION_REASONS]) {
      expect(Object.values(STOCK_REASONS)).toContain(reason);
    }
  });

  it("spells a shared reason the same way in both", () => {
    const { unmount } = render(
      <DeleteReasonDialog
        open
        itemName="Milk"
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const inDelete = screen.getByRole("option", { name: "Consumed" });
    expect(inDelete).toHaveValue(STOCK_REASONS.USED);
    unmount();

    render(
      <ConsumeDialog
        open
        item={item}
        onConfirm={() => {}}
        onCancel={() => {}}
      />,
    );
    const inConsume = screen.getByRole("option", { name: "Consumed" });
    expect(inConsume).toHaveValue(STOCK_REASONS.USED);
  });

  it("keeps the two questions apart", () => {
    // A record goes for reasons a quantity never does, and the other way round.
    expect(DELETION_REASONS).toContain(STOCK_REASONS.TEST_DATA);
    expect(CONSUMPTION_REASONS).not.toContain(STOCK_REASONS.TEST_DATA);
    expect(CONSUMPTION_REASONS).toContain(STOCK_REASONS.DISPOSED);
    expect(DELETION_REASONS).not.toContain(STOCK_REASONS.DISPOSED);
  });

  // The gate: a new reason may only enter through STOCK_REASONS,
  // and entering it there without a translation means a raw code in the
  // dropdown of both dialogs — the dynamic key assembly is exactly what the
  // static key scan cannot see.
  it("translates every reason the vocabulary knows", () => {
    const t = i18n.getFixedT(null, "items");
    for (const reason of Object.values(STOCK_REASONS)) {
      expect(t(`deletionReasons.${reason}`)).not.toBe(
        `deletionReasons.${reason}`,
      );
    }
  });

  // The journal's side of the same vocabulary: the reason column
  // reads `common:settings.audit.reasons.<code>`, and the dialog and the
  // log must not drift apart. One vocabulary in the dialog is one
  // vocabulary in the log.
  it("names every reason in the journal's catalogue too", () => {
    const written = [...Object.values(STOCK_REASONS)];
    for (const language of ["en", "pl", "de", "fr", "es"]) {
      const tJournal = i18n.getFixedT(language, "common");
      for (const reason of written) {
        expect(
          tJournal(`settings.audit.reasons.${reason}`),
          `${language} ${reason}`,
        ).not.toBe(`settings.audit.reasons.${reason}`);
      }
    }
  });
});
