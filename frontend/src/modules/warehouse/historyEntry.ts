import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";
import {
  correctionStockSign,
  type WarehouseDocumentRow,
} from "@/modules/warehouse/types";

/**
 * Which document types each History chip stands for, as the comma-joined
 * list the documents API takes. A receipt from production and a receipt from
 * a supplier are both "Receipts" to the person asking what came in.
 */
export const HISTORY_CHIPS = [
  { key: "all", types: undefined },
  { key: "receipts", types: "IN,INTERNAL_IN" },
  { key: "issues", types: "OUT" },
  { key: "moves", types: "INT" },
  { key: "use", types: "INTERNAL_OUT,SCRAP" },
  { key: "corrections", types: "CORRECTION,ADJUSTMENT" },
] as const;

export type HistoryChipKey = (typeof HISTORY_CHIPS)[number]["key"];

/** What a person means by "drafts and planned": not done yet, not dropped. */
export const HISTORY_PLANNED_STATUSES = "DRAFT,PENDING_APPROVAL,CONFIRMED";

/** The types that have a sentence of their own: `history.sentence.<TYPE>`. */
const SENTENCE_TYPES: ReadonlySet<string> = new Set([
  "IN",
  "OUT",
  "INT",
  "INTERNAL_IN",
  "INTERNAL_OUT",
  "SCRAP",
  "CORRECTION",
  "ADJUSTMENT",
]);

/** Receipts and issues name who the goods came from or went to:
 *  `history.sentence.<TYPE>Partner`. */
const PARTNER_SENTENCE_TYPES: ReadonlySet<string> = new Set(["IN", "OUT"]);

/** An adjustment's lines are differences with no direction the list row can
 *  read, so its sentence names the product and no quantity. */
const NAME_ONLY_TYPES: ReadonlySet<string> = new Set(["ADJUSTMENT"]);

const NAMED_PRODUCTS_IN_SUB_LINE = 2;

export interface HistoryEntryText {
  /** The entry in a sentence: "Received 6 items from Mleczarnia Sady". */
  sentence: string;
  /** The products or the path under the sentence; empty when there is none. */
  detail: string;
}

/** The contents of an entry: one product with its quantity, else a count. */
function describeWhat(
  doc: WarehouseDocumentRow,
  completed: boolean,
  t: TranslateFn,
): string {
  const only = doc.line_count === 1 ? doc.first_lines[0] : undefined;
  if (!only?.name)
    return t("warehouse:history.items", { count: doc.line_count });
  if (NAME_ONLY_TYPES.has(doc.type)) return only.name;
  const quantity = completed ? only.done_quantity : only.quantity;
  if (doc.type === "CORRECTION") {
    // A correction's line is a delta on the document it corrects, and the
    // sentence states what happened to stock, as the document's own summary
    // does: −1 on an issue put one back, so it reads "by +1".
    const delta =
      correctionStockSign(doc.corrects_document_type) * Number(quantity);
    const size = formatQuantityLocalized(
      t,
      Math.abs(delta),
      only.uom?.symbol,
      only.uom?.rounding,
    );
    return t("warehouse:history.correctedBy", {
      name: only.name,
      amount: `${delta < 0 ? "−" : "+"}${size}`,
    });
  }
  const amount = formatQuantityLocalized(
    t,
    quantity,
    only.uom?.symbol,
    only.uom?.rounding,
  );
  return `${amount} ${only.name}`;
}

/** The line under the sentence: partner, path, and the products it names. */
function describeDetail(
  doc: WarehouseDocumentRow,
  partnerInSentence: boolean,
  t: TranslateFn,
): string {
  const { source_location_name: from, target_location_name: to } = doc;
  const detail: string[] = [];
  // A planned entry has no partner in its sentence, so the detail carries it.
  if (doc.partner_snapshot?.name && !partnerInSentence) {
    detail.push(doc.partner_snapshot.name);
  }
  if (from && to) detail.push(`${from} → ${to}`);
  else if (from || to) detail.push(from ?? to ?? "");
  // The list row carries its first lines only — as many as this sentence
  // names — and the count of all of them.
  const names = doc.first_lines.flatMap((line) =>
    line.name ? [line.name] : [],
  );
  if (doc.line_count > 1 && names.length > 0) {
    const shown = names.slice(0, NAMED_PRODUCTS_IN_SUB_LINE);
    const rest = doc.line_count - shown.length;
    const list = shown.join(", ");
    detail.push(
      rest > 0
        ? `${list} ${t("warehouse:history.andOthers", { count: rest })}`
        : list,
    );
  }
  return detail.join(" · ");
}

/**
 * Put a document in plain words.
 *
 * A completed document says what happened. One that has not been completed
 * yet is not allowed to: "Received 6 items" over a draft reads as stock that
 * is not on the shelf, so a draft or a planned document is named by its type
 * and its contents, and its status badge says the rest.
 */
export function describeHistoryEntry(
  doc: WarehouseDocumentRow,
  t: TranslateFn,
): HistoryEntryText {
  const completed = doc.status === "COMPLETED";
  const partner = doc.partner_snapshot?.name ?? null;
  const what = describeWhat(doc, completed, t);
  const withPartner = Boolean(partner) && PARTNER_SENTENCE_TYPES.has(doc.type);
  const sentence =
    completed && SENTENCE_TYPES.has(doc.type)
      ? t(
          `warehouse:history.sentence.${doc.type}${withPartner ? "Partner" : ""}`,
          { what, partner },
        )
      : t("warehouse:history.planned", {
          type: t(`warehouse:types.${doc.type}`),
          what,
        });
  const partnerInSentence = completed && withPartner;
  return { sentence, detail: describeDetail(doc, partnerInSentence, t) };
}
