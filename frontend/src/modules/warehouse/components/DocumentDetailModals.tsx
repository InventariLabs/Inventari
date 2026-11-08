import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import DocumentFormModal from "@/modules/warehouse/components/DocumentFormModal";
import { CorrectionFormModal } from "@/modules/warehouse/components/CorrectionFormModal";
import { ReturnFormModal } from "@/modules/warehouse/components/ReturnFormModal";
import WmsPickingView from "@/modules/warehouse/components/picking/WmsPickingView";
import WmsReceivingView from "@/modules/warehouse/components/receiving/WmsReceivingView";
import WmsLotExpiryDialog from "@/modules/warehouse/components/receiving/WmsLotExpiryDialog";
import { isPackedType } from "@/modules/warehouse/components/packing/DocumentPackingStep";
import { PACKING_HASH } from "@/modules/warehouse/components/packing/packingHash";
import type { ShipmentCreate } from "@/modules/warehouse/api/shipments";
import type { WarehouseDocument } from "@/modules/warehouse/types";

/** The question the execution screen answers when a completion stops on a
 * record kept in another unit than the card its door adopts. */
export interface UnitMismatchPrompt {
  product: string;
  templateUnit: string;
  chosenUnit: string;
}

interface DocumentDetailModalsProps {
  doc: WarehouseDocument;
  editOpen: boolean;
  onEditClose: () => void;
  correctionOpen: boolean;
  onCorrectionClose: () => void;
  returnOpen: boolean;
  onReturnClose: () => void;
  pickingOpen: boolean;
  onPickingClose: (completed?: boolean, shipment?: ShipmentCreate) => void;
  onPickingRequestApproval?: () => void | Promise<void>;
  receivingOpen: boolean;
  onReceivingClose: (completed?: boolean) => void;
  onReceivingRequestApproval?: () => void | Promise<void>;
  confirmAction: "confirm" | "cancel" | "delete" | "postNow" | "undo" | null;
  confirmTitle: string;
  /** The one-step action only sends the document to the approval queue. */
  postNowSendsForApproval?: boolean;
  confirmMessage: string;
  confirmVariant: "danger" | "default";
  onConfirmAction: () => void;
  onConfirmCancel: () => void;
  onCompleteDocument?: (id: string) => void;
  unitMismatch?: UnitMismatchPrompt | null;
  onUnitMismatchConfirm?: () => void;
  onUnitMismatchClose?: () => void;
  /** The FEFO receipt line whose lot and expiry a completion or a one-step
   * posting is waiting for; the dialog asks for one line at a time. */
  receiptExpiry?: {
    prompt: { lineId: string; product: string };
    onConfirm: (batchNumber: string, expiryDate: string) => void;
    onClose: () => void;
  } | null;
}

export default function DocumentDetailModals({
  doc,
  editOpen,
  onEditClose,
  correctionOpen,
  onCorrectionClose,
  returnOpen,
  onReturnClose,
  pickingOpen,
  onPickingClose,
  onPickingRequestApproval,
  receivingOpen,
  onReceivingClose,
  onReceivingRequestApproval,
  confirmAction,
  confirmTitle,
  postNowSendsForApproval,
  confirmMessage,
  confirmVariant,
  onConfirmAction,
  onConfirmCancel,
  unitMismatch,
  onUnitMismatchConfirm,
  onUnitMismatchClose,
  receiptExpiry,
}: DocumentDetailModalsProps) {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const confirmLabels =
    confirmAction === "cancel"
      ? {
          confirm: t("confirmDialog.cancelConfirm"),
          keep: t("confirmDialog.cancelKeep"),
        }
      : confirmAction === "delete"
        ? {
            confirm: t("confirmDialog.deleteConfirm"),
            keep: t("confirmDialog.deleteKeep"),
          }
        : confirmAction === "postNow"
          ? {
              confirm: postNowSendsForApproval
                ? t("confirmDialog.postNowApprovalConfirm")
                : t("confirmDialog.postNowConfirm"),
              keep: t("confirmDialog.postNowKeep"),
            }
          : confirmAction === "undo"
            ? {
                confirm: t("confirmDialog.undoConfirm"),
                keep: t("confirmDialog.undoKeep"),
              }
            : null;
  return (
    <>
      {editOpen && <DocumentFormModal document={doc} onClose={onEditClose} />}

      {correctionOpen && (
        <CorrectionFormModal document={doc} onClose={onCorrectionClose} />
      )}

      {returnOpen && <ReturnFormModal document={doc} onClose={onReturnClose} />}

      {pickingOpen && (
        <WmsPickingView
          documentId={doc.id}
          onClose={(completed, shipment) => onPickingClose(completed, shipment)}
          onRequestApproval={onPickingRequestApproval}
          onPack={
            isPackedType(doc.type)
              ? (shipment) => {
                  // Closed without completing: the Pack step comes first,
                  // and takes the carrier already typed along with it.
                  onPickingClose(false);
                  navigate(PACKING_HASH, {
                    replace: true,
                    state: { shipment },
                  });
                }
              : undefined
          }
        />
      )}

      {receivingOpen && (
        <WmsReceivingView
          documentId={doc.id}
          onClose={(completed) => onReceivingClose(completed)}
          onRequestApproval={onReceivingRequestApproval}
        />
      )}

      {confirmAction && (
        <ConfirmDialog
          open={!!confirmAction}
          title={confirmTitle}
          message={confirmMessage}
          variant={confirmVariant}
          // Cancel and delete name what the button does and what the other
          // one keeps; "Cancel" beside "Cancel document" read as opposites.
          confirmLabel={confirmLabels?.confirm}
          cancelLabel={confirmLabels?.keep}
          onConfirm={onConfirmAction}
          onCancel={onConfirmCancel}
        />
      )}

      {receiptExpiry && (
        <WmsLotExpiryDialog
          // One instance per line: the sheet keeps what it was typed, and
          // the next line is another pack to read, not an answer to reuse.
          key={receiptExpiry.prompt.lineId}
          productName={receiptExpiry.prompt.product}
          isLoading={false}
          // The page is behind this question, not another sheet: at the
          // nested layer the date popover would open underneath it.
          zIndex="modal"
          onConfirm={receiptExpiry.onConfirm}
          onCancel={receiptExpiry.onClose}
        />
      )}

      {unitMismatch && onUnitMismatchConfirm && onUnitMismatchClose && (
        <ConfirmDialog
          open
          title={t("unitMismatch.title")}
          message={t("unitMismatch.message", {
            product: unitMismatch.product,
            templateUnit: unitMismatch.templateUnit,
            chosenUnit: unitMismatch.chosenUnit,
          })}
          confirmLabel={t("unitMismatch.confirm")}
          cancelLabel={t("unitMismatch.cancel")}
          onConfirm={onUnitMismatchConfirm}
          onCancel={onUnitMismatchClose}
        />
      )}
    </>
  );
}
