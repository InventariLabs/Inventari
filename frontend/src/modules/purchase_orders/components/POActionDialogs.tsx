import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import type { PurchaseOrder } from "../types/purchase-orders";
import {
  usePOConfirmMessage,
  usePORequestApprovalMessage,
} from "../hooks/usePOConfirmMessage";

export type POActionType =
  | "confirm"
  | "cancel"
  | "send"
  | "approve"
  | "reject"
  | "requestApproval"
  | null;

interface POActionDialogsProps {
  po: PurchaseOrder;
  actionType: POActionType;
  partnerEmail: string | null;
  onConfirm: () => void;
  onCancel: () => void;
  /** Rejecting requires a reason, the same way the approval panel collects it. */
  onReject: (reason: string) => void;
}

export function POActionDialogs({
  po,
  actionType,
  partnerEmail,
  onConfirm,
  onCancel,
  onReject,
}: POActionDialogsProps) {
  const { t } = useTranslation(["purchase_orders", "common"]);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectReasonError, setRejectReasonError] = useState(false);
  // What confirming does is decided by more than the approval flag; the
  // hook holds that reading, and the list page's dialog shares it.
  const confirmMessage = usePOConfirmMessage(po);
  const requestApprovalMessage = usePORequestApprovalMessage(po);

  useEffect(() => {
    if (actionType === "reject") {
      setRejectReason("");
      setRejectReasonError(false);
    }
  }, [actionType]);

  return (
    <>
      <ConfirmDialog
        open={actionType === "confirm"}
        title={t("confirmOrder", { number: po.number })}
        message={confirmMessage}
        confirmLabel={t("confirm")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />

      <ConfirmDialog
        open={actionType === "cancel"}
        title={t("cancelOrder", { number: po.number })}
        message={t("cancelOrderDescription")}
        variant="danger"
        confirmLabel={t("cancelOrderAction")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />

      <ConfirmDialog
        open={actionType === "approve"}
        title={t("approveOrder", { number: po.number })}
        message={t("approveOrderDescription")}
        confirmLabel={t("approve")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />

      <ConfirmDialog
        open={actionType === "reject"}
        title={t("rejectOrder", { number: po.number })}
        message={t("rejectOrderDescription")}
        variant="danger"
        confirmLabel={t("reject")}
        cancelLabel={t("common:form.cancel")}
        confirmDisabled={!rejectReason.trim()}
        onConfirm={() => {
          if (!rejectReason.trim()) {
            setRejectReasonError(true);
            return;
          }
          setRejectReasonError(false);
          onReject(rejectReason.trim());
        }}
        onCancel={() => {
          setRejectReason("");
          setRejectReasonError(false);
          onCancel();
        }}
      >
        {/* the header "Reject" skipped the reason the approval panel
            requires — two rejection paths, one without an audit trail. */}
        <Input
          label={t("rejectReasonPlaceholder")}
          value={rejectReason}
          onChange={(e) => {
            setRejectReason(e.target.value);
            if (rejectReasonError) setRejectReasonError(false);
          }}
          error={rejectReasonError ? t("rejectReasonRequired") : undefined}
        />
      </ConfirmDialog>

      <ConfirmDialog
        open={actionType === "requestApproval"}
        title={t("requestApproval")}
        message={requestApprovalMessage}
        confirmLabel={t("requestApproval")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />

      <ConfirmDialog
        open={actionType === "send"}
        title={t("sendToVendor")}
        message={
          partnerEmail
            ? t("sendEmailDescription", { email: partnerEmail })
            : t("sendEmailNoEmail")
        }
        confirmLabel={t("send")}
        cancelLabel={t("common:form.cancel")}
        // The dialog warned that there is no address and left Send live, so
        // the only way to learn it would not work was to press it and read a
        // server refusal in English.
        confirmDisabled={!partnerEmail}
        onConfirm={onConfirm}
        onCancel={onCancel}
      />
    </>
  );
}
