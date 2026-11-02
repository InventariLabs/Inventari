import { useTranslation } from "react-i18next";

import {
  executionHintKey,
  type ApprovalGate,
} from "@/modules/warehouse/components/documentApprovalGate";

/**
 * Says on the card why execution is closed while approval is required and no
 * request is open — the disabled buttons carry the same words only as a hover
 * title, which a phone never shows.
 */
export function ApprovalRequiredNotice({ gate }: { gate: ApprovalGate }) {
  const { t } = useTranslation("warehouse");
  const key = gate.approvalRequiredNoRequest
    ? executionHintKey(gate)
    : undefined;
  if (!key) return null;
  return (
    <p
      data-testid="approval-required-notice"
      className="rounded-xl border border-border/60 bg-surface-inset px-4 py-3 text-sm text-on-secondary"
    >
      {t(key)}
    </p>
  );
}
