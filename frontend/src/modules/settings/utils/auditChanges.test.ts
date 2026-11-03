import { describe, expect, it } from "vitest";

import deCommon from "@/i18n/locales/de/common.json";
import enCommon from "@/i18n/locales/en/common.json";
import esCommon from "@/i18n/locales/es/common.json";
import frCommon from "@/i18n/locales/fr/common.json";
import plCommon from "@/i18n/locales/pl/common.json";
import plApprovals from "@/modules/approvals/i18n/pl.json";
import plEquipment from "@/modules/equipment/i18n/pl.json";
import plRecipes from "@/modules/recipes/i18n/pl.json";
import {
  auditChanges,
  auditFieldLabel,
  formatAuditValue,
  snapshotIdentity,
} from "./auditChanges";

const t = ((key: string, opts?: { defaultValue?: string }) => {
  const names: Record<string, string> = {
    "settings.audit.fields.quantity": "Quantity",
    "settings.audit.fields.uom_id": "Unit",
    "settings.audit.fields.meta_data": "Additional data",
  };
  return names[key] ?? opts?.defaultValue ?? key;
}) as unknown as Parameters<typeof auditFieldLabel>[1];

describe("auditFieldLabel", () => {
  it("names the shelf as the product form does", () => {
    const named = ((key: string, opts?: { defaultValue?: string }) =>
      ({
        "items:itemShelfLocation": "Shelf Location",
        "settings.audit.fields.shelf_location": "Shelf / position",
      })[key] ??
      opts?.defaultValue ??
      key) as unknown as Parameters<typeof auditFieldLabel>[1];

    expect(auditFieldLabel("shelf_location", named)).toBe("Shelf Location");
  });
});

describe("auditChanges equipment status", () => {
  it("reads the status sentinel as the absence it names", () => {
    // Rows written before the writers stopped recording UNKNOWN still
    // carry the literal; the journal line reads it as the dash the rest
    // of the app shows for a value that is not there.
    const changes = auditChanges(
      {
        before: { equipment_status: "UNKNOWN" },
        after: { equipment_status: "RETIRED" },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "equipment_status", from: "—", to: "RETIRED" },
    ]);
    expect(JSON.stringify(changes)).not.toContain("UNKNOWN");
  });
});

describe("auditChanges approval entries", () => {
  it("leads a decision with the decision and who took it, not the target", () => {
    // The row read "Stage order: 1 / Stages: 1" with the decision behind
    // "Show the whole change" and the target printed as JSON — which the
    // Target column already names by its number.
    const changes = auditChanges(
      {
        decision: "APPROVED",
        decided_by: "Piotr Kowalski",
        stage_order: 1,
        total_stages: 1,
        new_status: "APPROVED",
        approves: {
          type: "equipment_checkout",
          id: "6f1c1d1e-0000-4000-8000-000000000001",
          number: "Family laptop",
        },
      },
      "UPDATE",
    );

    expect(changes.slice(0, 2).map((change) => change.path)).toEqual([
      "decision",
      "decided_by",
    ]);
    expect(changes[1]?.to).toBe("Piotr Kowalski");
    expect(changes.map((change) => change.path)).not.toContain("approves");
  });

  it("names a workflow's new approver on the stage that changed", () => {
    const changes = auditChanges(
      {
        name: "approvals",
        subject: "workflow:equipment_checkout",
        before: { stages: { "1": { label: "Piotr", approvers: [] } } },
        after: {
          stages: { "1": { label: "Piotr", approvers: ["Piotr Kowalski"] } },
        },
      },
      "UPDATE",
    );

    expect(changes).toContainEqual({
      path: "stages.1.approvers",
      from: "—",
      to: "Piotr Kowalski",
    });
  });
});

