import type { TFunction } from "i18next";

import type { components } from "@/types/api-generated";
import type { ApprovalWorkflow } from "@/modules/approvals/api/approvals";
import { roleLabel } from "@/modules/approvals/roleLabels";

/** Whose submissions a workflow holds, as the form edits it. */
export type RequesterScope = components["schemas"]["RequesterScope"];

/**
 * Whether a scope names somebody: everyone, or at least one person or role.
 *
 * "Chosen people" with nobody chosen is not a workflow that holds nobody —
 * the server refuses it, and the form says so before the save is offered.
 */
export function requesterScopeNamesSomebody(
  scope: RequesterScope | null,
): scope is RequesterScope {
  if (scope === null) return false;
  return (
    scope.everyone ||
    (scope.user_ids ?? []).length > 0 ||
    (scope.role_ids ?? []).length > 0
  );
}

/**
 * "Documents submitted by: Storeman, Kasia" — the sentence the card and the
 * switch-on dialog both show, so neither reads one way and the other another.
 *
 * The names come from the list (`requesters`), resolved on the server: most
 * readers of the card may not open the roles listing. A built-in level is
 * translated; a role the organization named and a person are shown as named.
 */
export function describeRequesters(
  t: TFunction,
  workflow: Pick<
    ApprovalWorkflow,
    "target_type" | "requester_scope" | "requesters"
  >,
): string {
  const names = workflow.requester_scope.everyone
    ? t("approvals:workflows.requesters.everyoneNames")
    : (workflow.requesters ?? [])
        .map((r) =>
          r.kind === "role" && r.is_system ? roleLabel(t, r.name) : r.name,
        )
        .join(", ");
  // One literal call per target type, so the catalogue check sees each key.
  switch (workflow.target_type) {
    case "document":
      return t("approvals:workflows.requesters.line_document", { names });
    case "purchase_order":
      return t("approvals:workflows.requesters.line_purchase_order", { names });
    case "equipment_checkout":
      return t("approvals:workflows.requesters.line_equipment_checkout", {
        names,
      });
    default:
      return t("approvals:workflows.requesters.line_other", { names });
  }
}
