import type { TFunction } from "i18next";

import type { components } from "@/types/api-generated";
import { formatMoney } from "@/utils/formatters";

export type WorkflowScope = components["schemas"]["WorkflowScope-Output"];
type WorkflowScopeCondition =
  components["schemas"]["WorkflowScopeCondition-Output"];

/**
 * Where each target type's own settings say what needs approval — the place a
 * reader is sent to change what a workflow holds. A target type whose module
 * has no such screen (equipment checkouts: an active workflow holds every
 * checkout) is simply not listed.
 */
const SETTINGS_PATHS: Record<string, string> = {
  document: "/warehouse/settings?section=approvals",
  purchase_order: "/purchase-orders/settings",
};

export function scopeSettingsPath(targetType: string): string | null {
  return SETTINGS_PATHS[targetType] ?? null;
}

/*
 * Each phrase per target type, with the generic wording as the fallback.
 * Every key is spelled out in its own t() call, so the catalogue check sees
 * each one consumed.
 */
function allPhrase(t: TFunction, targetType: string): string {
  switch (targetType) {
    case "document":
      return t("approvals:workflows.scope.allDocuments");
    case "purchase_order":
      return t("approvals:workflows.scope.allPurchaseOrders");
    case "equipment_checkout":
      return t("approvals:workflows.scope.allCheckouts");
    default:
      return t("approvals:workflows.scope.allOfKind");
  }
}

function nothingPhrase(t: TFunction, targetType: string): string {
  return targetType === "purchase_order"
    ? t("approvals:workflows.scope.nothingPurchaseOrders")
    : t("approvals:workflows.scope.nothing");
}

function valueAbovePhrase(
  t: TFunction,
  targetType: string,
  amount: string,
): string {
  switch (targetType) {
    case "document":
      return t("approvals:workflows.scope.documentsAbove", { amount });
    case "purchase_order":
      return t("approvals:workflows.scope.purchaseOrdersAbove", { amount });
    default:
      return t("approvals:workflows.scope.anythingAbove", { amount });
  }
}

function valueAboveOrUnpricedPhrase(
  t: TFunction,
  targetType: string,
  amount: string,
): string {
  switch (targetType) {
    case "document":
      return t("approvals:workflows.scope.documentsAboveOrUnpriced", {
        amount,
      });
    case "purchase_order":
      return t("approvals:workflows.scope.purchaseOrdersAboveOrUnpriced", {
        amount,
      });
    default:
      return t("approvals:workflows.scope.anythingAboveOrUnpriced", {
        amount,
      });
  }
}

function describeCondition(
  t: TFunction,
  targetType: string,
  condition: WorkflowScopeCondition,
): string {
  switch (condition.kind) {
    case "document_types":
      return t("approvals:workflows.scope.documentTypes", {
        types: condition.document_types
          .map((type) =>
            t(`approvals:dashboard.docTypes.${type}`, { defaultValue: type }),
          )
          .join(", "),
      });
    case "value_above": {
      const amount = formatMoney(condition.amount, condition.currency);
      return condition.unpriced_included
        ? valueAboveOrUnpricedPhrase(t, targetType, amount)
        : valueAbovePhrase(t, targetType, amount);
    }
    case "foreign_currency":
      return t("approvals:workflows.scope.foreignCurrency", {
        currency: condition.currency ?? "",
      });
  }
}

/**
 * What a workflow of this target type holds, as one phrase the workflow card
 * and the switch-on dialog both use.
 *
 * The scope is the owning module's answer (its gate's own rule), never worked
 * out here: this only puts it into words.
 */
export function describeWorkflowScope(
  t: TFunction,
  targetType: string,
  scope: WorkflowScope,
): string {
  if (scope.holds === "all") {
    return allPhrase(t, targetType);
  }
  if (scope.holds === "nothing") {
    return nothingPhrase(t, targetType);
  }
  return scope.conditions
    .map((condition) => describeCondition(t, targetType, condition))
    .join("; ");
}
