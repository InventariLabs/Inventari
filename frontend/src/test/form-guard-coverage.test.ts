import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  mkdirSync,
  mkdtempSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join, relative, sep } from "node:path";

/**
 * The nav-leave guard (`useNavLeaveGuard`, fed by
 * `useFormGuardStore.setDirtyForm`) protects one class of form: one that
 * lives on the page, where an ordinary click on a navigation tab walks out
 * of the route and everything typed is gone. That is what happened here:
 * the product form lost the reader's work in silence while the asset form,
 * two screens over, asked.
 *
 * This check keeps the class from eroding. It scans the module trees for
 * multi-field form components and requires every one of them to either
 * arm the guard itself or carry a reasoned entry in ALLOWED_BARE below —
 * the documented survey of why not. A NEW multi-field form fails here
 * until it calls `useFormGuard` (one line, see `AddEquipmentPage` /
 * `AddItemPage`) or is added to the survey with a reason a reviewer can
 * judge.
 *
 * The class is wider than the page, measured live: a sheet form
 * (the new-recipe sheet) traps clicks on the page's navigation tabs — the
 * backdrop eats them before the router sees them — but the command palette
 * opens over the sheet, its results go through `guardNavigate`, and the
 * route changed under a form full of typed work with no question asked.
 * A dialog or sheet therefore exempts nothing: the same arming is due.
 * The old blanket exemption for `Dialog`/`Sheet`/`Drawer` forms rested on
 * the false half of that measurement and is gone.
 *
 * The scan is a heuristic, and says so: field components are matched by
 * name, so a form built from unknown primitives slips past it. It slipped
 * on `WorkflowSettingsPage`, whose stages come from `ApprovalWorkflowEditor`
 * and which therefore showed two fields to the scan while the reader typed a
 * name, a target type and a stage list into it. A screen pass found that
 * one by hand, not here. The last case below is the answer: the consumers
 * the guard is known to have are named, so a heuristic that stops seeing one
 * of them fails instead of going quiet. What the scan cannot miss is the
 * class the guard is for — forms assembled from the shared field kit.
 */

const FIELD =
  /<(Input|Textarea|Select|Checkbox|DateInput|NumberInput|SearchableCombobox|LocationCombobox|RadioGroup|Switch|DynamicFieldRenderer|UnifiedFieldRenderer|MetadataFields|UnitQuantityInput|EditableList|ProductFormContent)\b/g;
