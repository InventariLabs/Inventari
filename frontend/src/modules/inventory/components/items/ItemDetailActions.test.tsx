import { render, screen } from "@/test/utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import { signInWith, signOut } from "@/test/auth";
import type { Item } from "@/types";
import { ItemDetailActions } from "./ItemDetailActions";

const item = {
  id: "item-1",
  name: "Olive oil",
  quantity: 3,
  location_id: "loc-1",
  organization_id: "org-1",
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
} as unknown as Item;

function renderActions() {
  return render(
    <ItemDetailActions
      item={item}
      inVirtualPlace={false}
      onEdit={vi.fn()}
      onDeleted={vi.fn()}
    />,
  );
}

/**
 * The product page's header actions ask for themselves: every one of them
 * writes, so a component that offered them on the strength of its parent's
 * question would offer them wherever it is mounted next.
 */
describe("ItemDetailActions", () => {
  afterEach(() => signOut());

  it("offers the stock actions, Edit and a separated Delete to a writer", () => {
    signInWith(["items:read", "items:write", "items:delete"]);
    renderActions();

    expect(
      screen.getAllByRole("button").map((b) => b.textContent?.trim()),
    ).toEqual(["Remove 1 unit", "Add 1 unit", "Move", "Edit", "Delete"]);
  });

  it("offers nothing to an account that cannot write", () => {
    signInWith(["items:read"]);
    const { container } = renderActions();

    expect(screen.queryByRole("button")).toBeNull();
    expect(container).toBeEmptyDOMElement();
  });
});