describe("auditChanges value dictionaries", () => {
  // One event, one vocabulary. The item screen's history read `Dostępny →
  // Wycofany` while the organization journal read `AVAILABLE → RETIRED` for
  // the same change — two screens, two dictionaries, one status. The reader
  // goes through the dictionaries the owning screens ship, not a copy.
  const screenT = namespacedT({
    common: plCommon,
    equipment: plEquipment,
  }) as never;

  it("reads a built-in level the way the roles screen reads it", () => {
    const changes = auditChanges(
      { before: { role: "manager" }, after: { role: "user" } },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      { path: "role", from: "Manager", to: "Użytkownik" },
    ]);
  });

  it("reads an equipment status through the dictionary the asset screen owns", () => {
    const changes = auditChanges(
      {
        before: { equipment_status: "AVAILABLE" },
        after: { equipment_status: "RETIRED" },
      },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      { path: "equipment_status", from: "Dostępny", to: "Wycofany" },
    ]);
  });

  it("writes the unit a product template recorded in the interface language", () => {
    // The shape the template writer produces: the id, and the unit's symbol
    // beside it as `uom_name`.
    const changes = auditChanges(
      { name: "Soy candle", uom_id: "16282d80-0000", uom_name: "pcs" },
      "CREATE",
      undefined,
      screenT,
    );

    expect(changes).toContainEqual({ path: "uom_id", from: null, to: "szt." });
    expect(JSON.stringify(changes)).not.toContain("pcs");
  });

  it("keeps the symbol of a unit nobody translated", () => {
    const changes = auditChanges(
      { name: "Soy candle", uom_id: "16282d80-0000", uom_name: "tul" },
      "CREATE",
      undefined,
      screenT,
    );

    expect(changes).toContainEqual({ path: "uom_id", from: null, to: "tul" });
  });

  it("words a restore's deletion reason the way the archive does", () => {
    const changes = auditChanges(
      {
        before: { deletion_reason: "TEST_DATA" },
        after: { deletion_reason: null },
      },
      "RESTORE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      {
        path: "deletion_reason",
        from: plCommon.settings.audit.reasons.TEST_DATA,
        to: "—",
      },
    ]);
  });

  it("keeps a code no dictionary carries as the record wrote it", () => {
    const changes = auditChanges(
      {
        before: { equipment_status: "BORROWED BY ANNA" },
        after: { equipment_status: "RETIRED" },
      },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      { path: "equipment_status", from: "BORROWED BY ANNA", to: "Wycofany" },
    ]);
  });

  it("reads a document type the way the document screens read it", () => {
    // The journal wrote the enum code: "Type: INTERNAL_OUT", "Type:
    // CORRECTION" — words the document screens never show the reader.
    const changes = auditChanges(
      { before: { type: "IN" }, after: { type: "INTERNAL_OUT" } },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      {
        path: "type",
        from: "Przyjęcie (PZ)",
        to: "Rozchód wewnętrzny (RW)",
      },
    ]);
  });

  it("reads an empty value as the dash of a value that is not there", () => {
    // `Opis: abc →` printed nothing where every other row prints `—`.
    const changes = auditChanges(
      { before: { description: "abc" }, after: { description: "" } },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([{ path: "description", from: "abc", to: "—" }]);
  });
});

describe("auditChanges select-field options", () => {
  // A seeded select field stores the option as written ("Yes") and the form
  // says it through `items:fieldOptions.<field>.<option>`. The history read
  // the stored word raw, so a Polish reader saw "Yes → No" under a Polish
  // label.
  const itemsT = namespacedT({
    items: {
      fieldOptions: { lactose_free: { No: "Nie", Yes: "Tak" } },
    },
  }) as never;

  it("reads a seeded field's options the way the form says them", () => {
    const changes = auditChanges(
      {
        before: { meta_data: { lactose_free: "No" } },
        after: { meta_data: { lactose_free: "Yes" } },
      },
      "UPDATE",
      undefined,
      itemsT,
    );

    expect(changes).toEqual([
      { path: "meta_data.lactose_free", from: "Nie", to: "Tak" },
    ]);
  });

  it("leaves an option nobody catalogued as the organization wrote it", () => {
    const changes = auditChanges(
      {
        before: { meta_data: { shelf_zone: "Cold" } },
        after: { meta_data: { shelf_zone: "Frozen" } },
      },
      "UPDATE",
      undefined,
      itemsT,
    );

    expect(changes).toEqual([
      { path: "meta_data.shelf_zone", from: "Cold", to: "Frozen" },
    ]);
  });
});

describe("auditChanges scan session journal", () => {
  const screenT = namespacedT({ common: plCommon }) as never;

  it("names the session keys and reads the status in the reader's word", () => {
    const snapshot = {
      number: "OUT/2026/005",
      wms_session_id: "8b1c2f3e-0d4a-4a52-9a41-6a0d52a7c1f0",
      wms_session_status: "cancelled",
      wms_session_discarded: ["Gouda Cheese: 8"],
      wms_session_handed_over_from: "Anna",
      wms_session_handed_over_to: "Jan",
    };

    const changes = auditChanges(snapshot, "UPDATE", undefined, screenT);

    expect(changes.map((change) => [change.path, change.to])).toEqual([
      ["wms_session_id", "8b1c2f3e"],
      ["wms_session_status", "Anulowana"],
      ["wms_session_discarded", "Gouda Cheese: 8"],
      ["wms_session_handed_over_from", "Anna"],
      ["wms_session_handed_over_to", "Jan"],
    ]);
    expect(
      changes.map((change) =>
        auditFieldLabel(change.path, catalogueT(plCommon)),
      ),
    ).toEqual([
      "Sesja skanowania",
      "Status sesji",
      "Odrzucone skany",
      "Przekazana od",
      "Przekazana do",
    ]);
  });

  it("labels the journal keys in every supported language", () => {
    const keys = [
      "wms_session_id",
      "wms_session_status",
      "wms_session_discarded",
      "wms_session_handed_over_from",
      "wms_session_handed_over_to",
      "picked_together",
      "held_quantity",
      "discrepancy_code",
      "discrepancy_reason",
    ];

    for (const catalog of [enCommon, plCommon, deCommon, frCommon, esCommon]) {
      for (const key of keys) {
        expect(auditFieldLabel(key, catalogueT(catalog))).not.toBe(key);
      }
    }
  });

  it("keeps a session status nobody listed as it was written", () => {
    const changes = auditChanges(
      { wms_session_status: "parked" },
      "UPDATE",
      undefined,
      screenT,
    );

    expect(changes).toEqual([
      { path: "wms_session_status", from: null, to: "parked" },
    ]);
  });
});

