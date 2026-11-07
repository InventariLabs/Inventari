/**
 * Ask why, before changing what a batch is allowed to do.
 *
 * The API has always accepted a reason and the screen never collected one,
 * so every quarantine and every release went into the record saying only
 * that somebody clicked. That is precisely the question this screen exists
 * to answer six months later.
 *
 * The reason is required for releases as much as for holds. Letting a
 * recalled batch back onto the shelf is the decision an auditor asks about,
 * and a rule with one exception is two rules. The server enforces the same
 * thing, so an API client cannot walk around the dialog.
 */
import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Textarea } from "@/components/ui/Textarea";
import type { LotStatus } from "@/lib/api/stockLots";

export interface LotStatusRequest {
  lotId: string;
  lotName: string;
  status: LotStatus;
}

/** Which states mean "do not ship it" — those get the warning treatment. */
const HOLDING: ReadonlySet<string> = new Set([
  "quarantined",
  "held",
  "expired",
  "recalled",
]);

export function LotStatusDialog({
  request,
  onConfirm,
  onCancel,
}: {
  request: LotStatusRequest | null;
  onConfirm: (reason: string) => Promise<unknown>;
  onCancel: () => void;
}) {
  const { t } = useTranslation(["inventory", "common"]);
  const [reason, setReason] = useState("");

  // A reopened dialog starts empty: the last batch's reason is not this
  // batch's, and inheriting it is how a wrong explanation gets recorded.
  useEffect(() => {
    setReason("");
  }, [request]);

  if (!request) return null;

  const statusLabel = t(`inventory:lot.status.${request.status}`, {
    defaultValue: request.status,
  });

  return (
    <ConfirmDialog
      open
      variant={HOLDING.has(request.status) ? "warning" : "default"}
      title={t("inventory:lots.reasonDialog.title", {
        status: statusLabel,
        name: request.lotName,
      })}
      message={t("inventory:lots.reasonDialog.message")}
      confirmLabel={t("inventory:lots.reasonDialog.confirm")}
      cancelLabel={t("common:form.cancel")}
      confirmDisabled={!reason.trim()}
      onConfirm={() => onConfirm(reason.trim())}
      errorFallback={t("inventory:lots.reasonDialog.failed")}
      onCancel={onCancel}
    >
      <Textarea
        label={t("inventory:lots.reasonDialog.label")}
        placeholder={t("inventory:lots.reasonDialog.placeholder")}
        value={reason}
        onChange={(event) => setReason(event.target.value)}
        rows={3}
        maxLength={500}
        required
        autoFocus
      />
    </ConfirmDialog>
  );
}
