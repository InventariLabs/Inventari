import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type Dispatch,
  type RefObject,
  type SetStateAction,
} from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { TypedSlot } from "@/components/Slot";
import type {
  DocumentMetaData,
  RegisterBeforeSubmit,
  SetMetaData,
} from "@/lib/moduleRegistry";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useFormGuard } from "@/hooks/useFormGuard";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { useModules } from "@/contexts/ModulesContext";
import { usePartnerPicker } from "@/hooks/usePartnerPicker";
import { CUSTOMER_ROLE_TYPES, SUPPLIER_ROLE_TYPES } from "@/hooks/partnerRoles";
import type { PartnerType } from "@/types";
import {
  useOpenPurchaseOrders,
  useOrderSupplier,
  type OpenPurchaseOrderLine,
} from "@/hooks/useOpenPurchaseOrders";
import { useLocationOffer } from "@/module-sdk";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import {
  useConfirmDocument,
  useCreateDocument,
  usePostNewDocument,
} from "@/modules/warehouse/hooks/useDocuments";
import { useDocumentMetaData } from "@/modules/warehouse/hooks/useDocumentMetaData";
import { useDraftExtensions } from "@/modules/warehouse/hooks/useDraftExtensions";
import { useReceiptPlan } from "@/modules/warehouse/hooks/useReceiptPlan";
import type { ImportResult } from "@/modules/warehouse/components/ImportPreviewSections";
import { useReceivingModes } from "@/modules/warehouse/hooks/usePutawayRules";
import { waitingInReceiving } from "@/modules/warehouse/components/receive/waitingInReceiving";
import { PostedActionResult } from "@/modules/warehouse/components/actions/PostedActionResult";
import { useSurplusQuestion } from "@/modules/warehouse/components/SurplusQuestion";
import { ReceiveFooter } from "@/modules/warehouse/components/receive/ReceiveFooter";
import { ReceiveHeaderFields } from "@/modules/warehouse/components/receive/ReceiveHeaderFields";
import { ReceiveLinesCard } from "@/modules/warehouse/components/receive/ReceiveLinesCard";
import { OrderOpenReceipts } from "@/modules/warehouse/components/receive/OrderOpenReceipts";
import {
  ReceivePhoneStart,
  type PhoneDoor,
  type PhoneGoods,
} from "@/modules/warehouse/components/receive/ReceivePhoneStart";
import {
  draftLineView,
  draftProblem,
  draftTotals,
  isHeld,
  RECEIVE_SOURCE_TYPE,
  shortDelivery,
  toDocumentCreate,
  withImportedLines,
  withOrderLines,
  withScannedProduct,
  type DraftProblem,
  type ImportedLine,
  type ReceiveDraftLine,
  type ReceiveSource,
  type RowPatch,
} from "@/modules/warehouse/components/receive/receiveDraft";
import type { ProductSearchResult } from "@/modules/warehouse/api/documents";
import type {
  DocumentCreate,
  DocumentType,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import { formatQuantityLocale } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { extractApiError, extractApiErrorCode } from "@/lib/errors";

// Pasting rows is a desk task, opened on request: its own chunk keeps the
// import dialog (file upload, column mapping, preview) off the screen a
// phone downloads to receive goods.
const DocumentImportModal = lazy(() =>
  import("@/modules/warehouse/components/DocumentImportModal").then(
    (module) => ({ default: module.DocumentImportModal }),
  ),
);

const TARGET_FIELD_ID = "receive-target-warehouse";

/** Below `sm` the delivery is received one item at a time, as a phone holds it. */
const PHONE_QUERY = "(max-width: 639px)";

/** What a form problem is called in the catalogues. */
const PROBLEM_KEYS = {
  noLines: "receive.errors.noLines",
  noProduct: "receive.errors.noProduct",
  noQuantity: "receive.errors.noQuantity",
  heldAboveReceived: "receive.errors.heldAboveReceived",
  noWarehouse: "receive.errors.noWarehouse",
  noPartner: "receive.errors.noPartner",
} as const satisfies Record<DraftProblem | "noPartner", string>;

/** The vocabulary the helper and the sheet share, plus the partner. */
type ProblemKey = DraftProblem | "noPartner";

/** What stops the sheet, and the row whose own value is the cause. */
interface Refusal {
  problem: ProblemKey;
  lineKey?: string;
}

/** The button says what the press does for this source. */
function postLabel(t: TFunction, source: ReceiveSource): string {
  switch (source) {
    case "return":
      return t("receive.post.return");
    case "internal":
      return t("receive.post.internal");
    default:
      return t("receive.post.supplier");
  }
}

/** What an empty sheet can do: only a delivery may wait on an order. */
function emptyHint(t: TFunction, source: ReceiveSource): string {
  return source === "supplier"
    ? t("receive.emptyHint")
    : t("receive.emptyHintAny");
}

/** Who the partner field offers: a customer's goods come back from a
 *  customer. An internal receipt names nobody, and its field is hidden. */
function partnerTypesFor(source: ReceiveSource): readonly PartnerType[] {
  return source === "return" ? CUSTOMER_ROLE_TYPES : SUPPLIER_ROLE_TYPES;
}

/** What stops the sheet, in the words of the source that was chosen. */
function problemMessage(
  t: TFunction,
  problem: ProblemKey,
  source: ReceiveSource,
): string {
  if (problem === "noPartner") {
    return source === "return"
      ? t("receive.errors.noCustomer")
      : t(PROBLEM_KEYS.noPartner);
  }
  return t(PROBLEM_KEYS[problem]);
}

/** The refusal that belongs to the location field, for the field to wear. */
function targetProblem(
  t: TFunction,
  problem: ProblemKey | null,
  source: ReceiveSource,
): string | undefined {
  return problem === "noWarehouse"
    ? problemMessage(t, problem, source)
    : undefined;
}

/** The sentence under the result: the count, and what the order still expects. */
function successDetails(
  t: TFunction,
  args: {
    pending: boolean;
    quantity: string | null;
    unit: string | null;
    orderNumber: string | null;
    shortCount: number;
  },
): string {
  const parts: string[] = [];
  if (!args.pending && args.quantity && args.unit) {
    parts.push(
      t("receive.success.quantity", {
        quantity: formatQuantityLocale(args.quantity),
        unit: unitLabel(t, args.unit),
      }),
    );
  }
  if (args.orderNumber === null) {
    parts.push(t("receive.success.documentSaved"));
  } else if (args.shortCount > 0) {
    parts.push(
      t("receive.success.orderRemains", {
        number: args.orderNumber,
        count: args.shortCount,
      }),
    );
  } else {
    parts.push(
      t("receive.success.orderComplete", { number: args.orderNumber }),
    );
  }
  return parts.join(" ");
}

/** Two sheets that hold the same rows, whatever keys React gave them. */
function sameRows(a: ReceiveDraftLine[], b: ReceiveDraftLine[]): boolean {
  const rows = (lines: ReceiveDraftLine[]) =>
    JSON.stringify(lines.map(({ key: _key, ...row }) => row));
  return rows(a) === rows(b);
}

/**
 * Whether the sheet holds anything the reader would lose by leaving.
 *
 * What an order link loaded is not work: the supplier it named and the
 * order's lines as the order states them are still on the order, and
 * leaving loses nothing. A row changed, added or removed, a reference
 * typed, or a supplier chosen by hand is.
 */
function sheetHasWork(args: {
  lines: ReceiveDraftLine[];
  externalReference: string;
  partnerId: string;
  linkedPartnerId: string | null;
  orderLines: OpenPurchaseOrderLine[];
}): boolean {
  const asLoaded =
    args.lines.length === 0 ||
    sameRows(args.lines, withOrderLines([], args.orderLines));
  return (
    !asLoaded ||
    args.externalReference.trim().length > 0 ||
    (args.partnerId.length > 0 && args.partnerId !== args.linkedPartnerId)
  );
}

/** Typed work is unsaved: leaving the sheet asks before it is lost. */
function useSheetGuard(args: {
  lines: ReceiveDraftLine[];
  externalReference: string;
  partnerId: string;
  delivery: {
    linkedPartnerId: string | null;
    chosenOrder: { lines: OpenPurchaseOrderLine[] } | null;
  };
  /** The posted receipt: the sheet behind the answer holds nothing to lose. */
  result: object | null;
}) {
  const { t } = useTranslation("warehouse");
  const { delivery, result, ...sheet } = args;
  useFormGuard(
    sheetHasWork({
      ...sheet,
      linkedPartnerId: delivery.linkedPartnerId,
      orderLines: delivery.chosenOrder?.lines ?? [],
    }) && !result,
    t("receive.guardName"),
  );
}

/**
 * What was posted, taken as the answer came back. Posting refreshes the
 * supplier's open orders, and an order just received in full drops out of
 * them: read live, the answer would forget the order it was about.
 */
interface PostedReceipt {
  document: WarehouseDocument;
  quantity: string | null;
  unit: string | null;
  order: { id: string; number: string } | null;
  shortCount: number;
}

/** The answer to keep, read off the sheet as the post returned. */
function postedReceipt(
  document: WarehouseDocument,
  totals: { quantity: string | null; unit: string | null },
  order: { id: string; number: string } | null,
  shortCount: number,
): PostedReceipt {
  return {
    document,
    quantity: totals.quantity,
    unit: totals.unit,
    order: order && { id: order.id, number: order.number },
    shortCount,
  };
}

/**
 * The order a link names (`?order=`), whose supplier opens the sheet.
 *
 * The order's own screen and its To do row name the order; the sheet loads
 * expected lines by supplier, so naming the supplier is what starts it on
 * the order's lines instead of a blank form. Applied once: choosing another
 * supplier afterwards is the reader's word, not the link's.
 */
function useLinkedOrder(
  setPartnerId: (id: string) => void,
  /** The supplier source is chosen: only its sheet starts from an order. */
  offer: boolean,
) {
  const [searchParams] = useSearchParams();
  const orderId = searchParams.get("order");
  const { partnerId } = useOrderSupplier(offer ? orderId : null);
  const applied = useRef(false);
  useEffect(() => {
    if (!offer || applied.current || !partnerId) return;
    applied.current = true;
    setPartnerId(partnerId);
  }, [offer, partnerId, setPartnerId]);
  return { orderId, partnerId };
}

/**
 * The waiting order the sheet is filled from: the one a link names, else
 * the one the reader chose, else the supplier's first.
 *
 * Choosing a supplier loads what its order still expects. Lines typed by
 * hand stay; lines from the previous order go, because they describe a
 * delivery that is not this one.
 */
function useDeliveryOrder(
  partnerId: string,
  setPartnerId: (id: string) => void,
  setLines: Dispatch<SetStateAction<ReceiveDraftLine[]>>,
  setFocusLineKey: (key: string | null) => void,
  supplierSource: boolean,
) {
  const linked = useLinkedOrder(setPartnerId, supplierSource);
  const orders = useOpenPurchaseOrders(partnerId || null);
  const [chosenOrderId, setChosenOrderId] = useState(linked.orderId);
  const chosenOrder = useMemo(
    () => chosenOf(orders.orders, chosenOrderId),
    [orders.orders, chosenOrderId],
  );
  const loadedOrder = useRef<string | null>(null);

  // What the cache holds for this supplier may be a delivery behind: the
  // sheet waits for the read under way, because lines taken from the old
  // answer would not be replaced when the new one arrives.
  const reading = orders.isFetching;

  useEffect(() => {
    if (reading || !chosenOrder || loadedOrder.current === chosenOrder.id) {
      return;
    }
    loadedOrder.current = chosenOrder.id;
    setLines((current) =>
      withOrderLines(withoutOrderLines(current), chosenOrder.lines),
    );
    setFocusLineKey(null);
  }, [chosenOrder, reading, setFocusLineKey, setLines]);

  /** Another supplier or another delivery: no order is chosen or loaded. */
  const forgetOrder = useCallback(() => {
    setChosenOrderId(null);
    loadedOrder.current = null;
  }, []);

  return {
    orders,
    chosenOrder,
    setChosenOrderId,
    forgetOrder,
    linkedPartnerId: linked.partnerId,
  };
}

/** The page header: the sheet's title, or the answer's once it is posted.
 *
 * Back goes where the reader came from — the order a link was followed
 * from says so — and to the warehouse start otherwise. */
function useReceiveHeader(posted: WarehouseDocument | null) {
  const { t } = useTranslation("warehouse");
  const { setHeader } = useModulePageHeader();
  const backTo = useReturnTarget() ?? "/warehouse/todo";
  const heading = receiveHeading(t, posted);
  useEffect(() => {
    setHeader({
      title: heading,
      subtitle: posted ? undefined : t("receive.subtitle"),
      backTo,
    });
  }, [backTo, heading, posted, setHeader, t]);
}

/** The result panel, fed by the sheet the reader had just filled in. */
function ReceiveResult({
  posted,
  onAnother,
}: {
  posted: PostedReceipt;
  onAnother: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const { document, order } = posted;
  const { data: receivingModes } = useReceivingModes();
  return (
    <div className="space-y-6">
      <PostedActionResult
        document={document}
        action="receive"
        lineCount={document.lines.length}
        waitingIn={waitingInReceiving(document, receivingModes)}
        details={successDetails(t, {
          pending: document.status === "PENDING_APPROVAL",
          quantity: posted.quantity,
          unit: posted.unit,
          orderNumber: order?.number ?? null,
          shortCount: posted.shortCount,
        })}
        extraActions={
          order && (
            <Button
              variant="outline"
              onClick={() => navigate(`/purchase-orders/${order.id}`)}
            >
              {t("receive.backToOrder", { number: order.number })}
            </Button>
          )
        }
        onAnother={onAnother}
      />
    </div>
  );
}

/** What a paste could not put on the sheet, said before the reader posts. */
interface RefusedPaste {
  unmatched: ImportedLine[];
  errors: ImportResult["errors"];
}

/** A press: the body that identifies it and the key the server remembers. */
type Press = { key: string; body: string };

/**
 * Send a press under the key the server remembers for it. The key lives as
 * long as the answer is owed — a retry after a lost answer is answered with
 * the document the first send made — and is retired once the answer is here,
 * so the same goods handed over again are a new delivery, not a retry.
 */
async function sendOnePress(
  press: { current: Press | null },
  send: (input: {
    data: DocumentCreate;
    key: string;
    confirmSurplus: boolean;
  }) => Promise<WarehouseDocument>,
  data: DocumentCreate,
  confirmSurplus: boolean,
): Promise<WarehouseDocument> {
  const body = JSON.stringify(data);
  if (press.current?.body !== body) {
    press.current = { key: crypto.randomUUID(), body };
  }
  // A surplus the server asked about wrote nothing, so the answer goes
  // under the same key: it is the same press, now confirmed.
  const answer = await send({ data, key: press.current.key, confirmSurplus });
  press.current = null;
  return answer;
}

/** What the server answers when a surplus needs the reader's yes. */
const SURPLUS_ASKED = "SURPLUS_NEEDS_CONFIRMATION";
const TAX_ID_REFUSED = "DOCUMENT_PARTNER_TAX_ID_REQUIRED";

/** The rows of the sheet that did not come from the supplier's order. */
function withoutOrderLines(lines: ReceiveDraftLine[]): ReceiveDraftLine[] {
  return lines.filter((line) => line.sourcePoLineId === null);
}

/** The heading the sheet or its answer wears. */
function receiveHeading(
  t: TFunction,
  posted: WarehouseDocument | null,
): string {
  if (!posted) return t("receive.title");
  return posted.status === "PENDING_APPROVAL"
    ? t("posted.pendingTitle")
    : t("receive.success.heading");
}

/** Put the reader where the refused field is. */
function focusProblem(issue: ProblemKey | null, scan: HTMLInputElement | null) {
  if (issue === "noWarehouse") {
    document.getElementById(TARGET_FIELD_ID)?.focus();
  } else if (issue === "noLines" || issue === "noProduct") {
    scan?.focus();
  }
}

/**
 * A priced receipt is worth something in the register; one posted without a
 * price is worth nothing there, and says "Goods are in stock" all the same.
 * The sheet says so before the post, with the way to the price column when
 * it is folded away.
 */
function unpricedCount(
  lines: ReceiveDraftLine[],
  valueNeeded: boolean,
): number {
  if (!valueNeeded) return 0;
  return lines.filter((line) => line.unitPrice.trim() === "").length;
}

function UnpricedLinesNotice({
  unpriced,
  pricesShown,
  onShowPrices,
}: {
  unpriced: number;
  pricesShown: boolean;
  onShowPrices: () => void;
}) {
  const { t } = useTranslation("warehouse");
  if (unpriced === 0) return null;
  return (
    <div
      role="status"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-lg bg-amber-50 px-4 py-3 text-sm text-on-warning"
    >
      <span>{t("receive.unpricedLines", { total: unpriced })}</span>
      {!pricesShown && (
        <Button type="button" variant="ghost" size="sm" onClick={onShowPrices}>
          {t("receive.addPrices")}
        </Button>
      )}
    </div>
  );
}

function PasteRefusedNotice({ refused }: { refused: RefusedPaste | null }) {
  const { t } = useTranslation("warehouse");
  if (!refused) return null;
  const { unmatched, errors } = refused;
  return (
    <div
      role="alert"
      className="space-y-2 rounded-lg bg-amber-50 px-4 py-3 text-sm text-on-warning"
    >
      {unmatched.length > 0 && (
        <div>
          <p className="font-medium">
            {t("receive.importUnmatched", { count: unmatched.length })}
          </p>
          <ul className="mt-0.5 list-disc pl-5">
            {unmatched.map((row) => (
              <li key={row.id}>
                {t("receive.importUnmatchedRow", {
                  name: row.name || "—",
                  quantity: formatQuantityLocale(row.quantity),
                })}
              </li>
            ))}
          </ul>
          <p className="mt-1">{t("receive.importUnmatchedHint")}</p>
        </div>
      )}
      {errors.length > 0 && (
        <div>
          <p className="font-medium">
            {t("import.errorCount", { count: errors.length })}
          </p>
          <ul className="mt-0.5 list-disc pl-5">
            {errors.map((error) => (
              <li key={`${error.row}-${error.error}`}>
                {t("import.row")} {error.row}: {error.error}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

/** The orders a supplier still owes, as the order picker lists them. */
function orderOptions(
  orders: { id: string; number: string; lines: unknown[] }[],
) {
  return orders.map((order) => ({
    id: order.id,
    number: order.number,
    lineCount: order.lines.length,
  }));
}

/** The footer's count, when every row is in one unit. */
function totalQuantity(totals: {
  quantity: string | null;
  unit: string | null;
}) {
  return totals.quantity && totals.unit
    ? { value: totals.quantity, unit: totals.unit }
    : null;
}

function patchRow(lines: ReceiveDraftLine[], key: string, patch: RowPatch) {
  return lines.map((row) =>
    row.key === key
      ? { ...row, ...(typeof patch === "function" ? patch(row) : patch) }
      : row,
  );
}

function dropRow(lines: ReceiveDraftLine[], key: string) {
  return lines.filter((row) => row.key !== key);
}

/** The sheet after a paste, and what the paste could not put on it. */
function importOutcome(lines: ReceiveDraftLine[], result: ImportResult) {
  const applied = withImportedLines(lines, result.lines);
  const refused: RefusedPaste | null =
    applied.unmatched.length > 0 || result.errors.length > 0
      ? { unmatched: applied.unmatched, errors: result.errors }
      : null;
  return { lines: applied.lines, refused };
}

/**
 * One internal location is the warehouse: there is nothing to choose, and
 * asking the reader to choose it is a click that cannot change anything.
 */
function useOnlyWarehouse(
  total: number | undefined,
  first: { id: string }[],
  targetLocationId: string,
  setTargetLocationId: (id: string) => void,
) {
  const defaulted = useRef(false);
  useEffect(() => {
    if (defaulted.current || targetLocationId || total !== 1) return;
    defaulted.current = true;
    setTargetLocationId(first[0].id);
  }, [total, first, targetLocationId, setTargetLocationId]);
}

/** Ctrl/Cmd+Enter posts from anywhere on the sheet.
 *
 * Listening on the window rather than a wrapping element keeps the page's own
 * markup non-interactive. The result screen has nothing left to post, and the
 * import sheet's Enter belongs to the paste, so neither gets the shortcut.
 */
function usePostShortcut(
  post: () => void,
  result: object | null,
  importing: boolean,
) {
  useEffect(() => {
    if (result || importing) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      // A held shortcut is one press, not one per repeat.
      if (event.repeat) return;
      if (!(event.ctrlKey || event.metaKey) || event.key !== "Enter") return;
      event.preventDefault();
      post();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [importing, post, result]);
}

/** What opens once the sheet is saved as a draft, given the draft's id. */
type AfterSave = (id: string) => Promise<void>;

/**
 * On a phone the delivery is counted on the receiving session, not on the
 * sheet: the sheet is saved as a receipt, the receipt is confirmed, and its
 * page opens the session — the camera, the count stepper and the suggested
 * location — the way a receipt's own Start receiving does. The page is
 * replaced, not stacked: Back from the session goes where the reader came
 * from, not to a sheet that would make a second receipt.
 *
 * A confirmation the server refuses leaves the receipt a draft, and the
 * reader is taken to it with the reason rather than left on a sheet that
 * would build another. `null` on a wider screen.
 */
function usePhoneDoor(
  canWrite: boolean,
  saveDraft: (then: AfterSave) => Promise<void>,
): PhoneDoor | null {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const isPhone = useMediaQuery(PHONE_QUERY);
  const [starting, setStarting] = useState(false);
  const confirmReceipt = useConfirmDocument();

  const openReceiving = useCallback(
    async (id: string) => {
      try {
        await confirmReceipt.mutateAsync(id);
      } catch (refused) {
        toast.error(extractApiError(refused, t("receive.errors.startFailed")));
        navigate(`/warehouse/documents/${id}`, { replace: true });
        return;
      }
      navigate(`/warehouse/documents/${id}#receive`, { replace: true });
    },
    [confirmReceipt, navigate, t],
  );

  if (!isPhone) return null;
  return {
    canWrite,
    starting,
    onStart: () => {
      setStarting(true);
      void saveDraft(openReceiving).finally(() => setStarting(false));
    },
  };
}

/**
 * The two presses that send the sheet: the post, and the draft kept for
 * later. Both check the sheet the same way, both run a module's fields
 * before anything is sent, and both answer in the sheet's own state — the
 * receipt it posted, or the reason the server refused.
 */
function useSheetPresses(args: {
  canWrite: boolean;
  result: PostedReceipt | null;
  submitting: { current: boolean };
  press: { current: Press | null };
  budgetProblem: () => Refusal | null;
  showProblem: (refusal: Refusal) => void;
  /** The previous refusal belongs to the previous press. */
  clearRefusals: () => void;
  runBeforeSubmit: () => Promise<void>;
  payload: () => DocumentCreate;
  save: (data: DocumentCreate) => Promise<WarehouseDocument>;
  send: (input: {
    data: DocumentCreate;
    key: string;
    confirmSurplus: boolean;
  }) => Promise<WarehouseDocument>;
  /** Put the server's question about a surplus to the reader; yes resends. */
  askSurplus: (message: string, resend: () => unknown) => void;
  navigate: (to: string) => void;
  t: TFunction;
  totals: { quantity: string | null; unit: string | null };
  order: { id: string; number: string } | null;
  shortCount: number;
  /** A row says part of what arrived is held back; only a post can record it. */
  holdsGoods: boolean;
  onPosted: (receipt: PostedReceipt) => void;
  onPostError: (message: string, code?: string | null) => void;
}) {
  const {
    canWrite,
    result,
    submitting,
    press,
    budgetProblem,
    showProblem,
    clearRefusals,
    runBeforeSubmit,
    payload,
    save,
    send,
    askSurplus,
    navigate,
    t,
    totals,
    order,
    shortCount,
    holdsGoods,
    onPosted,
    onPostError,
  } = args;

  const post = useCallback(
    async (confirmSurplus = false) => {
      if (!canWrite || result || submitting.current) return;
      const refusal = budgetProblem();
      if (refusal) {
        showProblem(refusal);
        return;
      }
      clearRefusals();
      submitting.current = true;
      try {
        await runBeforeSubmit();
        const document = await sendOnePress(
          press,
          send,
          payload(),
          confirmSurplus,
        );
        onPosted(postedReceipt(document, totals, order, shortCount));
      } catch (error) {
        if (extractApiErrorCode(error) === SURPLUS_ASKED) {
          askSurplus(extractApiError(error, ""), () => post(true));
          return;
        }
        onPostError(
          extractApiError(error, t("receive.errors.postFailed")),
          extractApiErrorCode(error),
        );
      } finally {
        submitting.current = false;
      }
    },
    [
      askSurplus,
      budgetProblem,
      canWrite,
      clearRefusals,
      onPostError,
      onPosted,
      order,
      payload,
      press,
      result,
      runBeforeSubmit,
      send,
      shortCount,
      showProblem,
      submitting,
      t,
      totals,
    ],
  );

  // The draft's page follows the save, or on a phone its receiving session.
  const finishLater = useCallback(
    async (then?: AfterSave) => {
      if (!canWrite || submitting.current) return;
      const refusal = budgetProblem();
      if (refusal) {
        showProblem(refusal);
        return;
      }
      // A draft keeps the count that arrived, not what was set aside from it:
      // saving would turn quarantined goods into ordinary stock without a word.
      if (holdsGoods) {
        onPostError(t("receive.errors.heldNeedsPost"));
        return;
      }
      clearRefusals();
      submitting.current = true;
      try {
        await runBeforeSubmit();
        const draft = await save(payload());
        if (then) {
          await then(draft.id);
          return;
        }
        toast.success(t("receive.draftSaved"));
        navigate(`/warehouse/documents/${draft.id}`);
      } catch (error) {
        onPostError(extractApiError(error, t("receive.errors.saveFailed")));
      } finally {
        submitting.current = false;
      }
    },
    [
      budgetProblem,
      canWrite,
      clearRefusals,
      holdsGoods,
      navigate,
      onPostError,
      payload,
      runBeforeSubmit,
      save,
      showProblem,
      submitting,
      t,
    ],
  );

  return { post, finishLater };
}

/** What other modules may add among the sheet's document-level fields. */
function ReceiveDraftSlot({
  partnerId,
  partnersEnabled,
  docType,
  lines,
  meta,
  registerBeforeSubmit,
}: {
  partnerId: string;
  partnersEnabled: boolean;
  docType: DocumentType;
  lines: ReceiveDraftLine[];
  meta: { metaData: DocumentMetaData; setMetaData: SetMetaData };
  registerBeforeSubmit: RegisterBeforeSubmit;
}) {
  return (
    <TypedSlot
      name="document_form_extra"
      data={{
        action: "receive",
        documentType: docType,
        partnerId: (partnersEnabled && partnerId) || null,
        lines: lines.map(draftLineView),
        metaData: meta.metaData,
        setMetaData: meta.setMetaData,
        registerBeforeSubmit,
      }}
    />
  );
}

/**
 * The keyboard walk through the sheet: Enter on a count moves to the next
 * row's count, and past the last one back to the scan field; a scanned
 * product lands on its row and puts the reader on that row's count. The
 * phone's list of goods with no order is the same rows, edited the same way.
 */
function useLineEntry(args: {
  lines: ReceiveDraftLine[];
  setLines: Dispatch<SetStateAction<ReceiveDraftLine[]>>;
  setFocusLineKey: (key: string | null) => void;
  setProblem: (problem: ProblemKey | null) => void;
  scanRef: RefObject<HTMLInputElement>;
}) {
  const { lines, setLines, setFocusLineKey, setProblem, scanRef } = args;
  const quantityEnter = useCallback(
    (index: number) => {
      const next = lines[index + 1];
      if (next) setFocusLineKey(next.key);
      else scanRef.current?.focus();
    },
    [lines, scanRef, setFocusLineKey],
  );

  const addProduct = useCallback(
    (product: ProductSearchResult) => {
      const result = withScannedProduct(lines, product);
      setLines(result.lines);
      setFocusLineKey(result.focusKey);
      setProblem(null);
    },
    [lines, setFocusLineKey, setLines, setProblem],
  );

  const goods: PhoneGoods = {
    lines,
    scanRef,
    onSelect: addProduct,
    onUpdate: (key, patch) =>
      setLines((current) => patchRow(current, key, patch)),
    onRemove: (key) => setLines((current) => dropRow(current, key)),
  };

  return { quantityEnter, addProduct, goods };
}

/**
 * The refusal a post met, and the way out of it when it has one. A supplier
 * without a tax ID is refused under rules that ask for one; the refusal names
 * three ways out and the partner is the one a first-day reader cannot find.
 */
function usePostError(partnerId: string, t: TFunction) {
  const [postError, setPostErrorText] = useState<string | null>(null);
  const [taxIdRefused, setTaxIdRefused] = useState(false);
  const setPostError = useCallback(
    (message: string | null, code?: string | null) => {
      setPostErrorText(message);
      setTaxIdRefused(code === TAX_ID_REFUSED);
    },
    [],
  );
  const postErrorFix =
    taxIdRefused && partnerId
      ? {
          to: `/partners?edit=${partnerId}`,
          label: t("receive.errors.openPartner"),
        }
      : null;
  return { postError, setPostError, postErrorFix };
}

/** The order the reader chose, or the first one the supplier has open. */
function chosenOf<T extends { id: string }>(orders: T[], id: string | null) {
  return orders.find((order) => order.id === id) ?? orders[0] ?? null;
}

export default function ReceiveGoodsPage() {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const canWrite = useCanWrite("warehouse");
  const { isModuleEnabled } = useModules();
  const partnersEnabled = isModuleEnabled("partners");

  // A receipt puts goods down: it is offered what may hold stock, never a
  // place another module claims, whatever the general lists mix.
  const {
    total: locationCount,
    first: firstLocations,
    isError: locationsFailed,
    emptyReason,
  } = useLocationOffer({ purpose: "stock" });
  const { data: profile } = useDocumentProfile();
  const [source, setSource] = useState<ReceiveSource>("supplier");
  const docType = RECEIVE_SOURCE_TYPE[source];
  const valueNeeded = useShowDocumentValue(docType);
  const [pricesChoice, setPricesChoice] = useState<boolean | null>(null);
  const showPrices = pricesChoice ?? valueNeeded;

  const [partnerId, setPartnerId] = useState("");
  // The field is hidden for an internal receipt; the picker keeps the
  // supplier list the sheet opened with rather than reading another one.
  const partnerPicker = usePartnerPicker(
    partnerTypesFor(source),
    partnerId || undefined,
  );
  const [targetLocationId, setTargetLocationId] = useState("");
  const [externalReference, setExternalReference] = useState("");
  const [lines, setLines] = useState<ReceiveDraftLine[]>([]);
  const [focusLineKey, setFocusLineKey] = useState<string | null>(null);
  const [problem, setProblem] = useState<ProblemKey | null>(null);
  const { postError, setPostError, postErrorFix } = usePostError(partnerId, t);
  const [importOpen, setImportOpen] = useState(false);
  const [result, setResult] = useState<PostedReceipt | null>(null);
  // What the last paste could not put on the sheet. Kept until the next
  // paste, so the reader sees the rows the catalogue refused.
  const [refused, setRefused] = useState<RefusedPaste | null>(null);
  // The server's question about a surplus past the tolerance, for a reader
  // who may receive over it; yes sends the same receipt again.
  const { ask: askSurplus, dialog: surplusDialog } = useSurplusQuestion();
  const scanRef = useRef<HTMLInputElement>(null);
  // Both doors build the same receipt; a held key repeats before React re-renders.
  const submitting = useRef(false);
  // A press is named by a key the server remembers: sent again after the
  // answer was lost, it is answered with the document the first send made,
  // not a second receipt. Changing a line makes another press, with its key.
  const press = useRef<{ key: string; body: string } | null>(null);
  // What other modules' fields on this sheet save before it is sent, and
  // what they put on the document itself.
  const extensions = useDraftExtensions();
  const documentMeta = useDocumentMetaData();

  // Only a supplier's delivery brings a purchase order with it: a return and
  // an internal receipt have none to load, and a customer has no orders.
  const delivery = useDeliveryOrder(
    source === "supplier" ? partnerId : "",
    setPartnerId,
    setLines,
    setFocusLineKey,
    source === "supplier",
  );
  const { orders, chosenOrder, setChosenOrderId, forgetOrder } = delivery;
  useSheetGuard({ lines, externalReference, partnerId, delivery, result });

  useOnlyWarehouse(
    locationCount,
    firstLocations,
    targetLocationId,
    setTargetLocationId,
  );

  // The scan field is where the work starts; the result screen has none.
  useEffect(() => {
    if (!result) scanRef.current?.focus();
  }, [result]);

  const plan = useReceiptPlan(lines, targetLocationId || null);
  const totals = useMemo(() => draftTotals(lines), [lines]);
  // Every outstanding order line counts, including the ones this delivery
  // does not mention: a line the reader removed did not arrive, and the order
  // still waits for it.
  const short = shortDelivery(lines, chosenOrder?.lines ?? []);
  const postNew = usePostNewDocument();
  const createDraft = useCreateDocument();
  const changeTarget = useCallback((next: string) => {
    setTargetLocationId(next);
    setProblem(null);
  }, []);

  const changePartner = useCallback(
    (next: string) => {
      // The supplier already chosen is not another supplier: its order and
      // the lines taken from it stay, as they do for a source pressed twice.
      if (next === partnerId) return;
      setPartnerId(next);
      forgetOrder();
      setProblem(null);
      setPostError(null);
      setLines(withoutOrderLines);
    },
    [forgetOrder, partnerId, setPostError],
  );

  // Another answer to where the goods come from: the partner and the order
  // belonged to the previous one. Rows the reader typed stay — the goods in
  // their hands did not change — while rows from the supplier's order go,
  // because only a delivery may credit that order. Pressing the answer
  // already chosen is not another answer: the choice group reports it too,
  // and clearing here would throw away the receipt being counted.
  const changeSource = useCallback(
    (next: ReceiveSource) => {
      if (next === source) return;
      setSource(next);
      setPartnerId("");
      forgetOrder();
      setProblem(null);
      setPostError(null);
      setLines(withoutOrderLines);
      // The document number belonged to the previous source's paperwork.
      setExternalReference("");
    },
    [forgetOrder, setPostError, source],
  );

  const budgetProblem = useCallback((): Refusal | null => {
    // An internal receipt names nobody outside the company.
    if (source !== "internal" && partnersEnabled && !partnerId) {
      return { problem: "noPartner" };
    }
    return draftProblem(lines, targetLocationId);
  }, [lines, partnerId, partnersEnabled, source, targetLocationId]);

  const clearRefusals = useCallback(() => {
    setPostError(null);
    setProblem(null);
  }, [setPostError]);

  const showProblem = useCallback((refusal: Refusal) => {
    setProblem(refusal.problem);
    // A row's own count is the cause: the row's quantity takes the focus, as
    // it does after a scan or a paste. Everything else points at its field.
    if (refusal.lineKey) setFocusLineKey(refusal.lineKey);
    else focusProblem(refusal.problem, scanRef.current);
  }, []);

  const payload = useCallback(
    () =>
      toDocumentCreate({
        docType,
        partnerId: partnersEnabled && source !== "internal" ? partnerId : null,
        targetLocationId,
        externalReference,
        lines,
        includePrices: showPrices,
        metaData: documentMeta.metaData,
      }),
    [
      docType,
      documentMeta.metaData,
      externalReference,
      lines,
      partnerId,
      partnersEnabled,
      showPrices,
      source,
      targetLocationId,
    ],
  );

  const { post, finishLater } = useSheetPresses({
    canWrite,
    result,
    submitting,
    press,
    budgetProblem,
    showProblem,
    clearRefusals,
    runBeforeSubmit: extensions.runBeforeSubmit,
    payload,
    save: createDraft.mutateAsync,
    send: postNew.mutateAsync,
    askSurplus,
    navigate,
    t,
    totals,
    order: chosenOrder,
    shortCount: short.count,
    holdsGoods: lines.some(isHeld),
    onPosted: setResult,
    onPostError: setPostError,
  });

  const { quantityEnter, addProduct, goods } = useLineEntry({
    lines,
    setLines,
    setFocusLineKey,
    setProblem,
    scanRef,
  });

  const phoneDoor = usePhoneDoor(canWrite, finishLater);

  useReceiveHeader(result?.document ?? null);

  usePostShortcut(post, result, importOpen);

  if (result) {
    return (
      <ReceiveResult
        posted={result}
        onAnother={() => {
          setResult(null);
          setLines([]);
          setExternalReference("");
          setPartnerId("");
          forgetOrder();
          setRefused(null);
          documentMeta.resetMetaData();
        }}
      />
    );
  }

  // A form whose every field is filled in before the refusal is work thrown
  // away: the account that cannot post is told so once, here, and sees no
  // pickers.
  if (!canWrite) return <ReadOnlyNotice module="warehouse" />;

  return (
    <div className="space-y-4">
      <ReadOnlyNotice module="warehouse" />

      <Card className="p-4">
        <ReceiveHeaderFields
          source={source}
          docType={docType}
          onSourceChange={changeSource}
          partnersEnabled={partnersEnabled}
          partnerId={partnerId}
          partnerOptions={partnerPicker.options}
          onPartnerSearch={partnerPicker.setSearch}
          partnersLoading={partnerPicker.loading}
          partnersError={partnerPicker.error}
          onRetryPartners={partnerPicker.retry}
          onPartnerChange={changePartner}
          targetLocationId={targetLocationId}
          onTargetChange={changeTarget}
          targetError={targetProblem(t, problem, source)}
          locationsEmptyReason={emptyReason}
          locationsFailed={locationsFailed}
          externalReference={externalReference}
          onExternalReferenceChange={setExternalReference}
          ordersLoading={orders.isLoading}
          ordersError={orders.error}
          onRetryOrders={() => void orders.refetch()}
          orderCount={orders.orders.length}
          chosenOrderId={chosenOrder?.id ?? null}
          chosenOrderNumber={chosenOrder?.number ?? null}
          chosenLineCount={chosenOrder?.lines.length ?? 0}
          orderOptions={orderOptions(orders.orders)}
          onOrderChange={setChosenOrderId}
        />
      </Card>

      <OrderOpenReceipts order={chosenOrder} />

      <ReceiveDraftSlot
        partnerId={partnerId}
        partnersEnabled={partnersEnabled}
        docType={docType}
        lines={lines}
        meta={documentMeta}
        registerBeforeSubmit={extensions.registerBeforeSubmit}
      />

      {phoneDoor ? (
        <ReceivePhoneStart
          door={phoneDoor}
          hasOrder={chosenOrder !== null}
          ordersLoading={orders.isLoading}
          goods={goods}
          error={problem ? problemMessage(t, problem, source) : postError}
        />
      ) : (
        <>
          <ReceiveLinesCard
            registerBeforeSubmit={extensions.registerBeforeSubmit}
            lines={lines}
            emptyHint={emptyHint(t, source)}
            plans={plan.plansByKey}
            planFetching={plan.isFetching}
            showPrices={showPrices}
            taxHandling={profile?.tax_handling ?? "NONE"}
            canWrite={canWrite}
            focusLineKey={focusLineKey}
            shortKeys={short.rowKeys}
            scanRef={scanRef}
            onSelectProduct={addProduct}
            onFocusHandled={() => setFocusLineKey(null)}
            onUpdate={goods.onUpdate}
            onRemove={goods.onRemove}
            onQuantityEnter={quantityEnter}
            onOpenImport={() => setImportOpen(true)}
            onTogglePrices={() => setPricesChoice(!showPrices)}
          />

          {refused && <PasteRefusedNotice refused={refused} />}

          <UnpricedLinesNotice
            unpriced={unpricedCount(lines, valueNeeded)}
            pricesShown={showPrices}
            onShowPrices={() => setPricesChoice(true)}
          />

          {plan.error != null && (
            <p role="alert" className="text-sm text-on-warning">
              {t("receive.errors.previewFailed")}
            </p>
          )}

          <ReceiveFooter
            lineCount={totals.count}
            quantity={totalQuantity(totals)}
            shortCount={short.count}
            fromOrder={chosenOrder !== null}
            problemText={problem ? problemMessage(t, problem, source) : null}
            postLabel={postLabel(t, source)}
            postError={postError}
            postErrorFix={postErrorFix}
            canWrite={canWrite}
            savingDraft={createDraft.isPending}
            posting={postNew.isPending}
            onFinishLater={() => void finishLater()}
            onPost={() => void post()}
          />
        </>
      )}

      {surplusDialog}

      {importOpen && (
        <Suspense fallback={null}>
          <DocumentImportModal
            documentType={docType}
            onClose={() => setImportOpen(false)}
            onImported={(result) => {
              const applied = importOutcome(lines, result);
              setLines(applied.lines);
              setRefused(applied.refused);
              setImportOpen(false);
            }}
          />
        </Suspense>
      )}
    </div>
  );
}