describe("auditChanges", () => {
  it("names only the paths that moved inside a dictionary", () => {
    // The whole document used to be printed on both sides of the arrow: a
    // product's nutrition data from a food database, twice, in one cell.
    const changes = auditChanges(
      {
        before: {
          meta_data: { nutrition: { fat: 1.8, carbs: 20 }, source: "off" },
        },
        after: {
          meta_data: { nutrition: { fat: 2.1, carbs: 20 }, source: "off" },
        },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "meta_data.nutrition.fat", from: "1.8", to: "2.1" },
    ]);
  });

  it("says nothing about a field that holds the same value on both sides", () => {
    const changes = auditChanges(
      {
        before: { name: "Canned peas", quantity: 1 },
        after: { name: "Canned peas", quantity: 3 },
      },
      "UPDATE",
    );

    expect(changes).toEqual([{ path: "quantity", from: "1", to: "3" }]);
  });

  it("notices a key that only one side has", () => {
    const changes = auditChanges(
      { before: {}, after: { group_label: "COLD" } },
      "UPDATE",
    );

    expect(changes).toEqual([{ path: "group_label", from: "—", to: "COLD" }]);
  });

  it("reads a CREATE as what the record came into the world with", () => {
    const changes = auditChanges(
      { name: "Rice", quantity: 2, description: "", price: 0 },
      "CREATE",
    );

    // The name is the Target column's job; empties and zeroes are not facts.
    expect(changes).toEqual([{ path: "quantity", from: null, to: "2" }]);
  });

  it("reads a flat snapshot on UPDATE as the record of what happened", () => {
    // An UPDATE row with a flat snapshot printed "—" — the stock
    // take's close carried four counters and the cell showed nothing.
    const changes = auditChanges(
      {
        name: "QAF16 spis tolerancja 10",
        counted_items: 8,
        adjusted_items: 2,
        over_cap_accepted: 0,
        over_tolerance_accepted: 1,
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "counted_items", from: null, to: "8" },
      { path: "adjusted_items", from: null, to: "2" },
      { path: "over_tolerance_accepted", from: null, to: "1" },
    ]);
  });

  it("reads a document confirmation's flat snapshot as a status change", () => {
    // The other measured shape: a document confirmed names its new status.
    const changes = auditChanges(
      {
        number: "INT/2026/002",
        new_status: "CONFIRMED",
        requires_approval: false,
        approval_workflow_configured: false,
      },
      "UPDATE",
    );

    // The number is what the Target column shows this row is about, so it is
    // not also a change line — the same rule a name has always followed.
    expect(changes).toEqual([
      { path: "new_status", from: null, to: "CONFIRMED" },
      { path: "requires_approval", from: null, to: "false" },
      {
        path: "approval_workflow_configured",
        from: null,
        to: "false",
      },
    ]);
  });

  it("reads a create's reference by the name the snapshot hung beside it", () => {
    // The journal writes `parent_name` next to `parent_id` at the moment of
    // the write. `Parent: 67d57628` is not an answer a reader can use.
    const changes = auditChanges(
      {
        name: "Probe Shelf",
        parent_id: "67d57628-1111-2222-3333-444455556666",
        parent_name: "Main Warehouse",
      },
      "CREATE",
    );

    // One line about the parent, named — not two, and not the uuid.
    expect(changes).toEqual([
      { path: "parent_id", from: null, to: "Main Warehouse" },
    ]);
  });

  it("names both sides of a move from the pair the snapshot carries", () => {
    const changes = auditChanges(
      {
        name: "QA Item",
        before: {
          parent_id: "67d57628-1111-2222-3333-444455556666",
          parent_name: "Old shelf",
        },
        after: {
          parent_id: "84f70f85-1111-2222-3333-444455556666",
          parent_name: "New shelf",
        },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "parent_id", from: "Old shelf", to: "New shelf" },
    ]);
  });

  it("still shortens an id the snapshot left unnamed", () => {
    const changes = auditChanges(
      {
        before: { location_id: "67d57628-1111-2222-3333-444455556666" },
        after: { location_id: "84f70f85-1111-2222-3333-444455556666" },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "location_id", from: "67d57628", to: "84f70f85" },
    ]);
  });

  it("reads a category in the word its code translates to", () => {
    // A seeded category carries its seed's English name and is *read* by its
    // code — the product screen says "Nabiał" where the record says "Dairy".
    // The journal writes both, so it can say the word the screen says.
    const labels: Record<string, string> = {
      "categories:codes.dairy": "Nabiał",
      "categories:codes.cheese": "Ser",
    };
    const translate = ((key: string, opts?: { defaultValue?: string }) =>
      labels[key] ?? opts?.defaultValue ?? key) as unknown as Parameters<
      typeof auditChanges
    >[3];

    const changes = auditChanges(
      {
        name: "Milk",
        before: {
          category_id: "67d57628-1111-2222-3333-444455556666",
          category_name: "Dairy",
          category_code: "dairy",
        },
        after: {
          category_id: "84f70f85-1111-2222-3333-444455556666",
          category_name: "Cheese",
          category_code: "cheese",
        },
      },
      "UPDATE",
      undefined,
      translate,
    );

    // One line, named — the code is how the name reads, not a change of its
    // own.
    expect(changes).toEqual([
      { path: "category_id", from: "Nabiał", to: "Ser" },
    ]);
  });

  it("keeps the name written down when no catalogue knows the code", () => {
    const translate = ((_key: string, opts?: { defaultValue?: string }) =>
      opts?.defaultValue ?? "") as unknown as Parameters<
      typeof auditChanges
    >[3];

    const changes = auditChanges(
      {
        name: "Milk",
        category_id: "67d57628-1111-2222-3333-444455556666",
        category_name: "Dairy",
        category_code: "a_code_no_language_has",
      },
      "CREATE",
      undefined,
      translate,
    );

    expect(changes).toEqual([{ path: "category_id", from: null, to: "Dairy" }]);
  });

  it("drops a line where nothing turned into nothing", () => {
    // The edit form posts its whole state, so an untouched description arrived
    // as "" beside a column holding NULL and the row read `Description: — →`
    // — a change of nothing into nothing, which on a location move was the
    // line that pushed the parent under "Show the whole change".
    const changes = auditChanges(
      {
        before: { description: null, parent_id: null, parent_name: null },
        after: { description: "", parent_id: null, parent_name: null },
      },
      "UPDATE",
    );

    expect(changes).toEqual([]);
  });

  it("reads a custom role taken away as the role it named, not a dash", () => {
    // A custom role is removed over the built-in path, so the level reads the
    // same on both sides and the reference is the only thing that moved. The
    // name beside the id is what makes the row say which role went away
    // instead of showing `—` in the Detail column.
    const changes = auditChanges(
      {
        name: "member@example.com",
        before: {
          role: "user",
          role_id: "67d57628-1111-2222-3333-444455556666",
          role_name: "Magazynier",
        },
        after: { role: "user" },
      },
      "UPDATE",
    );

    expect(changes).toEqual([{ path: "role_id", from: "Magazynier", to: "—" }]);
  });

  it("names the custom role a swap took away, with no level to carry it", () => {
    // The other direction: one custom role replaced by another. It arrives as
    // `role_id` alone, and the level reads the same on both sides — so unless
    // the role that went away is named here, the row says one role is held
    // and the other never was.
    const changes = auditChanges(
      {
        name: "member@example.com",
        before: {
          role: "user",
          role_id: "67d57628-1111-2222-3333-444455556666",
          role_name: "Magazynier",
        },
        after: {
          role: "user",
          role_id: "84f70f85-1111-2222-3333-444455556666",
        },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "role_id", from: "Magazynier", to: "84f70f85" },
    ]);
  });

  it("keeps the context beside a change, so it says which line moved", () => {
    // A recipe's ingredient line: "Qty per batch: 2 → 5" about a recipe with
    // nine ingredients is not an answer. The field naming the line is a fact,
    // not a difference, so it reads the way a create's fields do.
    const changes = auditChanges(
      {
        name: "Powidła śliwkowe",
        ingredient: "Śliwki węgierki",
        before: { qty_per_batch: 2 },
        after: { qty_per_batch: 5 },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "qty_per_batch", from: "2", to: "5" },
      { path: "ingredient", from: null, to: "Śliwki węgierki" },
    ]);
  });

  it("does not print a change dictionary as JSON", () => {
    // What the maker's own `{changed: {field: {from, to}}}` shape used to
    // get: `Changed: {"qty_per_batch":{"from":2,"to":5}}`, one cell, one
    // reader, no meaning. The shape is gone from the writer; this pins the
    // reading side against it coming back.
    const changes = auditChanges(
      {
        name: "Powidła śliwkowe",
        before: { uom: null },
        after: { uom: "kg" },
      },
      "UPDATE",
    );

    expect(changes).toEqual([{ path: "uom", from: "—", to: "kg" }]);
    expect(JSON.stringify(changes)).not.toContain('from\\":');
  });

  it("reads a nested setting written for the first time as its fields", () => {
    // A module's settings snapshot takes the schema default for a key the
    // record did not hold yet, and an object field has no default: the entry
    // arrived as `jina: null → {api_key}`. Walking only pairs where BOTH
    // sides are objects printed the whole value — `Jina: — →
    // {"api_key":"**********"}` — with the field name, the only part a reader
    // can act on, lost inside the JSON.
    const changes = auditChanges(
      {
        name: "recipes",
        before: { jina: null },
        after: { jina: { api_key: "**********" } },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "jina.api_key", from: "—", to: "**********" },
    ]);
  });

  it("reads a nested setting that was cleared as the fields that went", () => {
    const changes = auditChanges(
      {
        name: "recipes",
        before: { jina: { api_key: "**********" } },
        after: { jina: null },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      { path: "jina.api_key", from: "**********", to: "—" },
    ]);
  });

  it("names a record by its number when it has no name", () => {
    expect(snapshotIdentity({ number: "IN/2026/009" })).toBe("IN/2026/009");
  });

  it("prefers the name where a record carries both", () => {
    expect(snapshotIdentity({ name: "Milk", number: "X/1" })).toBe("Milk");
  });

  it("hands back nothing for a snapshot that names no record", () => {
    expect(snapshotIdentity({ quantity: 4 })).toBeNull();
    expect(snapshotIdentity({ name: "  " })).toBeNull();
    expect(snapshotIdentity(null)).toBeNull();
  });

  it("gives up on depth rather than following a document forever", () => {
    const deep = (leaf: unknown) => ({ a: { b: { c: { d: leaf } } } });
    const changes = auditChanges(
      { before: deep({ e: 1 }), after: deep({ e: 2 }) },
      "UPDATE",
    );

    expect(changes).toHaveLength(1);
    expect(changes[0].path).toBe("a.b.c.d");
  });

  it("skips the envelope's own before/after when they sit inside a field", () => {
    // A nested snapshot that wrapped its own two sides — `meta: {before,
    // after, x}` — used to be read as the record's fields, `Meta › before
    // › …` in place of what moved. The names are the envelope's at every
    // depth, never a field of the record; `meta.x` is one, and it is the
    // same on both sides here, so the entry moved nothing.
    const changes = auditChanges(
      {
        before: { meta: { before: { a: 1 }, after: { b: 1 }, x: 1 } },
        after: { meta: { before: { a: 2 }, after: { b: 2 }, x: 1 } },
      },
      "UPDATE",
    );

    expect(changes).toEqual([]);
  });
});

