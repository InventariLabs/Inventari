import type { TFunction } from "i18next";

/**
 * Campaign and response statuses arrive as codes and used to render as codes
 * — DRAFT, ACTIVE, PENDING — in an interface whose asset statuses are
 * translated. Static keys keep the i18n unused-key gate honest: a template
 * literal would report all nine as orphans.
 */
const CAMPAIGN_STATUS_KEYS: Record<string, string> = {
  DRAFT: "attestation.status.DRAFT",
  ACTIVE: "attestation.status.ACTIVE",
  COMPLETED: "attestation.status.COMPLETED",
  CANCELLED: "attestation.status.CANCELLED",
};

const RESPONSE_STATUS_KEYS: Record<string, string> = {
  PENDING: "attestation.responseStatus.PENDING",
  CONFIRMED: "attestation.responseStatus.CONFIRMED",
  DISPUTED: "attestation.responseStatus.DISPUTED",
  EXPIRED: "attestation.responseStatus.EXPIRED",
  RETURNED: "attestation.responseStatus.RETURNED",
};

const SCOPE_KEYS: Record<string, string> = {
  ALL: "attestation.scope.all",
  STORAGE: "attestation.scope.storage",
  CATEGORY: "attestation.scope.category",
};

/** Campaign status in the reader's language; the code itself if unknown. */
export function campaignStatusLabel(t: TFunction, status: string): string {
  const key = CAMPAIGN_STATUS_KEYS[status];
  return key ? t(key) : status;
}

/** Response status in the reader's language; the code itself if unknown. */
export function responseStatusLabel(t: TFunction, status: string): string {
  const key = RESPONSE_STATUS_KEYS[status];
  return key ? t(key) : status;
}

/** Scope type in the reader's language; the code itself if unknown. */
export function campaignScopeLabel(t: TFunction, scopeType: string): string {
  const key = SCOPE_KEYS[scopeType];
  return key ? t(key) : scopeType;
}

/**
 * The status a response is shown with. An unanswered response whose assets
 * have all come back is not waiting for anybody: it read "Awaiting reply"
 * while the person's own link already said "Already Returned".
 */
export function responseDisplayStatus(response: {
  status: string;
  assets_returned?: boolean;
}): string {
  return response.status === "PENDING" && response.assets_returned
    ? "RETURNED"
    : response.status;
}

/**
 * The kind of issue a person reported, in the reader's language. Four written
 * calls rather than a key table: the unused-key gate then sees each key used.
 */
export function disputeTypeLabel(t: TFunction, disputeType: string): string {
  switch (disputeType) {
    case "MISSING":
      return t("equipment:attestation.disputeType.MISSING");
    case "DAMAGED":
      return t("equipment:attestation.disputeType.DAMAGED");
    case "WRONG_ITEM":
      return t("equipment:attestation.disputeType.WRONG_ITEM");
    case "OTHER":
      return t("equipment:attestation.disputeType.OTHER");
    default:
      return disputeType;
  }
}

/**
 * What closing a campaign asks the reader to accept. Closing refuses every
 * answer still out, so the question says how many that is when it is known.
 */
export function completeMessage(
  t: TFunction,
  responses: { status: string; assets_returned?: boolean }[] | null,
): string {
  const unanswered = (responses ?? []).filter(
    (r) => responseDisplayStatus(r) === "PENDING",
  ).length;
  return unanswered > 0
    ? t("equipment:attestation.confirm.completeMessageUnanswered", {
        count: unanswered,
      })
    : t("equipment:attestation.confirm.completeMessage");
}