// A call, not a mention: the evidence is read from code with comments
// stripped, so a comment naming `setDirtyForm` proves nothing.
const GUARD = /\b(setDirtyForm|useFormGuard|useNavLeaveGuard)\s*\(/;
const FIELD_BAR = 4;
// Every directory that can hold a form. No file-name filter: a form named
// `OrganizationSettings` or `ProbeScreen` is as much a form as `FooPage`.
const ROOTS = ["src/modules", "src/components"];

// Source with comments and string-literal contents blanked, so only code is
// left to match. A mention in a comment or in a string (`"useFormGuard("`)
// is not a call. Quoted strings end at a line break, which bounds the damage
// of an apostrophe in JSX text to its own line.
function stripComments(text: string): string {
  let out = "";
  let i = 0;
  while (i < text.length) {
    const c = text[i];
    const two = text.slice(i, i + 2);
    if (two === "//") {
      while (i < text.length && text[i] !== "\n") i++;
    } else if (two === "/*") {
      const end = text.indexOf("*/", i + 2);
      i = end < 0 ? text.length : end + 2;
    } else if (c === '"' || c === "'" || c === "`") {
      out += c;
      i++;
      while (i < text.length && text[i] !== c) {
        if (text[i] === "\\") i++;
        else if (text[i] === "\n" && c !== "`") break;
        i++;
      }
      if (text[i] === c) out += c;
      i++;
    } else {
      out += c;
      i++;
    }
  }
  return out;
}

function fieldCount(text: string): number {
  return stripComments(text).match(FIELD)?.length ?? 0;
}

/**
 * Multi-field files under `roots` that neither call the guard nor sit in
 * `allowed`. A dialog, sheet or drawer in the file exempts nothing: the
 * guard is due wherever the fields are, so a page form with a delete
 * confirmation dialog beside it is still found.
 */
function findBare(
  roots: string[],
  base: string,
  allowed: Record<string, string>,
): string[] {
  const bare: string[] = [];
  for (const root of roots) {
    for (const file of walk(join(base, root))) {
      const text = readFileSync(file, "utf8");
      if (fieldCount(text) < FIELD_BAR) continue;
      if (GUARD.test(stripComments(text))) continue;
      const rel = relative(base, file).split(sep).join("/");
      if (allowed[rel]) continue;
      bare.push(rel);
    }
  }
  return bare;
}

/**
 * Multi-field forms the scan finds, with the reason they do not arm the
 * nav-leave guard. Two honest shapes live here.
 *
 * Fields hosted by a parent's dialog: the component renders fields only —
 * the dialog that would arm the guard belongs to the composition root, and
 * the entry names it.
 *
 * Dialog forms recorded bare: since the palette-over-sheet measurement a dialog or
 * sheet exempts nothing (the palette reaches the gate over it), but arming
 * needs a dirty comparator the form does not have. Its state is local
 * `useState`, and the edit variants among these are prefilled from the
 * record they edit — a naive "differs from empty" compare would ask on
 * values nobody typed, which is the exact wrong question this guard exists
 * for. Each entry says so per form rather than behind a class-wide excuse;
 * arming one is a small change plus an entry removal.
 */
const ALLOWED_BARE: Record<string, string> = {
  // ── Fields hosted by a parent's dialog ─────────────────────────────────
  "src/modules/warehouse/components/DocumentFormatSettings.tsx":
    "FIELDS: the numbering format and the document type names, mounted inside Configuration's Advanced disclosure; DocumentProfileSettingsPage arms the guard for every section through SettingsSaveBar.",
  "src/modules/warehouse/components/DocumentFormFields.tsx":
    "FIELDS: the fields of DocumentFormModal's dialog; the dialog is the arming site.",
  "src/modules/warehouse/components/DocumentQuickAddPanel.tsx":
    "FIELDS: panel inside DocumentLinesEditor, which lives in DocumentFormModal's dialog; the dialog is the arming site.",
  "src/modules/inventory/components/items/ProductFormContent.tsx":
    "The product form's fields. Its composition roots own the guard: AddItemPage armed against this form's isDirty through useQuickAdd, which arms for both its consumers (the page and QuickAddModal); ItemEditModal mounts the same fields inside a dialog and is its own arming site.",
  "src/modules/settings/components/ai/AiConnectionFields.tsx":
    "FIELDS: fields of AiConnectionFormModal's dialog; the dialog is the arming site.",
  "src/modules/warehouse/components/receive/ReceiveLineRow.tsx":
    "FIELDS: one line's count, price, lot and expiry inside ReceiveGoodsPage's sheet; the page arms the guard for the sheet.",
  "src/modules/shared/components/LineItemsEditor/LineItemOptionalPanel.tsx":
    "FIELDS: line-level fields inside DocumentFormModal's dialog; the dialog is the arming site.",
  "src/modules/shared/components/LineItemsEditor/LineItemValueFields.tsx":
    "FIELDS: line-level fields inside DocumentFormModal's dialog; the dialog is the arming site.",
  "src/modules/spaces/components/StorageWizardStepContent.tsx":
    "FIELDS: step content of StorageWizard, which renders the dialog and is the arming site.",
  "src/modules/spaces/components/storages/StorageEditFields.tsx":
    "FIELDS: fields of the storage edit dialog; the dialog is the arming site.",
  "src/modules/webhooks/components/WebhookForm.tsx":
    "FIELDS: form inside the webhook sheet on WebhooksPage; the sheet is the arming site.",
  "src/modules/equipment/components/DynamicFieldsCard.tsx":
    "FIELDS: a controlled view — values and onChange come from the asset form, whose page arms the guard (AddEquipmentPage); this file holds no state of its own.",
  "src/modules/equipment/components/PurchaseNotesSection.tsx":
    "FIELDS: a controlled view — the purchase fields are props of the asset form (`form`, `onSet`), whose page arms the guard (AddEquipmentPage).",
  "src/modules/inventory/components/labels/LabelSettingsSidebar.tsx":
    "FIELDS: a controlled view of print settings inside LabelPreviewModal; nothing is typed that outlives the preview, and the settings state belongs to the modal.",
  "src/modules/shared/components/BarcodeLabelSheet.tsx":
    "BARE: print settings for a preview — a size, copies and one switch, each starting at a default; nothing typed outlives the download, and a preset click restores the size. Recorded bare, not exempt — the palette reaches the gate over this sheet.",
  "src/modules/recipes/components/RecipeIngredientRow.tsx":
    "FIELDS: one row of RecipeForm's ingredient list, controlled through onUpdate; RecipeForm arms the guard for the whole list.",
  // ── Dialog forms recorded bare (the palette reaches over them) ────────
  "src/modules/equipment/components/CheckoutModal.tsx":
    "BARE: fields prefilled from the asset being checked out; a naive compare asks on values nobody typed. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/equipment/components/CreateCampaignModal.tsx":
    "BARE: create form on local state with no dirty tracking; arming needs its comparator. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/equipment/components/ImportEquipmentModal.tsx":
    "BARE: an import preview over parsed rows; the reader's work is the mapping fields, and its dirty shape is its own decision. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/equipment/components/MaintenanceLogModal.tsx":
    "BARE: log form on local state with no dirty tracking; arming needs its comparator. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/equipment/components/ModelEditModal.tsx":
    "BARE: edit form prefilled from the model; a naive compare asks on values nobody typed. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/inventory/components/items/BulkEditModal.tsx":
    "BARE: bulk edit over a selection, prefilled from it; a naive compare asks on values nobody typed. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/partners/components/PartnerFormModal.tsx":
    "BARE: create/edit form, the edit variant prefilled from the partner; a naive compare asks on values nobody typed. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/purchase_orders/components/PricelistFormModal.tsx":
    "BARE: a controlled view — the form state lives in the parent page's `form` prop, so the arming site is that composition root, not this file. Recorded bare, not exempt — the palette reaches the gate over this sheet.",
  "src/modules/purchase_orders/components/ReorderRuleFormModal.tsx":
    "BARE: a controlled view — the form state lives in the parent page's `form` prop, so the arming site is that composition root, not this file. Recorded bare, not exempt — the palette reaches the gate over this sheet.",
  "src/modules/recipes/components/ImportReviewModal.tsx":
    "BARE: review of rows parsed from a file; the reader's decisions are accept/reject per row and the dirty shape is its own decision. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  "src/modules/stock_takes/components/StockTakeCreateModal.tsx":
    "BARE: create form on local state with no dirty tracking; arming needs its comparator. Recorded bare, not exempt — the palette reaches the gate over this dialog.",
  // ── Page class, reasoned ───────────────────────────────────────────────
  "src/modules/equipment/components/BulkAddPanel.tsx":
    "PAGE: holds its own entry rows, which the asset page's dirty comparator does not track. Arming the route guard on it needs the panel's state lifted or its own wiring — recorded bare rather than pretending the page's guard covers it.",
  "src/modules/recipes/pages/ConversionAddForm.tsx":
    "PAGE: a two-field inline add-row on the conversions page — the commit is one explicit Add click away, below the bar of multi-field work this guard exists for.",
  "src/modules/settings/components/SettingsEmailTab.tsx":
    "PAGE: the SMTP section saves section-scoped settings whose absent-vs-present distinction is server state; a dirty definition has to compare against the server record, not the mount snapshot, so wiring it is its own decision.",
};

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...walk(full));
    } else if (full.endsWith(".tsx") && !full.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("the nav-leave guard covers the multi-field forms", () => {
  it("every multi-field form arms the guard or carries a reasoned exemption", () => {
    expect(
      findBare(ROOTS, process.cwd(), ALLOWED_BARE),
      "Multi-field forms found that neither arm the nav-leave guard nor " +
        "carry a reason in ALLOWED_BARE (form-guard-coverage.test.ts). " +
        "Wire them — `setDirtyForm(isDirty ? label : null)` with cleanup, " +
        "as in AddItemPage — or add them to the survey with a reason.",
    ).toEqual([]);
  });

  describe("the detector has teeth", () => {
    const fields = Array.from({ length: 6 }, () => "<Input />").join("");
    let base: string;

    beforeEach(() => {
      base = mkdtempSync(join(tmpdir(), "form-guard-"));
      for (const dir of ROOTS) mkdirSync(join(base, dir), { recursive: true });
    });
    afterEach(() => rmSync(base, { recursive: true, force: true }));

    // The probe is imported by a real page: a detector that only sees
    // orphans would pass these, so the page is part of every case.
    function plant(rel: string, body: string) {
      mkdirSync(join(base, rel, ".."), { recursive: true });
      writeFileSync(join(base, rel), body);
      writeFileSync(
        join(base, "src/modules/x/RealPage.tsx"),
        `import P from "../../../${rel.replace(/\.tsx$/, "")}"; export default () => <P />;`,
      );
    }
    const form = (extra = "") =>
      `export default function F() { ${extra} return <div>${fields}</div>; }`;

    it("sees src/components", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant("src/components/__probe/ProbeForm.tsx", form());
      expect(findBare(ROOTS, base, {})).toEqual([
        "src/components/__probe/ProbeForm.tsx",
      ]);
    });

    it("sees a form whatever its file is called", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant("src/modules/x/ProbeScreen.tsx", form());
      expect(findBare(ROOTS, base, {})).toEqual([
        "src/modules/x/ProbeScreen.tsx",
      ]);
    });

    it("counts a call, not a mention in a comment", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant(
        "src/modules/x/ProbeForm.tsx",
        form("// TODO setDirtyForm(null)\n/* useFormGuard( */"),
      );
      expect(findBare(ROOTS, base, {})).toEqual([
        "src/modules/x/ProbeForm.tsx",
      ]);
    });

    it("counts a call, not a mention inside a string literal", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant(
        "src/modules/x/ProbeForm.tsx",
        form('const s = "useFormGuard(false)"; const t = `setDirtyForm(`;'),
      );
      expect(findBare(ROOTS, base, {})).toEqual([
        "src/modules/x/ProbeForm.tsx",
      ]);
    });

    it("accepts a form that really calls the guard", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant("src/modules/x/ProbeForm.tsx", form("useFormGuard(false);"));
      expect(findBare(ROOTS, base, {})).toEqual([]);
    });

    it("a page form with a confirmation dialog beside it is still found", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant(
        "src/modules/x/ProbeForm.tsx",
        `export default function F() { return <div>${fields}<Dialog open={false} /></div>; }`,
      );
      expect(findBare(ROOTS, base, {})).toEqual([
        "src/modules/x/ProbeForm.tsx",
      ]);
    });

    it("a modal form with the guard at its root passes", () => {
      mkdirSync(join(base, "src/modules/x"), { recursive: true });
      plant(
        "src/modules/x/ProbeModal.tsx",
        `export default function M() { useFormGuard(false); return <Dialog>${fields}</Dialog>; }`,
      );
      expect(findBare(ROOTS, base, {})).toEqual([]);
    });
  });

  it("the survey's entries all point at files the scan still recognises", () => {
    // A stale entry (the form renamed, the fields moved out) would keep
    // guarding nothing while reading as covered — the list must only name
    // forms the scan can still see.
    const stale: string[] = [];
    for (const rel of Object.keys(ALLOWED_BARE)) {
      const text = readFileSync(join(process.cwd(), rel), "utf8");
      if (fieldCount(text) >= FIELD_BAR) continue;
      stale.push(rel);
    }
    expect(stale).toEqual([]);
  });

  it("the guard's known consumers still report to it", () => {
    // Every form known to hold page-level work: the two originals, the
    // product form and the approval path form. If any stops mentioning the
    // guard, the wiring was dropped and the coverage test above has nothing
    // to believe in — and for the approval path the scan above would not
    // notice, which is why this list exists.
    for (const rel of [
      "src/modules/approvals/pages/WorkflowSettingsPage.tsx",
      "src/modules/equipment/pages/AddEquipmentPage.tsx",
      // The product form's guard lives in the hook both its consumers share
      // (AddItemPage's page form and QuickAddModal) — the page no longer
      // wires it itself.
      "src/modules/inventory/hooks/useQuickAdd.ts",
      "src/modules/recipes/components/RecipeForm.tsx",
      "src/modules/stock_takes/hooks/useStockTakeCounting.ts",
      // Two dirty cards on one screen; their flags meet one useFormGuard at
      // the page, or the first card going clean disarms the second's question.
      "src/modules/settings/components/OrganizationSettings.tsx",
      // Every section of a settings page that has one Save reports through it.
      "src/components/ui/SettingsSaveBar.tsx",
    ]) {
      expect(
        GUARD.test(
          stripComments(readFileSync(join(process.cwd(), rel), "utf8")),
        ),
        rel,
      ).toBe(true);
    }
  });
});