describe("the changed-fields list on a journal line", () => {
  it("reads the fields list through the field catalogue", () => {
    // The item update writes which fields moved beside the two sides, and
    // the line printed the names raw — "Pola: brand" — while the very
    // same names, met as change lines, read in the reader's language. The
    // elements are field names, so they go through the same catalogue; a
    // field no catalogue names stays raw, visible, not blanked out.
    const changes = auditChanges(
      {
        name: "Canned peas",
        before: { quantity: 2, brand: "Heinz" },
        after: { quantity: 5, brand: "Bonduelle" },
        fields: ["quantity", "brand"],
      },
      "UPDATE",
      undefined,
      t,
    );

    expect(changes).toContainEqual({
      path: "fields",
      from: null,
      to: "Quantity, brand",
    });
  });

  it("does not repeat a field the diff already speaks as flat context", () => {
    // Moving a webhook's address: the snapshot carries the url flat beside
    // the two sides, and the line used to appear twice under one key.
    const changes = auditChanges(
      {
        name: "Orders hook",
        url: "https://example.com/hook-moved",
        before: { url: "https://example.com/hook" },
        after: { url: "https://example.com/hook-moved" },
      },
      "UPDATE",
    );

    expect(changes).toEqual([
      {
        path: "url",
        from: "https://example.com/hook",
        to: "https://example.com/hook-moved",
      },
    ]);
  });

  it("keeps a flat field the diff does not speak as context", () => {
    const changes = auditChanges(
      {
        name: "Orders hook",
        url: "https://example.com/hook",
        before: { is_active: true },
        after: { is_active: false },
      },
      "UPDATE",
    );

    expect(changes.map((change) => change.path)).toEqual(["is_active", "url"]);
  });

  it("reads the list the same way when the entry is all context", () => {
    // The template bind writes the list without the two sides — a flat
    // snapshot — and flatFields reads both shapes, so the flat one gets
    // the catalogue too.
    const changes = auditChanges(
      { fields: ["quantity"] },
      "UPDATE",
      undefined,
      t,
    );

    expect(changes).toEqual([{ path: "fields", from: null, to: "Quantity" }]);
  });

  it("keeps the raw list when no translator is given", () => {
    // Without a reader there is no catalogue to consult; the value reads
    // as it always did. Green both ways — it pins the no-t shape.
    const changes = auditChanges({ fields: ["quantity"] }, "UPDATE");

    expect(changes).toEqual([{ path: "fields", from: null, to: "quantity" }]);
  });
});

