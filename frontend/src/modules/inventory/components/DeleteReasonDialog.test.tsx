/**
 * The delete confirmation used to say the same thing twice — title and body
 * were one sentence — and the two of them disagreed about what was being
 * deleted: the title said "product", the toast that followed said "item".
 */
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import en from "@/i18n/locales/en/items.json";
import { DeleteReasonDialog } from "./DeleteReasonDialog";

describe("DeleteReasonDialog", () => {
  it("does not repeat its title in its body", () => {
    render(
      <DeleteReasonDialog
        open
        itemName="Rack 42U"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const title = screen.getByText(en.actions.confirmDelete);
    const body = screen.getByText(en.messages.deleteGoesToArchive);
    expect(title.textContent).not.toBe(body.textContent);
  });

  it("does not call a reversible operation irreversible", () => {
    // The old body opened with "This cannot be undone" and kept
    // talking in the next breath about the archive it lands in, where a
    // Restore button gives the product back with everything.
    render(
      <DeleteReasonDialog
        open
        itemName="Rack 42U"
        onConfirm={vi.fn()}
        onCancel={vi.fn()}
      />,
    );

    const body = screen.getByText(en.messages.deleteGoesToArchive);
    expect(body.textContent).toMatch(/archive/i);
    expect(body.textContent).not.toMatch(/^this cannot be undone/i);
  });

  it("uses one noun for the thing it deletes", () => {
    // "product" in the title, "item" in the toast right after it, "record" in
    // the body: three words for one row.
    for (const sentence of [
      en.actions.confirmDelete,
      en.messages.deleteGoesToArchive,
      en.messages.itemDeleted,
      en.deleteItem,
    ]) {
      expect(sentence).not.toMatch(/\bitems?\b/i);
      expect(sentence).not.toMatch(/\brecords?\b/i);
    }
  });
});
