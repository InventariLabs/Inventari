import { SYSTEM_FIELDS } from "@/config/systemFields";
import { auditChanges } from "@/modules/settings/utils/auditChanges";
import type { FieldDefinition } from "@/types";
import type { TranslateFn } from "@/types/i18n";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";

/** Just enough of i18next's `t` for a row of this timeline. */
type Translate = TranslateFn;

/**
 * What a reader needs besides the row itself.
 *
 * `locationName` resolves the ids a MOVED or an UPDATED row carries — the
 * caller holds the storage list; the fallback is a shortened id for a
 * location that is gone.
 */
interface ReadContext {
  t: Translate;
  locationName?: (id: string) => string | undefined;
  /** The record's own unit; a row's numbers are written in it. */
  unit?: HistoryUnit;
}

/** The unit of the record the timeline belongs to. */
export interface HistoryUnit {
  symbol?: string | null;
  rounding?: string | null;
}

/**
 * A quantity as the history holds it: the exact digits as a string, which is
 * how every quantity is written; a number in rows written before that.
 */
type Amount = number | string;

/**
 * An amount written the way the card writes it: with the record's unit.
 *
 * A row's numbers are in the unit of the record they belong to, but the
 * payload does not carry it — "290.667 → 499" left the reader to guess
 * between grams and pieces. Without a unit in hand the number stays bare,
 * though still in the reader's number format ("1,5" where the language
 * writes a comma).
 */
function amountText(amount: Amount, { t, unit }: ReadContext): string {
  return formatQuantityLocalized(t, amount, unit?.symbol, unit?.rounding);
}

type ChangeReader = (
  changes: Record<string, unknown>,
  ctx: ReadContext,
) => string;

/**
 * Human name for a field key recorded in an UPDATED row.
 *
 * Three sources, in the order a reader benefits from: the item's own field
 * catalog, then the journal's shared catalog, then the identifier tidied up.
 * The last one exists so that a column name never reaches the screen —
 * `storage_location_id` reads as "Storage location", not as itself.
 *
 * Nested paths keep their parents, so `meta_data.nutrition.fat` still says
 * which document the figure came out of.
 */
function fieldDisplayName(key: string, t: Translate): string {
  const segments = key.split(".");
  return segments
    .map((segment, index) => {
      const sys = SYSTEM_FIELDS[segment] as
        Partial<FieldDefinition> | undefined;
      if (sys?.label) {
        const translated = t(sys.label, { defaultValue: "" });
        if (translated) return translated;
      }
      // A custom field of the product form (`meta_data.lactose_free`) is
      // named by the form's own catalogue entry, so the history says what the
      // form says. Only below `meta_data`: the same catalogue also holds
      // form captions ("Unit (pcs, kg, …)") that are not field names.
      if (segments[index - 1] === "meta_data") {
        const custom = t(`items:fields.${segment}`, { defaultValue: "" });
        if (custom) return custom;
      }
      const shared = t(`common:settings.audit.fields.${segment}`, {
        defaultValue: "",
      });
      if (shared) return shared;
      const words = segment.replace(/_id$/, "").replace(/_/g, " ").trim();
      return words ? words[0].toUpperCase() + words.slice(1) : segment;
    })
    .join(" › ");
}

/** The reason a write carried, said the way the rest of the app says it. */
function reasonText(reason: string, t: Translate): string {
  return t(`deletionReasons.${reason}`, { defaultValue: reason });
}

function readMoved(
  changes: Record<string, unknown>,
  { t, locationName }: ReadContext,
): string {
  const nameOf = (id: string | undefined) =>
    id ? (locationName?.(id) ?? id.slice(0, 8)) : undefined;
  const from = nameOf(changes.from as string | undefined);
  const to = nameOf(changes.to as string | undefined);
  if (from && to) return `${from} → ${to}`;
  if (from) return `${t("items:history.from")}: ${from}`;
  if (to) return `${t("items:history.to")}: ${to}`;
  return "";
}

function readQuantityChanged(
  changes: Record<string, unknown>,
  ctx: ReadContext,
): string {
  const { t } = ctx;
  const oldQty = changes.old as Amount | undefined;
  const newQty = changes.new as Amount | undefined;
  const parts: string[] = [];
  if (oldQty !== undefined && newQty !== undefined) {
    parts.push(`${amountText(oldQty, ctx)} → ${amountText(newQty, ctx)}`);
  }
  // The journal shows the same event with its reason; this row used to
  // keep only the numbers, though the write carried the why — a stock
  // take correction names itself and, when the counter picked one, the
  // code for what the count found. One event, one story, both screens.
  const reason = changes.reason as string | undefined;
  if (reason) {
    // A production run's reason is a code, and the code carries no number:
    // two runs on one day would read the same without it.
    const run = changes.production_order_number as string | undefined;
    const label = t(`common:settings.audit.reasons.${reason}`, {
      defaultValue: reason,
    });
    parts.push(run ? `${label} ${run}` : label);
  }
  const discrepancyCode = changes.discrepancy_reason_code as string | undefined;
  if (discrepancyCode) {
    parts.push(
      t(`stock_takes:reasons.discrepancy.codes.${discrepancyCode}`, {
        defaultValue: discrepancyCode,
      }),
    );
  }
  return parts.join(" · ");
}