describe("formatAuditValue", () => {
  it("rounds a float back to the number somebody meant", () => {
    // A nutrition figure stored as a 32-bit float reads back with eighteen
    // digits of rounding artefact.
    expect(formatAuditValue(1.7999999523162842)).toBe("1.8");
  });

  it("keeps a small value that rounding to a few places would flatten", () => {
    expect(formatAuditValue(0.0001234)).toBe("0.0001234");
  });

  it("leaves whole numbers alone", () => {
    expect(formatAuditValue(20)).toBe("20");
  });

  it("prints the store's decimal string as the number it stands for", () => {
    // One journal row read "Quantity: 0 → 2.000": the number typed beside
    // the database's own scale. Both sides are now the reader's number —
    // no trailing zeros the store kept, no separator the store used.
    expect(formatAuditValue("2.000")).toBe("2");
    expect(formatAuditValue("0.500")).toBe("0.5");
  });

  it("shortens an id it cannot name", () => {
    expect(formatAuditValue("1245b1db-1111-2222-3333-444455556666")).toBe(
      "1245b1db",
    );
  });

  it("names an id when the page knows one", () => {
    expect(
      formatAuditValue("1245b1db-1111-2222-3333-444455556666", (uuid) =>
        uuid.startsWith("1245") ? "Kilograms" : null,
      ),
    ).toBe("Kilograms");
  });

  it("prints a timestamp the way the column beside it does", () => {
    // `deadline: 2026-09-25T23:59:59.999999+00:00` used to reach the reader
    // exactly as written — microseconds, offset and all — in a column whose
    // every other row says "18.09.2026, 14:41". The exact rendering is the
    // formatter's business; what this pins is that it is no longer ISO.
    const printed = formatAuditValue("2026-09-25T23:59:59.999999+00:00");

    expect(printed).not.toContain("T23:59:59");
    expect(printed).not.toContain("+00:00");
    expect(printed).toContain("2026");
  });

  it("leaves a date it cannot parse alone rather than losing it", () => {
    expect(formatAuditValue("2026-09")).toBe("2026-09");
    expect(formatAuditValue("not-a-date")).toBe("not-a-date");
  });

  it("keeps a day a day — no midnight invented for it", () => {
    // `expiry_date` carries `2026-01-01` and nothing else. Read as a
    // timestamp it printed "01/01/2026, 12:00 AM", a moment nobody
    // recorded, on a field the journal shows for a date somebody picked.
    expect(formatAuditValue("2026-01-01")).not.toContain(":");
    expect(formatAuditValue("2026-01-01")).toContain("2026");
  });

  it("reads a code the catalogue knows as the word it stands for", () => {
    const translate = ((key: string, opts?: { defaultValue?: string }) =>
      key === "common:settings.audit.values.ALL"
        ? "Wszystkie"
        : (opts?.defaultValue ?? key)) as unknown as Parameters<
      typeof formatAuditValue
    >[2];

    expect(formatAuditValue("ALL", undefined, translate)).toBe("Wszystkie");
  });

  it("leaves a code the catalogue does not know as it arrived", () => {
    expect(formatAuditValue("PENDING_RETRY", undefined, t)).toBe(
      "PENDING_RETRY",
    );
  });
});

