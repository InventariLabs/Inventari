import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import { DocumentLinesEditor } from "@/modules/warehouse/components/DocumentLinesEditor";
import { lineFieldErrors } from "@/modules/warehouse/components/documentFormShared";
import { lineExtraFor } from "@/modules/warehouse/components/WorkspaceFormSlots";
import { PhoneLineByLine } from "@/modules/warehouse/components/actions/PhoneLineByLine";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { useDocumentScanner } from "@/modules/warehouse/hooks/useDocumentScanner";
import { useQuickAddLine } from "@/modules/warehouse/hooks/useQuickAddLine";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import type { ActionDraft } from "@/modules/warehouse/hooks/useActionDraft";

interface ActionLinesProps {
  draft: ActionDraft;
  /** A phone enters the goods one by one, with big buttons. */
  phone: boolean;
  /** A picked record starts at all it holds (a move) rather than at one. */
  wholeRecord?: boolean;
  /** A location label scanned where a product was expected. */
  onLocationScanned?: (locationId: string, name: string) => void;
  /**
   * Set on the screens that open their lines to other modules' fields (Issue);
   * a move leaves it out and its lines stay as they are.
   */
  extendedAs?: "issue";
}

/** Other modules' fields under each line of the issue screen. */
function lineExtras(draft: ActionDraft) {
  return lineExtraFor(
    "issue",
    draft.workspace,
    draft.extensions.registerBeforeSubmit,
  );
}

/**
 * The desktop's lines: the document form's line editor — scan or search, the
 * quantity typed on the row. Prices stay out of the way behind one button
 * unless the profile requires them; a move never carries any.
 */
function DesktopLines({
  draft,
  onLocationScanned,
  extendedAs,
}: Pick<ActionLinesProps, "draft" | "onLocationScanned" | "extendedAs">) {
  const { t } = useTranslation("warehouse");
  const { workspace, errors } = draft;
  const stockLocationId = workspace.sourceLocationId || null;
  const { data: profile } = useDocumentProfile();
  const valueTracked = useShowDocumentValue(workspace.docType);
  const pricesRequired = valueTracked && !!profile?.require_unit_price;
  const [pricesOpen, setPricesOpen] = useState(false);
  const showPrices = pricesRequired || (valueTracked && pricesOpen);
  const currency = useDocumentCurrency(profile?.default_currency);
  const quickAdd = useQuickAddLine(workspace.appendLine);
  const scanner = useDocumentScanner({
    onAddOrIncrementLine: workspace.addOrIncrementLine,
    onOpenQuickAdd: quickAdd.openQuickAdd,
    stock: { locationId: stockLocationId },
    onLocationScanned,
  });

  return (
    <div className="space-y-3">
      {valueTracked && !pricesRequired && (
        <div className="flex justify-end">
          <Button
            variant="ghost"
            size="sm"
            aria-pressed={pricesOpen}
            onClick={() => setPricesOpen((open) => !open)}
          >
            {pricesOpen ? t("action.hidePrices") : t("action.addPrices")}
          </Button>
        </div>
      )}
      <DocumentLinesEditor
        lines={workspace.lines}
        {...quickAdd.editorProps}
        scanOpen={scanner.scanOpen}
        scanLoading={scanner.scanLoading}
        scannerError={scanner.scannerError}
        isCameraActive={scanner.isCameraActive}
        isTorchOn={scanner.isTorchOn}
        showValueFields={showPrices}
        showTaxField={
          showPrices && (profile?.tax_handling ?? "NONE") !== "NONE"
        }
        currency={currency}
        partnerId={workspace.partnerId}
        stockLocationId={stockLocationId}
        needsStockRow={workspace.requiresItemId}
        mergeStockRows={workspace.splitsAcrossRecords}
        lineErrors={lineFieldErrors(errors, workspace.lines, t)}
        onAddEmptyLine={workspace.addEmptyLine}
        onScanToggle={() => {
          const next = !scanner.scanOpen;
          scanner.setScanOpen(next);
          if (next) scanner.restartCamera();
        }}
        onToggleTorch={scanner.toggleTorch}
        onManualCode={scanner.handleCodeScanned}
        onRemoveLine={workspace.removeLine}
        onUpdateLine={workspace.updateLine}
        renderLineExtra={extendedAs ? lineExtras(draft) : undefined}
      />
    </div>
  );
}

/**
 * What the action takes, from the place it takes it from: the desktop's line
 * editor, or one product at a time on a phone. Either way the lines name the
 * stock records standing in the source — or anywhere, while no source is
 * chosen for a write-off, whose record says where it is.
 */
export function ActionLines({
  draft,
  phone,
  wholeRecord = false,
  onLocationScanned,
  extendedAs,
}: ActionLinesProps) {
  const { t } = useTranslation("warehouse");
  const { workspace } = draft;
  if (!phone)
    return (
      <DesktopLines
        draft={draft}
        onLocationScanned={onLocationScanned}
        extendedAs={extendedAs}
      />
    );
  return (
    <PhoneLineByLine
      lines={draft.entered}
      stockLocationId={workspace.sourceLocationId || null}
      merge={workspace.splitsAcrossRecords}
      wholeRecord={wholeRecord}
      lineErrors={lineFieldErrors(draft.errors, workspace.lines, t)}
      onLocationScanned={onLocationScanned}
      renderLineExtra={extendedAs ? lineExtras(draft) : undefined}
      onAdd={workspace.addOrIncrementLine}
      onRemove={(key) =>
        workspace.removeLine(
          workspace.lines.findIndex((line) => line._key === key),
        )
      }
    />
  );
}
