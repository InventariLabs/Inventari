import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { TranslateFn } from "@/types/i18n";
import type { WorkItem } from "@/modules/warehouse/types";
import { documentTitle } from "@/modules/warehouse/lib/documentTitle";

const INBOUND_TYPES = new Set(["IN", "INTERNAL_IN"]);

/** The verb on the button, or nothing when the task has no action. A module's
 * own task names its label itself; the built-in verbs are literal calls so the
 * unused-key check can see every one of them. */
export function actionLabel(t: TranslateFn, item: WorkItem): string | null {
  if (item.action_label) return item.action_label;
  switch (item.next_action) {
    case "receive":
      return t("warehouse:todo.receive");
    case "pick":
      return t("warehouse:todo.pick");
    case "resume":
      return t("warehouse:todo.resume");
    case "pack":
      return t("warehouse:todo.pack");
    case "complete":
      return t("warehouse:todo.complete");
    case "request_approval":
      return t("warehouse:todo.requestApproval");
    case "receive_delivery":
      return t("warehouse:todo.receiveDelivery");
    case "produce":
      return t("warehouse:todo.produce");
    case "review_approval":
      return t("warehouse:todo.decisionReviewApproval");
    case "open_draft":
      return t("warehouse:todo.decisionOpenDraft");
    case "count":
      return t("warehouse:todo.count");
    case "put_away":
      return t("warehouse:todo.putAway");
    case "replenish":
      return t("warehouse:todo.replenish");
    default:
      return null;
  }
}

/** Where the one next action is taken: a module's own link, a session, the
 * packing step, the document's own page, or the screen of the order or run
 * behind it. A count carries the link to the one under way; one not yet begun
 * is started from the list instead. */
export function workItemTarget(item: WorkItem): string {
  if (item.action_href) return item.action_href;
  const id = item.source_id;
  switch (item.next_action) {
    case "receive":
      return `/warehouse/documents/${id}#receive`;
    case "pick":
      return `/warehouse/documents/${id}#pick`;
    case "resume":
      return `/warehouse/documents/${id}#${
        INBOUND_TYPES.has(item.document_type ?? "") ? "receive" : "pick"
      }`;
    case "request_approval":
      // The document's own page is where the gate is explained and the
      // approvals card raises the request; opening the session there would
      // read as a start the rule has not allowed.
      return `/warehouse/documents/${id}`;
    case "pack":
      return `/warehouse/documents/${id}#pack`;
    case "receive_delivery":
      // The order's own lines on the receive screen, not the order to open
      // and press Receive on.
      return `/warehouse/receive?order=${id}`;
    case "produce":
      return `/maker/production/${id}`;
    case "replenish":
      return `/warehouse/todo?replenish=${id}`;
    default:
      return `/warehouse/documents/${id}`;
  }
}

/** The document a task is about, in the words a document is called elsewhere:
 * a draft has no number yet, and its raw identifier reads as an error. */
export function workItemNumber(t: TranslateFn, item: WorkItem): string {
  const number = item.number ?? "";
  if (!number || !item.document_type) return number;
  return documentTitle(t, { number, type: item.document_type });
}

/** What the task asks of the reader, as a sentence: who it is for and how
 * much of it. Each sentence is a literal key, so the unused-key check sees
 * them all and each language orders its own words. */
export function workItemSentence(t: TranslateFn, item: WorkItem): string {
  if (item.sentence) return item.sentence;
  const subject = item.subject ?? "";
  const number = workItemNumber(t, item);
  const lead = leadSentence(t, item, subject, number);
  const lines = Number(item.count ?? 0);
  const showsLines =
    item.source_kind === "document" || item.source_kind === "purchase_order";
  if (!showsLines || lines <= 0) return lead;
  return t("warehouse:todo.task.withItems", { lead, count: lines });
}

function leadSentence(
  t: TranslateFn,
  item: WorkItem,
  subject: string,
  number: string,
): string {
  switch (item.kind) {
    case "receive":
    case "expected_delivery":
      if (subject) return t("warehouse:todo.task.receive", { subject });
      return item.kind === "receive"
        ? t("warehouse:todo.task.receiveAnon", { number })
        : t("warehouse:todo.task.expectedAnon", { number });
    case "ship":
      if (item.document_type === "INT")
        return t("warehouse:todo.task.transfer", { number });
      return subject
        ? t("warehouse:todo.task.ship", { subject })
        : t("warehouse:todo.task.shipAnon", { number });
    case "produce":
      return t("warehouse:todo.task.produce", {
        subject,
        quantity: formatQuantityLocalized(t, item.count, item.unit),
      });
    case "approve":
      return subject
        ? t("warehouse:todo.task.approve", { number, subject })
        : t("warehouse:todo.task.approveAnon", { number });
    case "backorder":
      return item.origin_number
        ? t("warehouse:todo.task.backorder", { origin: item.origin_number })
        : t("warehouse:todo.task.backorderAnon", { number });
    case "count":
      return item.source_kind === "location"
        ? countLocationSentence(t, item, subject)
        : t("warehouse:todo.task.count", { subject });
    case "putaway":
      return putawaySentence(t, item, subject);
    case "replenish":
      return replenishSentence(t, item, subject);
    default:
      return subject || number;
  }
}

/** Goods waiting in a receiving area: "Put away 40 pcs Jasmine Rice to Shelf
 * A - Top", or without the shelf when no rule names one. */
function putawaySentence(
  t: TranslateFn,
  item: WorkItem,
  subject: string,
): string {
  const quantity = formatQuantityLocalized(t, item.count, item.unit);
  if (!item.place)
    return t("warehouse:todo.task.putaway", { quantity, subject });
  return t("warehouse:todo.task.putawayTo", {
    quantity,
    subject,
    location: item.place,
  });
}

/** Reserve stock on its way to a pick face: "Carry 17 pcs Jasmine Rice from
 * reserve to Pick B-01". */
function replenishSentence(
  t: TranslateFn,
  item: WorkItem,
  subject: string,
): string {
  const quantity = formatQuantityLocalized(t, item.count, item.unit);
  return t("warehouse:todo.task.replenish", {
    quantity,
    subject,
    location: item.place ?? "",
  });
}

/** A location that has fallen due: "Count Shelf A — last counted 62 days
 * ago". Its ``count`` is the days since that count, empty when there was
 * none. */
function countLocationSentence(
  t: TranslateFn,
  item: WorkItem,
  subject: string,
): string {
  if (item.count == null)
    return t("warehouse:todo.task.countLocationNever", { subject });
  return t("warehouse:todo.task.countLocation", {
    subject,
    count: Number(item.count),
  });
}