describe("auditFieldLabel", () => {
  it("uses the translation when the catalog has one", () => {
    expect(auditFieldLabel("uom_id", t)).toBe("Unit");
  });

  it("prints an unnamed field as the record wrote it", () => {
    // The fallback used to tidy `storage_location_id` into "Storage
    // location" — a shape no reader can tell from a translated label, which
    // is how forty fields went out in English in a Polish journal.
    expect(auditFieldLabel("min_quantity", t)).toBe("min_quantity");
    expect(auditFieldLabel("storage_location_id", t)).toBe(
      "storage_location_id",
    );
  });

  it("keeps a nested path's parents so the value has an origin", () => {
    expect(auditFieldLabel("meta_data.nutrition.fat", t)).toBe(
      "Additional data › nutrition › fat",
    );
  });

  it("names a module's setting the way its own settings screen names it", () => {
    // The row for a module's settings change tidied the stored key into
    // "Allow admin self approve" — words the reader could not find on any
    // screen, in a language the interface never showed. The module's schema
    // carries the key its own settings screen renders.
    const titles = {
      allow_admin_self_approve: "approvals:settings.allowAdminSelfApprove",
      "ai.purposeLabel": "recipes:ai.purposeLabel",
    };
    const moduleT = namespacedT({ approvals: plApprovals, recipes: plRecipes });

    expect(auditFieldLabel("allow_admin_self_approve", moduleT, titles)).toBe(
      "Administrator może zatwierdzać własne wnioski",
    );
    // A nested path — `AI › Purpose label` — is a title of its own, not
    // the parent's, so the leaf is what the schema is asked about.
    expect(auditFieldLabel("ai.purposeLabel", moduleT, titles)).toBe(
      plRecipes.ai.purposeLabel,
    );
  });

  it("prints the key itself when the module names that field nothing", () => {
    // The schema map is asked first, but an entry it does not name is not
    // tidied into "Threshold days": the reader gets the word the record
    // wrote, which is also what they get with no map at all.
    expect(auditFieldLabel("threshold_days", t, {})).toBe("threshold_days");
    expect(auditFieldLabel("threshold_days", t)).toBe("threshold_days");
  });
});

/** The page's translator over a real catalogue: the words a reader gets. */
function catalogueT(catalog: unknown): Parameters<typeof auditFieldLabel>[1] {
  const lookup = (key: string, opts?: { defaultValue?: string }): string => {
    const leaf = key
      .split(".")
      .reduce<unknown>(
        (node, segment) =>
          typeof node === "object" && node !== null
            ? (node as Record<string, unknown>)[segment]
            : undefined,
        catalog,
      );
    return typeof leaf === "string" ? leaf : (opts?.defaultValue ?? key);
  };
  return lookup as unknown as Parameters<typeof auditFieldLabel>[1];
}

/**
 * The same translator, for the keys a module writes: `approvals:settings.x`.
 *
 * A module's title key is namespace-prefixed, exactly as the settings screen
 * hands it to `t`, so a catalogue keyed by module is what has to answer it.
 */
function namespacedT(
  catalogues: Record<string, unknown>,
): Parameters<typeof auditFieldLabel>[1] {
  const lookups: Record<string, Parameters<typeof auditFieldLabel>[1]> = {};
  for (const [namespace, catalog] of Object.entries(catalogues)) {
    lookups[namespace] = catalogueT(catalog);
  }
  const lookup = (key: string, opts?: { defaultValue?: string }): string => {
    const [namespace, path] = key.split(":");
    const scoped = path === undefined ? undefined : lookups[namespace];
    return scoped ? scoped(path, opts) : (opts?.defaultValue ?? key);
  };
  return lookup as unknown as Parameters<typeof auditFieldLabel>[1];
}

