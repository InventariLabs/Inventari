import { useMemo } from "react";
import type { TFunction } from "i18next";
import { useModules } from "@/contexts/ModulesContext";

/**
 * Target types selectable when creating a new approval workflow.
 *
 * A target type belongs here once a module actually creates approval requests
 * for it — that is, passes it to `approvals_api.request_approval`. Three
 * modules do today: documents (confirm-over-threshold and its approval proxy),
 * purchase_orders (`_service_workflow.py`, `_router_approval.py`) and
 * equipment (`_router_approvals.py`, checkout requests).
 *
 * The list used to hold "document" alone, justified by a comment claiming the
 * other two never call approvals_api. They did, in ten places, so the workflow
 * a purchase order needed could not be created from this screen at all. The
 * companion test reads those call sites out of the backend rather than
 * repeating this list, so the next integration fails the gate instead of
 * silently sitting outside the editor.
 */
export const AVAILABLE_TARGET_TYPES = [
  "document",
  "purchase_order",
  "equipment_checkout",
] as const;

/**
 * The module that raises the requests of each target type. A workflow for a
 * target whose module is switched off can never hold anything — a home
 * organization without the warehouse was offered documents and purchase
 * orders, and could save and switch on a workflow guarding nothing.
 */
const TARGET_TYPE_MODULES: Record<
  (typeof AVAILABLE_TARGET_TYPES)[number],
  string
> = {
  document: "warehouse",
  purchase_order: "purchase_orders",
  equipment_checkout: "equipment",
};

/** The target types a new workflow may be created for in this organization. */
function offeredTargetTypes(enabledModules: readonly string[]): string[] {
  return AVAILABLE_TARGET_TYPES.filter((type) =>
    enabledModules.includes(TARGET_TYPE_MODULES[type]),
  );
}

/** The target types the organization's switched-on modules can raise. */
export function useOfferedTargetTypes(): string[] {
  const { enabledModules } = useModules();
  return useMemo(() => offeredTargetTypes(enabledModules), [enabledModules]);
}

/**
 * Display labels for every known target type. Existing workflows may still
 * reference a type that has since lost its integration, so card/summary
 * surfaces read labels from here rather than from the selectable list.
 */
const TARGET_TYPE_LABEL_KEYS: Record<string, string> = {
  document: "workflows.targetType_document",
  equipment_checkout: "workflows.targetType_equipment_checkout",
  purchase_order: "workflows.targetType_purchase_order",
};

/** Resolve a target type to a translated label, falling back to the raw value. */
export function targetTypeLabel(t: TFunction, targetType: string): string {
  const key = TARGET_TYPE_LABEL_KEYS[targetType];
  return key ? t(key) : targetType;
}

/**
 * Where a request's target lives, for the screens that point a reader at it.
 * A target type missing here has no page to go to, and a caller renders no
 * link rather than one that lands on a 404.
 */
const TARGET_PATHS: Record<string, (targetId: string) => string> = {
  document: (id) => `/warehouse/documents/${id}`,
  purchase_order: (id) => `/purchase-orders/${id}`,
  equipment_checkout: (id) => `/equipment/${id}`,
};

export function targetPath(
  targetType: string,
  targetId: string,
): string | null {
  const path = TARGET_PATHS[targetType];
  return path ? path(targetId) : null;
}
