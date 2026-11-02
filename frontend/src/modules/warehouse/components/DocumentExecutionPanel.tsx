import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { useScanCamera } from "@/hooks/useScanCamera";
import { useScanResolver } from "@/hooks/useScanResolver";
import { useDocumentScanResult } from "../hooks/useDocumentScanResult";
import { ExecutionLineCard } from "./ExecutionLineCard";
import { ExecutionActions } from "./ExecutionActions";
import { ScanModeSection } from "./ScanModeSection";
import { isPackedType } from "./packing/DocumentPackingStep";
import { ShipmentFields } from "./shipping/ShipmentFields";
import {
  EMPTY_SHIPMENT,
  shipmentError,
  shipmentPayload,
} from "./shipping/shipmentDraft";
import { useDocumentExecution } from "@/modules/warehouse/hooks/useDocumentExecution";
import { getDocumentLineStatus } from "@/modules/warehouse/lineStatus";
import type {
  DocumentCompletePayload,
  WarehouseDocument,
} from "@/modules/warehouse/types";

interface DocumentExecutionPanelProps {
  document: WarehouseDocument;
  isPending: boolean;
  onCancel: () => void;
  onSubmit: (data: DocumentCompletePayload) => void;
}

export function DocumentExecutionPanel({
  document,
  isPending,
  onCancel,
  onSubmit,
}: DocumentExecutionPanelProps) {
  const { t } = useTranslation(["warehouse", "common"]);
  // The header's Execute button sits above the metadata card, so on a phone
  // this panel opens past the fold and the tap reads as dead. The panel only
  // exists once somebody asks for it, so mounting is that ask — the same
  // reveal the Pack step does from its hash.
  const cardRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    cardRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" });
  }, []);
  // Only goods coming in can be held back out of what arrived; a dispatch
  // takes stock off the shelf and a correction restates it.
  const isReceipt = document.type === "IN" || document.type === "INTERNAL_IN";
  // A dispatch leaves with a carrier, and this panel is one of the doors it
  // is completed through; every other type completes as it always did.
  const ships = isPackedType(document.type);
  const [shipment, setShipment] = useState(EMPTY_SHIPMENT);
  const [shipmentFault, setShipmentFault] = useState<string>();

  const submitWithShipment = (data: DocumentCompletePayload) => {
    const fault = ships ? shipmentError(shipment, t) : undefined;
    setShipmentFault(fault);
    if (fault) return;
    const shipped = ships ? shipmentPayload(shipment) : undefined;
    onSubmit(shipped ? { ...data, shipment: shipped } : data);
  };

  const exec = useDocumentExecution({
    document,
    onSubmit: submitWithShipment,
    t,
  });

  // The context is the point here: a line on this document has priority, and
  // the panel keeps its own matching. What it does not get to keep is the
  // verdict on a code that is not on this document — that goes to the shared
  // registry, so "not on this list" and "this is somebody else's code" stop
  // being the same message.
  const applyScanResult = useDocumentScanResult(
    document.lines,
    exec.applyScanToLine,
    t,
  );
  const { resolve } = useScanResolver({
    handle: async (result) => applyScanResult(result),
    // The panel already said the code is not on this document; a second,
    // vaguer message on top of it would only crowd the first.
    acceptUnrecognized: () => true,
  });

  const handleScannedCode = (code: string) => {
    if (exec.applyScanCode(code)) return;
    void resolve(code);
  };

  const {
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
    restartCamera,
    setIsCameraActive,
  } = useScanCamera({
    onCodeScanned: handleScannedCode,
  });

  useEffect(() => {
    if (!exec.lastScannedLineId) return;

    const targetLine = exec.nextIncompleteLine ?? exec.scanTargetLine;
    if (!targetLine) return;

    const targetInput = globalThis.document?.getElementById(
      `done-quantity-${targetLine.id}`,
    ) as HTMLInputElement | null;
    if (!targetInput) return;

    targetInput.focus();
    targetInput.select?.();
    targetInput.scrollIntoView?.({ block: "center", behavior: "smooth" });
  }, [exec.lastScannedLineId, exec.nextIncompleteLine, exec.scanTargetLine]);

  const handleCameraToggle = () => {
    exec.handleCameraToggle(restartCamera, setIsCameraActive);
  };

  // An empty field opens the camera instead of doing nothing, the rule the
  // picking and receiving sessions' Scan follows; an open camera showing a
  // refusal is retried, as the press is what follows allowing it.
  const applyTypedScan = () => {
    if (exec.scanValue.trim()) handleScannedCode(exec.scanValue);
    else if (!exec.cameraOpen) handleCameraToggle();
    else if (scannerError) restartCamera();
  };

  return (
    <Card
      ref={cardRef}
      className="p-4 sm:p-6 space-y-4 border-primary-200 bg-primary-50/20"
    >
      <div className="space-y-1">
        <h2 className="text-base font-semibold text-on">
          {t("detail.executionTitle")}
        </h2>
        <p className="text-sm text-on-secondary">{t("detail.executionHelp")}</p>
      </div>

      <ScanModeSection
        scanMode={exec.scanMode}
        cameraOpen={exec.cameraOpen}
        scanValue={exec.scanValue}
        scanFeedback={exec.scanFeedback}
        scanFeedbackTone={exec.scanFeedbackTone}
        lineStatusCounts={exec.lineStatusCounts}
        scanTargetLine={exec.scanTargetLine}
        nextIncompleteLine={exec.nextIncompleteLine}
        scannerError={scannerError}
        isCameraActive={isCameraActive}
        isTorchOn={isTorchOn}
        onToggleScanMode={exec.handleScanModeToggle}
        onCameraToggle={handleCameraToggle}
        onScanValueChange={exec.setScanValue}
        onApplyScan={applyTypedScan}
        onToggleTorch={toggleTorch}
        onRetryCamera={restartCamera}
        t={t}
      />

      <div className="space-y-3">
        {document.lines.map((line) => {
          const currentDoneQty = Number(
            exec.values[line.id] ?? line.expected_quantity ?? line.quantity,
          );
          const expectedQty = Number(line.expected_quantity ?? line.quantity);

          return (
            <ExecutionLineCard
              key={line.id}
              line={line}
              documentStatus={document.status}
              currentDoneQuantity={currentDoneQty}
              isReceipt={isReceipt}
              requiresDiscrepancy={currentDoneQty < expectedQty}
              isActiveScanLine={exec.activeScanLineId === line.id}
              lastScannedLineId={exec.scannedLineId}
              isReasonEditorOpen={
                exec.reasonEditorOpen[line.id] ||
                Boolean(exec.reasons[line.id]?.trim())
              }
              executionLineStatus={getDocumentLineStatus(
                {
                  ...line,
                  done_quantity: currentDoneQty,
                  discrepancy_code:
                    (exec.codes[line.id] || line.discrepancy_code) ?? null,
                },
                document.status,
              )}
              values={exec.values}
              heldValues={exec.heldValues}
              codes={exec.codes}
              codeError={exec.codeErrors[line.id]}
              reasons={exec.reasons}
              onUpdateDoneQuantity={exec.updateLineDoneQuantity}
              onHeldChange={exec.setHeldForLine}
              onCodeChange={exec.setCodeForLine}
              onReasonToggle={exec.toggleReasonEditor}
              onReasonChange={exec.setReasonForLine}
              t={t}
            />
          );
        })}
      </div>

      {ships && (
        <ShipmentFields
          value={shipment}
          onChange={setShipment}
          error={shipmentFault}
        />
      )}

      {exec.error && (
        <p className="text-sm font-medium text-red-600">{exec.error}</p>
      )}

      <ExecutionActions
        isPending={isPending}
        onCancel={onCancel}
        onSubmit={exec.handleSubmit}
        cancelText={t("common:form.cancel")}
        submitText={t("detail.executionSubmit")}
        floating={!exec.cameraOpen}
      />
    </Card>
  );
}
