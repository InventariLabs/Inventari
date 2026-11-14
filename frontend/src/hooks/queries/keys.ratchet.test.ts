import { describe, expect, it } from "vitest";

import { queryKeys } from "./keys";

/**
 * The namespaces `keys.ts` held when a module began owning its own query keys.
 *
 * A ratchet, not a dial: the list may shrink as a namespace moves into the
 * module that owns it, and does not grow. A new module keeps its keys in a
 * `queryKeys.ts` beside its hooks — `keys.ts` is a file every module PR would
 * otherwise edit, and the first two open at once conflict there. A namespace
 * that really belongs to Core (not to one module) is a decision a reviewer
 * makes; it is added here in the commit that adds it, and says why.
 */
const CORE_NAMESPACES = [
  "about",
  "admin",
  "aiConnections",
  "announcements",
  "apiKeys",
  "approvals",
  "attestation",
  "auditLog",
  "categories",
  "commandPalette",
  "documents",
  "equipment",
  "inventory",
  "items",
  "labels",
  "maker",
  "mealPlans",
  "modules",
  "notifications",
  "onboarding",
  "organization",
  "partners",
  "printing",
  "productTemplates",
  "purchaseOrders",
  "recipes",
  "roles",
  "settings",
  "shoppingLists",
  "stats",
  "stockAsOf",
  "stockLots",
  "stockMoves",
  "stockQuants",
  "stockTakes",
  "storages",
  "templatePreview",
  "templates",
  "uoms",
  "users",
  "webhooks",
];

describe("queryKeys namespaces", () => {
  it("takes no namespace for a module that is not already in it", () => {
    const added = Object.keys(queryKeys).filter(
      (name) => !CORE_NAMESPACES.includes(name),
    );
    expect(
      added,
      "Keep a module's query keys in modules/<name>/queryKeys.ts, not in hooks/queries/keys.ts",
    ).toEqual([]);
  });

  it("drops a namespace from the list once it has left keys.ts", () => {
    const gone = CORE_NAMESPACES.filter((name) => !(name in queryKeys));
    expect(gone, "Remove it from CORE_NAMESPACES").toEqual([]);
  });
});
