/**
 * The delete confirmation says each thing once, and the title and the toast
 * name what is deleted the same way.
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
    // The body does not open with "This cannot be undone", and it names the
    // archive it lands in, where a
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