describe("the labels a role change prints", () => {
  it("gives the custom role its own line in every supported language", () => {
    // A custom → built-in swap printed "Role" on both lines: the removed
    // role's line had no catalogue entry and fell back to its tidied
    // identifier, which is English in every language. The label that names
    // the custom role is its own key now, and it is not the level's.
    const expected: Array<[unknown, string]> = [
      [enCommon, "Custom role"],
      [plCommon, "Rola własna"],
      [deCommon, "Eigene Rolle"],
      [frCommon, "Rôle personnalisé"],
      [esCommon, "Rol personalizado"],
    ];

    for (const [catalog, label] of expected) {
      expect(auditFieldLabel("role_id", catalogueT(catalog))).toBe(label);
      expect(auditFieldLabel("role", catalogueT(catalog))).not.toBe(label);
    }
  });

  it("keeps the two lines of a custom → built-in swap apart", () => {
    const changes = auditChanges(
      {
        name: "member@example.com",
        before: {
          role: "user",
          role_id: "67d57628-1111-2222-3333-444455556666",
          role_name: "Magazynier",
        },
        after: { role: "manager" },
      },
      "UPDATE",
    );
    const labels = changes.map((change) =>
      auditFieldLabel(change.path, catalogueT(plCommon)),
    );

    // `role` now has an entry of its own ("Rola"); before that it fell
    // through to the tidied identifier and read "Role" in Polish too.
    expect(labels).toEqual(["Rola", "Rola własna"]);
  });
});

describe("the labels the recipe journal prints", () => {
  // The keys the maker recipe journal writes into its snapshots (see
  // recipe_service's log_recipe_change calls). A key the catalogue does not
  // name is now printed as the record wrote it — `ingredient_added` — which
  // is the same word in all five languages, so the guard stands: the journal
  // has to name these itself.
  const recipeJournalKeys = [
    "ingredient_added",
    "ingredient_removed",
    "output",
    "copied_from_culinary_recipe",
    "lines",
    "lines_removed",
    "cost_line_added",
    "cost_line_removed",
  ];

  const catalogues: Array<[string, unknown]> = [
    ["en", enCommon],
    ["pl", plCommon],
    ["de", deCommon],
    ["fr", frCommon],
    ["es", esCommon],
  ];

  it.each(catalogues)("names every journal key in %s", (_language, catalog) => {
    const translator = catalogueT(catalog);
    for (const key of recipeJournalKeys) {
      expect(
        translator(`settings.audit.fields.${key}`, { defaultValue: "" }),
      ).not.toBe("");
    }
  });

  it("does not read the tidied identifier on a Polish screen", () => {
    const translator = catalogueT(plCommon);
    expect(auditFieldLabel("ingredient_added", translator)).not.toBe(
      "Ingredient added",
    );
    expect(auditFieldLabel("output", translator)).not.toBe("Output");
  });
});

describe("a rotated secret on a journal line", () => {
  const rotation = {
    before: { jina: { api_key: "**********" } },
    after: { jina: { api_key: "ROTATED_VALUE" } },
  };

  it("reads as a change, not as a dash", () => {
    // Both sides masked to the same ten asterisks, and the line was
    // dropped as `X → X`: a key that had just been replaced left the
    // Details column showing "—". The value is still not printed.
    const changes = auditChanges(
      rotation,
      "UPDATE",
      undefined,
      namespacedT({ common: plCommon }) as never,
    );

    expect(changes).toHaveLength(1);
    expect(changes[0].path).toBe("jina.api_key");
    expect(changes[0].from).toBe("**********");
    expect(changes[0].to).not.toBe(changes[0].from);
  });

  it("says it in the reader's language, never the sentinel", () => {
    for (const [language, catalog] of [
      ["pl", plCommon],
      ["en", enCommon],
      ["de", deCommon],
      ["fr", frCommon],
      ["es", esCommon],
    ] as const) {
      const changes = auditChanges(
        rotation,
        "UPDATE",
        undefined,
        namespacedT({ common: catalog }) as never,
      );
      // The catalogue's own sentence, not the key and not the sentinel:
      // a translator that silently answers with the key it was handed
      // would satisfy "not the sentinel" and still print gibberish.
      expect(changes[0].to, language).toBe(
        catalog.settings.audit.secretChanged,
      );
      expect(changes[0].to, language).not.toContain("ROTATED_VALUE");
      expect(changes[0].to, language).not.toContain(":");
    }
  });

  it("still shows nothing where the secret did not move", () => {
    const changes = auditChanges(
      {
        before: { jina: { api_key: "**********" }, threshold: 1 },
        after: { jina: { api_key: "**********" }, threshold: 2 },
      },
      "UPDATE",
      undefined,
      namespacedT({ common: plCommon }) as never,
    );

    expect(changes.map((change) => change.path)).toEqual(["threshold"]);
  });
});