/**
 * How much left, why, and what the person typed about it.
 *
 * The quantity alone answers "how much left", never "why it left" — the
 * reason the dialog made the reader pick is the one thing that turns the
 * row into an answer.
 */
function removalText(
  quantity: Amount | undefined,
  reason: string | undefined,
  notes: string | undefined,
  ctx: ReadContext,
): string {
  const { t } = ctx;
  const parts: string[] = [];
  if (quantity !== undefined) parts.push(amountText(quantity, ctx));
  if (reason) parts.push(reasonText(reason, t));
  if (notes) parts.push(`„${notes}"`);
  return parts.join(" · ");
}

/** A quantity leaving the shelf: USED or DISPOSED. */
function readRemoval(
  changes: Record<string, unknown>,
  ctx: ReadContext,
): string {
  return removalText(
    changes.qty as Amount | undefined,
    changes.reason as string | undefined,
    changes.notes as string | undefined,
    ctx,
  );
}

/**
 * The record itself leaving the list, and coming back.
 *
 * These two describe undoing a mistake, and they were the only two actions
 * the reader had no branch for: they fell through to the dictionary dump
 * while a row about eating the same product read as a sentence. A deletion
 * carries the same three things a consumption does, under another key.
 */
function readDeleted(
  changes: Record<string, unknown>,
  ctx: ReadContext,
): string {
  return removalText(
    changes.old_quantity as Amount | undefined,
    changes.reason as string | undefined,
    changes.notes as string | undefined,
    ctx,
  );
}

/**
 * A restore says where the record came back from, and why it had gone.
 *
 * The write also carries the moment of the deletion; the row above it in the
 * same list already carries that moment in the reader's own format, so an
 * ISO string here would only be the same fact spelled less legibly.
 */
function readRestored(
  changes: Record<string, unknown>,
  { t }: ReadContext,
): string {
  const parts = [t("items:history.restoredFromArchive")];
  const previous = changes.previous_deletion_reason as string | undefined;
  if (previous) parts.push(reasonText(previous, t));
  return parts.join(" · ");
}

/**
 * An opened package says how much was left, in the unit it was said in.
 *
 * The row above already carries the moment and the record the unit was split
 * from is a UUID nobody reads, so only the amount is worth a line.
 */
function readOpened(
  changes: Record<string, unknown>,
  { t }: ReadContext,
): string {
  const left = changes.left as Amount | undefined;
  if (left === undefined) return "";
  if (Number(left) === 0) return t("items:history.openedNothingLeft");
  const unit = changes.left_unit as string | undefined;
  return t("items:history.openedLeft", {
    amount: formatQuantityLocalized(t, left, unit),
  });
}

function readCreated(
  changes: Record<string, unknown>,
  ctx: ReadContext,
): string {
  const qty = changes.quantity as number | undefined;
  // `count` still picks the plural form; the number itself is printed with
  // the record's unit, in the reader's format.
  return qty
    ? ctx.t("items:history.createdWith", {
        count: qty,
        amount: amountText(qty, ctx),
      })
    : "";
}

/**
 * A scan-created row names the code that minted it.
 *
 * The scan writes the label code, the barcode and the photo marker — never
 * a quantity, which is what the plain created reader looks for here, so a
 * scan-created row answered with an empty line under its action. A row
 * carrying nothing the scan can name stays quiet: the action label beside
 * it already says "Created via scan".
 */
function readCreatedViaScan(
  changes: Record<string, unknown>,
  { t }: ReadContext,
): string {
  const labelCode = changes.label_code as string | undefined;
  if (labelCode) {
    return t("items:history.createdViaScan.label", { code: labelCode });
  }
  const barcode = changes.barcode as string | undefined;
  if (barcode) {
    return t("items:history.createdViaScan.barcode", { code: barcode });
  }
  if (changes.via_vision_ai) {
    return t("items:history.createdViaScan.photo");
  }
  return "";
}

/**
 * An update names what moved, with both sides of the arrow.
 *
 * The organization journal renders this same event correctly and always did:
 * it walks the two snapshots and keeps the leaves that differ. This timeline
 * listed the union of their keys instead, so an edit sheet that PUTs the
 * whole record reported sixteen changed fields for one changed letter. The
 * difference engine is shared rather than written a second time.
 */
