import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { useHasPermission } from "@/module-sdk";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { formatMoney } from "@/utils/formatters";
import type { PurchaseOrder } from "../types/purchase-orders";
import { usePOApprovalRequirement, usePOSettings } from "./usePurchaseOrders";

const NAMED = "named_approvers_cannot_decide";
const ONLY_REQUESTER = "only_the_requester_can_decide";

/**
 * Why nobody could decide the approval, what would let somebody do it, and what
 * confirming does meanwhile. The cause and the way out are the sentences the
 * parked request carries (`ApprovalDeadEndNotice`), said before the click, and
 * they differ for a reader who can give the access and one who has to ask.
 */
function deadEndSentence(
  requirement: {
    undecidable_reason?: string | null;
    undecidable_stage?: string | null;
  },
  isAdmin: boolean,
  t: TFunction<["purchase_orders", "approvals"]>,
  whatHappensMeanwhile: string,
): string {
  const reason = requirement.undecidable_reason;
  const inApprovals = (key: string) => t(key, { ns: "approvals" });
  const cause =
    reason === NAMED
      ? inApprovals("request.deadEndCauseNamedUnknown")
      : reason === ONLY_REQUESTER
        ? inApprovals("request.deadEndCauseOnlyRequester")
        : inApprovals("request.deadEndCauseNoApprover");
  const wayOut = !isAdmin
    ? reason === NAMED
      ? inApprovals("request.deadEndStepAskAdminNamedUnknown")
      : inApprovals("request.deadEndStepAskAdminApprove")
    : reason === NAMED
      ? inApprovals("request.deadEndStepGrantNamedUnknown")
      : reason === ONLY_REQUESTER
        ? `${inApprovals("request.deadEndStepGrantApprove")} ${inApprovals("request.deadEndStepAllowSelf")}`
        : inApprovals("request.deadEndStepGrantApprove");
  // The title stands alone in `ApprovalDeadEndNotice`; run into one line it
  // needs the full stop that its own paragraph spares it.
  return [
    `${inApprovals("request.deadEndTitle")}.`,
    cause,
    wayOut,
    whatHappensMeanwhile,
  ].join(" ");
}

/**
 * What confirming THIS order will actually do, as a sentence.
 *
 * The dialog names what this organization configured, not a default with a
 * condition for the reader to resolve. Reading `approval_required` as the
 * whole answer is what left the "off" branch carrying the sentence *"if
 * your organization requires purchase approval, confirming first sends it
 * to the approval queue"* — a condition the reader cannot settle from the
 * screen it stands on, in the one branch that was chosen because the flag
 * had already settled it.
 *
 * `_is_approval_required` (backend `_service_workflow.py`) answers in three
 * shapes and this follows them one for one:
 *
 *   * the flag is on             → the queue, certainly;
 *   * the flag is off and no
 *     threshold is stored        → no queue, ever — the function returns
 *                                  False before it looks at anything else,
 *                                  so nothing here is conditional;
 *   * the flag is off and a
 *     threshold is stored        → this order's net total decides, so the
 *                                  message names the number the
 *                                  organization configured instead of
 *                                  asking the reader whether there is one.
 *
 * Two cases inside the third are decided without any comparison — a
 * currency the threshold is not denominated in (there is no FX conversion,
 * so cross-currency orders are routed to approval outright) and a total no
 * line price lets anyone state. Both mean the queue for certain, and
 * naming the threshold there would describe a comparison that never runs.
 *
 * The order's own total is deliberately *not* recomputed here: the
 * comparison stays the backend's, and this only picks which of the three
 * sentences is true.
 *
 * Once the server has answered, its answer decides whether the order goes to
 * the queue, and whether anybody could decide it there: the sentence must not
 * call a dead end "the approval queue". The reading above stands in until
 * then, and for an organization with the approvals module off.
 */
export function usePOConfirmMessage(po: PurchaseOrder | null): string {
  const { t } = useTranslation(["purchase_orders", "approvals"]);
  const isAdmin = useHasPermission("admin:access");
  const { data: settings } = usePOSettings();
  const requirement = usePOApprovalRequirement(po);
  const orgCurrency = useOrganizationCurrency();

  const threshold = settings?.approval_threshold ?? null;
  const crossCurrency =
    !!po?.currency && !!orgCurrency && po.currency !== orgCurrency;
  const totalUnstatable = (po?.lines ?? []).some(
    (line) => line.unit_price == null,
  );

  const queued =
    requirement?.approval_required ??
    (settings?.approval_required ||
      (threshold != null && (crossCurrency || totalUnstatable)));

  if (queued) {
    const consequence =
      requirement?.approval_solvable === false
        ? deadEndSentence(
            requirement,
            isAdmin,
            t,
            t("confirmOrderDeadEndWaits", {
              stage: requirement.undecidable_stage ?? "",
            }),
          )
        : t("confirmOrderDescriptionApproval");
    // Pricing the lines is a way out only where the missing price is what
    // sends the order to approval: the threshold is the one rule in play.
    return threshold != null &&
      !settings?.approval_required &&
      !crossCurrency &&
      totalUnstatable
      ? `${t("confirmOrderUnpriced", {
          threshold: formatMoney(threshold, orgCurrency),
        })} ${consequence}`
      : consequence;
  }
  if (threshold != null) {
    return t("confirmOrderDescriptionThreshold", {
      threshold: formatMoney(threshold, orgCurrency),
    });
  }
  return t("confirmOrderDescription");
}

/**
 * What asking for approval on THIS draft will do, as a sentence.
 *
 * Asking parks the order whatever the rules say, so `approval_required` has no
 * part in this: the server's verdict on who could decide the request stands
 * alone, and until it has answered the plain sentence stands in.
 */
export function usePORequestApprovalMessage(po: PurchaseOrder): string {
  const { t } = useTranslation(["purchase_orders", "approvals"]);
  const isAdmin = useHasPermission("admin:access");
  const requirement = usePOApprovalRequirement(po);

  return requirement?.approval_solvable === false
    ? deadEndSentence(
        requirement,
        isAdmin,
        t,
        t("requestApprovalDeadEndWaits", {
          number: po.number,
          stage: requirement.undecidable_stage ?? "",
        }),
      )
    : t("requestApprovalDescription", { number: po.number });
}