describe("formatAuditValue booleans", () => {
  // "Analytics enabled: true → false" is English grammar wearing a Polish
  // label: a boolean is an answer, and the journal reads answers in the
  // interface's language like every other value it prints. The key carries
  // its `common:` namespace: the reader is reached from screens whose
  // translator is bound elsewhere — the item card reads with `items`.
  const catalogueT = namespacedT({
    common: plCommon,
  }) as unknown as Parameters<typeof formatAuditValue>[2];

  it("reads a boolean through the catalogue", () => {
    expect(formatAuditValue(true, undefined, catalogueT)).toBe("Tak");
    expect(formatAuditValue(false, undefined, catalogueT)).toBe("Nie");
  });

  it("reads both sides of a toggled setting in the interface's language", () => {
    const changes = auditChanges(
      {
        before: { enable_analytics: true },
        after: { enable_analytics: false },
      },
      "UPDATE",
      undefined,
      catalogueT as never,
    );

    expect(changes[0]).toEqual({
      path: "enable_analytics",
      from: "Tak",
      to: "Nie",
    });
    expect(JSON.stringify(changes)).not.toContain(": true");
  });

  it("keeps the raw literal when no catalogue is loaded yet", () => {
    // Boot order: the spinner can show before translations arrive, and the
    // journal row cannot do better than the literal it was handed.
    expect(formatAuditValue(true)).toBe("true");
  });

  it("every catalogue carries the pair in all five languages", () => {
    for (const [language, common] of Object.entries({
      en: enCommon,
      pl: plCommon,
      de: deCommon,
      es: esCommon,
      fr: frCommon,
    })) {
      const values = (
        common as { settings: { audit: { values: Record<string, string> } } }
      ).settings.audit.values;
      expect(values.YES, language).toBeTruthy();
      expect(values.NO, language).toBeTruthy();
    }
  });
});

/**
 * The module catalogues, keyed `<module>/<language>`, so a test can ask a
 * list what it calls a code without twenty static imports.
 */
const moduleBundles = import.meta.glob<{ default: Record<string, unknown> }>(
  "../../*/i18n/*.json",
  { eager: true },
);

function moduleBundle(
  module: string,
  language: string,
): Record<string, unknown> {
  const path = `../../${module}/i18n/${language}.json`;
  const found = moduleBundles[path];
  if (!found) throw new Error(`missing module catalogue ${path}`);
  return found.default;
}

/** A dictionary as string→string, for the maps the lists read. */
function wordMap(value: unknown): Record<string, string> {
  return value as Record<string, string>;
}

describe("formatAuditValue statuses", () => {
  // The journal printed the code the backend stores — "Nowy status:
  // CONFIRMED" beside "Poprzedni status: …", in a column that spells every
  // other value the way the reader's interface does. A status is not a
  // code to the reader: the list that owns the record shows a word, and
  // the journal reads the dictionary that list reads.
  const CATALOGUES = {
    en: enCommon,
    pl: plCommon,
    de: deCommon,
    fr: frCommon,
    es: esCommon,
  } as const;

  /** The five codes a document, an order and a production run move through. */
  const ORDER_STATUSES = [
    "DRAFT",
    "PENDING_APPROVAL",
    "CONFIRMED",
    "COMPLETED",
    "CANCELLED",
  ] as const;

  /** The codes an approval request moves through, and its keys in the list. */
  const APPROVAL_STATUSES: Array<[string, string]> = [
    ["PENDING", "pending"],
    ["IN_PROGRESS", "inProgress"],
    ["APPROVED", "approved"],
    ["REJECTED", "rejected"],
  ];

  /** The codes an asset's status machine moves through. */
  const ASSET_STATUSES = [
    "AVAILABLE",
    "DEPLOYED",
    "MAINTENANCE",
    "RETIRED",
  ] as const;

  it("reads a confirmed order as the word its own list shows", () => {
    // The measured defect: a confirmed purchase order read
    // "Nowy status: CONFIRMED" while the order list beside it said
    // "Potwierdzone". The journal had no word for the code at all.
    expect(
      formatAuditValue(
        "CONFIRMED",
        undefined,
        namespacedT({ common: plCommon }) as never,
      ),
    ).toBe("Potwierdzone");
  });

  it("says the change, not the code, on a confirmed order's line", () => {
    const changes = auditChanges(
      { number: "PO/2026/001", new_status: "CONFIRMED" },
      "UPDATE",
      undefined,
      namespacedT({ common: plCommon }) as never,
    );

    expect(changes).toContainEqual({
      path: "new_status",
      from: null,
      to: "Potwierdzone",
    });
    expect(JSON.stringify(changes)).not.toContain("CONFIRMED");
  });

  it.each(Object.entries(CATALOGUES))(
    "%s reads each status through the dictionary its list reads",
    (language, common) => {
      const values = wordMap(
        (common as { settings: { audit: { values: unknown } } }).settings.audit
          .values,
      );
      const documents = wordMap(moduleBundle("warehouse", language).status);
      const orders = wordMap(moduleBundle("purchase_orders", language).status);
      const approvals = wordMap(moduleBundle("approvals", language).request);
      const equipment = moduleBundle("equipment", language);
      const campaign = wordMap(
        (equipment.attestation as Record<string, unknown>).status,
      );
      const assets = wordMap(equipment.status);

      for (const code of ORDER_STATUSES) {
        expect(values[code], `${language} ${code}`).toBe(documents[code]);
        // One code, one word: the order list and the document list were
        // written apart and agree on every one of the five.
        expect(values[code], `${language} ${code}`).toBe(orders[code]);
      }
      for (const [code, key] of APPROVAL_STATUSES) {
        expect(values[code], `${language} ${code}`).toBe(approvals[key]);
      }
      // An attestation is the one record whose "closed" is not the
      // order's "completed" (Zamknięta against Zakończone): one code
      // cannot carry two words, and the row names the record it is about.
      expect(values.ACTIVE, `${language} ACTIVE`).toBe(campaign.ACTIVE);
      for (const code of ASSET_STATUSES) {
        expect(values[code], `${language} ${code}`).toBe(
          assets[code.toLowerCase()],
        );
      }
    },
  );
});