function readUpdated(
  changes: Record<string, unknown>,
  { t, locationName }: ReadContext,
): string {
  const oldValues = changes.old as Record<string, unknown> | null;
  const newValues = changes.new as Record<string, unknown> | null;
  // The translator names what the journal names: a boolean reads as the
  // word the catalogue carries, and an enum code reads through the same
  // values catalogue. The reference resolver stays for the id a snapshot
  // recorded no name beside — and an id nothing can name reads as the
  // dash, never as eight characters of a UUID.
  const resolve = (id: string) => locationName?.(id) ?? "";
  return auditChanges(
    { before: oldValues ?? {}, after: newValues ?? {} },
    "UPDATED",
    resolve,
    t,
  )
    .map(
      (change) =>
        `${fieldDisplayName(change.path, t)}: ${change.from ?? "—"} → ${change.to}`,
    )
    .join(" · ");
}

/**
 * A scan that added stock to an existing record names the barcode and the
 * numbers it moved.
 *
 * The scan writes the barcode, the quantity before, the quantity after and
 * the increment. Read as a sentence: the arrow and the plus sign say what
 * happened in the language the rest of the timeline speaks, and the barcode
 * answers "which code did this" — the one question the row's label cannot.
 */
function readQuantityIncreasedViaScan(
  changes: Record<string, unknown>,
  ctx: ReadContext,
): string {
  const { t } = ctx;
  const oldQty = changes.old_quantity as Amount | undefined;
  const newQty = changes.new_quantity as Amount | undefined;
  const increment = changes.increment as Amount | undefined;
  const parts: string[] = [];
  if (oldQty !== undefined && newQty !== undefined) {
    let step = `${amountText(oldQty, ctx)} → ${amountText(newQty, ctx)}`;
    if (increment !== undefined) step += ` (+${amountText(increment, ctx)})`;
    parts.push(step);
  }
  const barcode = changes.barcode as string | undefined;
  if (barcode) {
    parts.push(
      t("items:history.quantityIncreasedViaScan.barcode", { code: barcode }),
    );
  }
  return parts.join(" · ");
}

/** The last resort: a row written by something this reader does not know. */
function readUnknown(changes: Record<string, unknown>): string {
  return Object.entries(changes)
    .map(([key, value]) => `${key}: ${JSON.stringify(value)}`)
    .join(", ");
}

/**
 * An equipment transition, with the model's word for "no status" read as
 * the dash it is: UNKNOWN names an absence, and printed verbatim it looks
 * like a state nobody ever told the reader about. Real states take the
 * vocabulary the asset timeline speaks, so one event reads the same way
 * on both screens.
 */
function readStatusChanged(
  changes: Record<string, unknown>,
  { t }: ReadContext,
): string {
  const side = (value: unknown) =>
    typeof value === "string" && value !== "UNKNOWN"
      ? t(`equipment:status.${value.toLowerCase()}`, { defaultValue: value })
      : "—";
  return `${side(changes.old_status)} → ${side(changes.new_status)}`;
}

export const READERS: Record<string, ChangeReader> = {
  MOVED: readMoved,
  QUANTITY_CHANGED: readQuantityChanged,
  USED: readRemoval,
  DISPOSED: readRemoval,
  CREATED: readCreated,
  CREATED_VIA_SCAN: readCreatedViaScan,
  QUANTITY_INCREASED_VIA_SCAN: readQuantityIncreasedViaScan,
  DELETED: readDeleted,
  RESTORED: readRestored,
  UPDATED: readUpdated,
  STATUS_CHANGED: readStatusChanged,
  OPENED: readOpened,
};

/**
 * Actions whose history row carries nothing beyond the action label.
 *
 * The label is always there — it is what the action name translates to.
 * These are the writes that carry no `changes` payload worth reading, so
 * the reader returns "" for them and the row shows only the label.
 * Every member of the backend `ItemAction` enum must appear either in
 * `READERS` or here; the contract test enforces it.
 */
export const LABEL_ONLY_ACTIONS: ReadonlySet<string> = new Set();

/**
 * One line under the action naming what changed.
 *
 * Every branch is read by a person standing in a warehouse: places are named,
 * the reason travels with the quantity, and an update names the fields that
 * moved instead of dumping both records as JSON.
 */
export function parseChanges(
  action: string,
  changes: Record<string, unknown> | null,
  t: Translate,
  locationName?: (id: string) => string | undefined,
  unit?: HistoryUnit,
): string {
  if (!changes) return "";
  return (READERS[action] ?? readUnknown)(changes, { t, locationName, unit });
}
