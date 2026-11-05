import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
} from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { TriangleAlert } from "lucide-react";
import axios from "axios";
import { Button } from "@/components/ui/Button";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { Sheet } from "@/components/ui/Sheet";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { extractApiError } from "@/lib/errors";
import { parseApiValidationErrors } from "@/lib/validationErrors";
import { useDocumentPlaces } from "@/modules/warehouse/hooks/useDocumentPlaces";
import {
  DocumentFormFields,
  FIELD_IDS,
} from "@/modules/warehouse/components/DocumentFormFields";
import { DocumentFormHeader } from "@/modules/warehouse/components/DocumentFormHeader";
import { DocumentImportModal } from "@/modules/warehouse/components/DocumentImportModal";
import { DocumentLinesEditor } from "@/modules/warehouse/components/DocumentLinesEditor";
import {
  WorkspaceFormExtra,
  lineExtraFor,
} from "@/modules/warehouse/components/WorkspaceFormSlots";
import { documentTypeName } from "@/modules/warehouse/lib/documentTypeName";
import { useDocumentScanner } from "@/modules/warehouse/hooks/useDocumentScanner";
import { useDraftExtensions } from "@/modules/warehouse/hooks/useDraftExtensions";
import {
  useCreateDocument,
  useUpdateDocument,
} from "@/modules/warehouse/hooks/useDocuments";
import { useDocumentWorkspaceState } from "@/modules/warehouse/hooks/useDocumentWorkspaceState";
import type {
  DocumentInitialLine,
  DocumentWorkspace,
} from "@/modules/warehouse/hooks/useDocumentWorkspaceState";
import { useDocumentLineImport } from "@/modules/warehouse/hooks/useDocumentLineImport";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { useDocumentCurrency } from "@/hooks/useDocumentCurrency";
import {
  readLastUsedLocations,
  rememberLastUsedLocations,
} from "@/modules/warehouse/lib/lastUsedLocations";
import {
  PartnerInlineCreate,
  usePartnerCreateLayer,
} from "@/modules/partners/moduleApi";
import { useDocumentPartnerOptions } from "@/modules/warehouse/hooks/useDocumentPartnerOptions";
import { useModules } from "@/contexts/ModulesContext";
import { useShowDocumentValue } from "@/modules/warehouse/hooks/useShowDocumentValue";
import { useQuickAddLine } from "@/modules/warehouse/hooks/useQuickAddLine";
import { lineFieldErrors } from "@/modules/warehouse/components/documentFormShared";
import type {
  DocumentType,
  WarehouseDocument,
} from "@/modules/warehouse/types";
import type { TFunction } from "i18next";

interface Props {
  document?: WarehouseDocument;
  initialType?: string;
  /** The shelf a new document starts on, when the form was opened from one. */
  initialSourceLocationId?: string;
  /** Goods a new document starts with, when the form was opened from them. */
  initialLines?: DocumentInitialLine[];
  onClose: () => void;
  /**
   * Called with the created document instead of plain onClose. The next step
   * after creating one is almost always to confirm it or add lines, and the
   * list gave no way through — the user had to find the new row themselves.
   */
  onCreated?: (created: WarehouseDocument) => void;
}

/** Opens the source location list, for a search that found nothing there. */
function openSourceField() {
  document.getElementById(FIELD_IDS.source)?.click();
}

/** The patch that records whether picking a product suggested a price. */
function withPriceHint(lineKey: string, suggested: boolean) {
  return (previous: Record<string, boolean>) => ({
    ...previous,
    [lineKey]: suggested,
  });
}

/** Move focus to the first field the validator rejected. */
function focusFirstInvalidField(errors: Record<string, string>) {
  const byId = [
    ["partner_id", FIELD_IDS.partner],
    ["source_location_id", FIELD_IDS.source],
    ["target_location_id", FIELD_IDS.target],
  ] as const;

  for (const [key, id] of byId) {
    if (errors[key]) {
      document.getElementById(id)?.focus();
      return;
    }
  }

  // Line-level errors render inside the editor; the field carries
  // aria-invalid, which is enough to find it without knowing the markup.
  requestAnimationFrame(() => {
    const firstInvalid = document.querySelector<HTMLElement>(
      '[aria-invalid="true"]',
    );
    firstInvalid?.focus();
  });
}

/** What a line says, so a line the caller handed in can be told from one the
 * user wrote or changed. */
function lineSignature(line: {
  item_id?: string | null;
  product_template_id?: string | null;
  quantity: string | number;
}): string {
  return `${line.item_id ?? ""}|${line.product_template_id ?? ""}|${Number(line.quantity)}`;
}

/** The signatures of the lines the form was opened with. */
function initialLineSignatures(
  initialLines: DocumentInitialLine[] | undefined,
): Set<string> {
  return new Set((initialLines ?? []).map(lineSignature));
}

/** Whether any line on screen is the user's work rather than a handed-in one. */
function hasUserFilledLine(
  lines: Array<{
    item_id?: string | null;
    product_template_id?: string | null;
    name: string;
    barcode?: string;
    quantity: string | number;
  }>,
  prefilled: ReadonlySet<string>,
): boolean {
  return lines.some((line) => {
    const filled =
      !!line.item_id || !!line.name.trim() || !!line.barcode?.trim();
    return filled && !prefilled.has(lineSignature(line));
  });
}

/** A location the user picked, as opposed to none or the one handed in. */
function changedFrom(picked: string, prefilled?: string): boolean {
  return !!picked && picked !== prefilled;
}

/** The locations a form was opened with, so they are not mistaken for work. */
function openedAt(source?: string): { source?: string; target?: string } {
  return source ? { source } : {};
}

/**
 * What the submit button of a form says. One label per document
 * type, exhaustive over the union — the old ladder covered the four flow
 * families and let everything else fall through to "Create Receipt", so the
 * scrap and correction forms asked the operator to "create a receipt" while
 * doing the opposite.
 */
function submitLabelFor(
  t: TFunction,
  docType: DocumentType,
  typeLabels: Record<string, string> | null | undefined,
  isEdit: boolean,
): string {
  if (isEdit) return t("common:form.save");
  // The organization's own label for the type, the one the register and the
  // document number already use, joins the stock name instead of replacing it.
  const customName = typeLabels?.[docType];
  if (customName) {
    return t("picker.createNamed", {
      type: documentTypeName(t, docType, customName),
    });
  }
  const labels: Record<DocumentType, string> = {
    IN: t("picker.createReceipt"),
    OUT: t("picker.createDispatch"),
    INT: t("picker.createTransfer"),
    INTERNAL_IN: t("picker.createInternalReceipt"),
    INTERNAL_OUT: t("picker.createInternalIssue"),
    CORRECTION: t("picker.createCorrection"),
    // A stock-count adjustment is a correction of the shelf, not a new kind.
    ADJUSTMENT: t("picker.createCorrection"),
    SCRAP: t("picker.createScrap"),
  };
  return labels[docType];
}

/** Whether a line still waits for a price. */
function isUnpriced(line: { unit_price?: string | null }): boolean {
  return line.unit_price == null || line.unit_price === "";
}

/**
 * The value-completeness signal — a document whose lines carry no price has
 * no accounting value. Says nothing while every line is priced. It speaks of
 * the document only: what the price sources answered differs from line to
 * line, so that answer stands under the line it is about.
 */
function MissingValueWarning({
  lines,
}: {
  lines: Array<{ unit_price?: string }>;
}) {
  const { t } = useTranslation("warehouse");
  if (!lines.some(isUnpriced)) return null;
  return (
    <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-800 dark:border-amber-900 dark:bg-amber-950/40 dark:text-amber-300">
      <TriangleAlert size={14} className="mt-0.5 shrink-0" />
      <span>{t("form.missingValueWarning")}</span>
    </div>
  );
}

/** Under a line that went looking for a price and came back without one. */
function LineNoPriceSource() {
  const { t } = useTranslation("warehouse");
  return (
    <p className="text-xs text-amber-800 dark:text-amber-300">
      {t("form.lineNoPriceSource")}
    </p>
  );
}

/** What the prefill reads besides the form it fills. */
interface DocumentLocationPrefillInput {
  locationsLoaded: boolean;
  /** The places the form remembers that are still on offer. */
  offeredIds: ReadonlySet<string>;
  /** The one place there is, when there is exactly one on offer. */
  onlyLocationId: string | null;
  prefilledLocations: MutableRefObject<{ source?: string; target?: string }>;
}

/**
 * Where a new document's source and target start: the locations this
 * document type was last given, when they still exist — and, when the
 * organization has one location left and the type names exactly one of its
 * ends, that location, put in the field rather than asked for. A transfer
 * names both ends, and with a single location there is nowhere to transfer
 * to — it gets no default, since its two fields cannot hold the same place.
 *
 * Only empty fields are filled, and both kinds of fill are marked in
 * `prefilledLocations` like the ones the reader hands in: the discard guard
 * must not read a default for the reader's work as unsaved input.
 */
function useDocumentLocationPrefill(
  {
    isEdit,
    docType,
    sourceLocationId,
    targetLocationId,
    requiresSource,
    requiresTarget,
    setSourceLocationId,
    setTargetLocationId,
  }: DocumentWorkspace,
  {
    locationsLoaded,
    offeredIds,
    onlyLocationId,
    prefilledLocations,
  }: DocumentLocationPrefillInput,
): void {
  useEffect(() => {
    if (isEdit || !locationsLoaded) return;
    const remembered = readLastUsedLocations()[docType];
    if (
      remembered?.source &&
      !sourceLocationId &&
      offeredIds.has(remembered.source)
    ) {
      setSourceLocationId(remembered.source);
      prefilledLocations.current.source = remembered.source;
    }
    if (
      remembered?.target &&
      !targetLocationId &&
      offeredIds.has(remembered.target)
    ) {
      setTargetLocationId(remembered.target);
      prefilledLocations.current.target = remembered.target;
    }
    if (!onlyLocationId) return;
    if (requiresSource && !requiresTarget && !sourceLocationId) {
      setSourceLocationId(onlyLocationId);
      prefilledLocations.current.source = onlyLocationId;
    }
    if (requiresTarget && !requiresSource && !targetLocationId) {
      setTargetLocationId(onlyLocationId);
      prefilledLocations.current.target = onlyLocationId;
    }
  }, [
    isEdit,
    locationsLoaded,
    docType,
    offeredIds,
    onlyLocationId,
    sourceLocationId,
    targetLocationId,
    requiresSource,
    requiresTarget,
    setSourceLocationId,
    setTargetLocationId,
    prefilledLocations,
  ]);
}

export default function DocumentFormModal({
  document,
  initialType,
  initialSourceLocationId,
  initialLines,
  onClose,
  onCreated,
}: Props) {
  // Move all hooks to top level to satisfy rules-of-hooks
  const { t } = useTranslation(["warehouse", "common"]);
  // when the Partners module is disabled, the partner query is gated
  // (empty list) and inline-create can't surface the new partner. Treat the
  // partner as optional in that case and show a notice instead of a dead
  // picker.
  const { isModuleEnabled } = useModules();
  const partnersEnabled = isModuleEnabled("partners");

  const { data: profile } = useDocumentProfile();
  // The server stamps this rate on every line that arrives without one
  // (`_apply_simple_rate_tax`), so the form says so before a total is approved.
  const defaultTaxRate =
    profile?.tax_handling === "SIMPLE_RATE" && profile.default_tax_rate != null
      ? String(profile.default_tax_rate)
      : undefined;
  // Same chain the server walks in `resolve_document_currency`: the
  // document's own currency, then the profile's explicit override, then the
  // organization. The profile alone starts empty on every new organization,
  // which is how every amount here came out as "51.40 ?".
  const linesCurrency = useDocumentCurrency(
    document?.currency ?? profile?.default_currency,
  );

  const workspace = useDocumentWorkspaceState({
    document,
    initialType,
    initialSourceLocationId,
    initialLines,
    partnersEnabled,
  });
  const {
    isEdit,
    docType,
    partnerId,
    sourceLocationId,
    targetLocationId,
    scheduledDate,
    notes,
    externalReference,
    lines,
    requiresSource,
    requiresTarget,
    requiresPartner,
    hasLines,
    setPartnerId,
    setSourceLocationId,
    setTargetLocationId,
    setScheduledDate,
    setNotes,
    setExternalReference,
    appendLine,
    addOrIncrementLine,
    replaceLinesFrom,
    appendImportedLines,
    addEmptyLine,
    removeLine,
    updateLine,
    consolidateLines,
    toCreatePayload,
    toUpdatePayload,
    validateForm,
    requiresItemId,
    splitsAcrossRecords,
    linesNameAProduct,
    replaceLine,
  } = workspace;
  // What other modules' fields on the form save before it is sent.
  const extensions = useDraftExtensions();
  // Price, VAT, totals and the empty-price warning belong to the documents
  // that carry a value — receipts and issues, internal ones included — and
  // only while the profile tracks value. A transfer, a correction or a
  // scrap is offered no price field, so nothing here asks the writer for
  // one either.
  const showValueFields = useShowDocumentValue(docType);
  const showTaxField =
    showValueFields && (profile?.tax_handling ?? "NONE") !== "NONE";
  // After the workspace: the picker reads the partner it holds, to name it
  // and to say whether the role set still allows it.
  const picker = useDocumentPartnerOptions(
    { type: docType, return_of_id: document?.return_of_id },
    partnerId,
  );
  // The picker folds shelf-total rows only where the executor can spend
  // them — one executor truth, mirrored from document_types.py.
  const lineImport = useDocumentLineImport({
    documentId: document?.id,
    docType,
    sourceLocationId,
    requiresSource,
    replaceLinesFrom,
    appendImportedLines,
  });
  const [hasAttemptedSubmit, setHasAttemptedSubmit] = useState(false);
  // Server (422) errors, set by handleApiError; cleared on input change.
  const [serverErrors, setServerErrors] = useState<Record<string, string>>({});
  // Per line: did the price sources answer the pick? A miss on the first line
  // says nothing about the second, so the answer stands under its own line.
  const [priceHintByLine, setPriceHintByLine] = useState<
    Record<string, boolean>
  >({});
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);
  // fills the locations from the last used ones. Those are not the
  // user's work, so the discard guard must not count them as unsaved input.
  const prefilledLocations = useRef(openedAt(initialSourceLocationId));

  const createMutation = useCreateDocument();
  const updateMutation = useUpdateDocument();
  const isLoading = createMutation.isPending || updateMutation.isPending;

  // Live validation is derived in render (see `errors` below): once the
  // user has attempted submit, client errors add and clear as fields are
  // fixed. Server errors clear on the next input change.
  useEffect(() => {
    setServerErrors({});
  }, [lines, partnerId, sourceLocationId, targetLocationId, docType]);

  const quickAdd = useQuickAddLine(appendLine, {
    namesAProduct: linesNameAProduct,
    lines,
    replaceLine,
  });

  const {
    open: partnerCreateOpen,
    query: partnerCreateQuery,
    handleCreate: handlePartnerCreate,
    handleCreated: handlePartnerCreated,
    handleCancel: handlePartnerCreateCancel,
  } = usePartnerCreateLayer({
    roleTypes: picker.partnerTypes,
    onAccepted: setPartnerId,
  });

  const hasUnsavedInput =
    hasUserFilledLine(lines, initialLineSignatures(initialLines)) ||
    !!partnerId ||
    changedFrom(sourceLocationId, prefilledLocations.current.source) ||
    changedFrom(targetLocationId, prefilledLocations.current.target) ||
    !!notes.trim() ||
    !!externalReference.trim();

  // when the inline partner-create popover is open, Esc/backdrop must
  // close the popover first — not discard the whole document form.
  //
  // And Escape on a filled-in form used to throw away the partner, the
  // locations and every line without a word, with no way back.
  const handleSheetClose = useCallback(() => {
    if (partnerCreateOpen) {
      handlePartnerCreateCancel();
      return;
    }
    if (hasUnsavedInput) {
      setDiscardConfirmOpen(true);
      return;
    }
    onClose();
  }, [partnerCreateOpen, handlePartnerCreateCancel, hasUnsavedInput, onClose]);

  // Map a backend line index to the current line's stable _key, so 422
  // errors stay attached to the right row after reorder/remove.
  const indexToKey = useCallback((i: number) => lines[i]?._key, [lines]);

  const handleApiError = useCallback(
    (err: Error) => {
      const detail = axios.isAxiosError(err)
        ? err.response?.data?.detail
        : undefined;
      const apiErrors = parseApiValidationErrors(detail, indexToKey);
      const fallback =
        isEdit && document
          ? t("errors.updateFailed")
          : t("errors.createFailed");
      if (Object.keys(apiErrors).length > 0) {
        setHasAttemptedSubmit(true);
        setServerErrors(apiErrors);
        toast.error(extractApiError(err, fallback));
        return;
      }
      toast.error(extractApiError(err, fallback));
    },
    [indexToKey, t, isEdit, document],
  );

  // Set only where lines name a stock record; null while no source is chosen.
  const stockLocationId = requiresItemId ? sourceLocationId || null : undefined;

  const {
    handleCodeScanned,
    scanOpen,
    setScanOpen,
    scanLoading,
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
    restartCamera,
  } = useDocumentScanner({
    onAddOrIncrementLine: addOrIncrementLine,
    onOpenQuickAdd: quickAdd.openQuickAdd,
    stock: { locationId: stockLocationId },
  });

  const renderModuleLineExtra = lineExtraFor(
    "document",
    workspace,
    extensions.registerBeforeSubmit,
  );

  const save = () => {
    if (isEdit && document) {
      updateMutation.mutate(
        { id: document.id, data: toUpdatePayload() },
        {
          onSuccess: () => {
            toast.success(t("toast.updated"));
            onClose();
          },
          onError: handleApiError,
        },
      );
      return;
    }

    createMutation.mutate(toCreatePayload(), {
      onSuccess: (created) => {
        rememberLastUsedLocations(docType, sourceLocationId, targetLocationId);
        toast.success(t("toast.created"));
        if (onCreated && created) {
          onCreated(created);
          return;
        }
        onClose();
      },
      onError: handleApiError,
    });
  };

  const handleSubmit = (event: React.FormEvent) => {
    event.preventDefault();

    if (!hasLines) {
      toast.error(t("lines.noLines"));
      return;
    }

    setHasAttemptedSubmit(true);
    const validationErrors = validateForm(picker.selectedPartnerOffered);

    if (Object.keys(validationErrors).length > 0) {
      const firstKey = Object.values(validationErrors)[0];
      toast.error(t(firstKey));
      // Focus follows the first problem. Leaving it on the submit button
      // means a keyboard or screen-reader user gets no route to the field
      // that stopped the save.
      focusFirstInvalidField(validationErrors);
      return;
    }

    // A module's own fields save first; one that refuses stops the save.
    if (!extensions.hasCallbacks()) return save();
    void extensions.runBeforeSubmit().then(save, handleApiError);
  };

  // Derived validation: client errors recompute in render once submit was
  // attempted; server errors persist until the next input change.
  const errors: Record<string, string> = {
    ...serverErrors,
    ...(hasAttemptedSubmit ? validateForm(picker.selectedPartnerOffered) : {}),
  };

  // The pickers offer a stock flow's set — what may hold stock, never a
  // place a module owns: a receipt into a server rack is the module's
  // transaction, not this form's, whatever the general lists mix. They search
  // the places on the server as the reader types, and an edited document's
  // own places are named by id, so opening one never silently clears where it
  // moves from or to.
  // What the form needs to know of the places before the reader opens a
  // picker: asked by id and by count, never found in a list of every location.
  const places = useDocumentPlaces({ isEdit, docType, stockLocationId });

  // prefill source/target with the last used locations for this
  // document type (new documents only) — and, where there is exactly one
  // eligible location, with that; only empty fields are filled.
  useDocumentLocationPrefill(workspace, {
    locationsLoaded: places.locationsLoaded,
    offeredIds: places.offeredIds,
    onlyLocationId: places.onlyLocationId,
    prefilledLocations,
  });

  const lineErrors = lineFieldErrors(errors, lines, t);

  const submitLabel = submitLabelFor(t, docType, profile?.type_labels, isEdit);

  return (
    <>
      <Sheet
        open
        onClose={handleSheetClose}
        maxWidth="6xl"
        aria-label={isEdit ? t("form.editTitle") : t("form.createTitle")}
        className="sm:max-w-4xl xl:max-w-6xl 3xl:max-w-7xl"
      >
        {/* `Sheet` already draws the panel — surface, radius, shadow and the
            90vh cap. Repeating the cap here made the inner panel ask for the
            full 90vh inside a parent whose border had already spent 2px of it,
            so the form scrolled on content that fits. */}
        <div
          data-testid="document-form-modal-shell"
          className="flex min-h-0 w-full flex-1 flex-col"
        >
          <DocumentFormHeader
            isEdit={isEdit}
            docType={docType}
            onClose={handleSheetClose}
          />

          <form
            onSubmit={handleSubmit}
            className="flex-1 space-y-5 overflow-y-auto bg-surface-card p-4 sm:p-5"
          >
            <section className="rounded-2xl border border-border bg-surface-raised/40 p-4 sm:p-5">
              <div className="mb-4 space-y-1">
                <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                  {t("form.documentSectionEyebrow")}
                </p>
                <p className="text-sm text-on-secondary">
                  {t("form.documentSectionHint")}
                </p>
              </div>

              <DocumentFormFields
                docType={docType}
                partnerId={partnerId}
                sourceLocationId={sourceLocationId}
                targetLocationId={targetLocationId}
                scheduledDate={scheduledDate}
                externalReference={externalReference}
                notes={notes}
                scrapReason={workspace.scrapReason}
                requiresPartner={requiresPartner}
                requiresSource={requiresSource}
                requiresTarget={requiresTarget}
                {...picker.fieldProps}
                partnersModuleDisabled={!partnersEnabled}
                locationsEmptyReason={places.emptyReason}
                errors={errors}
                onPartnerIdChange={setPartnerId}
                onSourceLocationIdChange={setSourceLocationId}
                onTargetLocationIdChange={setTargetLocationId}
                onScheduledDateChange={setScheduledDate}
                onExternalReferenceChange={setExternalReference}
                onNotesChange={setNotes}
                onPartnerCreate={
                  partnersEnabled ? handlePartnerCreate : undefined
                }
              />

              {partnerCreateOpen && partnersEnabled && (
                <div className="mt-3">
                  <PartnerInlineCreate
                    initialName={partnerCreateQuery}
                    roleTypes={picker.partnerTypes}
                    onCreated={handlePartnerCreated}
                    onCancel={handlePartnerCreateCancel}
                  />
                </div>
              )}

              <WorkspaceFormExtra
                action="document"
                workspace={workspace}
                registerBeforeSubmit={extensions.registerBeforeSubmit}
                partnerId={partnerId || null}
                lines={lines}
              />
            </section>

            <section className="rounded-2xl border border-border bg-surface-card shadow-sm shadow-primary-100/20 overflow-visible">
              <div className="border-b border-border px-4 py-3 sm:px-5 sm:py-4">
                <p className="text-[10px] font-medium uppercase tracking-widest text-on-muted">
                  {t("form.linesSectionEyebrow")}
                </p>
                <p className="mt-1 text-sm text-on-secondary">
                  {t("form.linesSectionHint")}
                </p>
              </div>

              <div className="p-4 sm:p-5">
                <div className="mb-3 flex justify-end">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={lineImport.openImport}
                  >
                    {t("import.title")}
                  </Button>
                </div>
                <DocumentLinesEditor
                  lines={lines}
                  {...quickAdd.editorProps}
                  scanOpen={scanOpen}
                  scanLoading={scanLoading}
                  scannerError={scannerError}
                  isCameraActive={isCameraActive}
                  isTorchOn={isTorchOn}
                  showValueFields={showValueFields}
                  showTaxField={showTaxField}
                  defaultTaxRate={defaultTaxRate}
                  currency={linesCurrency}
                  partnerId={partnerId}
                  stockLocationId={stockLocationId}
                  stockLocationName={places.stockPlaceName}
                  onChangeSource={openSourceField}
                  needsStockRow={requiresItemId}
                  mergeStockRows={splitsAcrossRecords}
                  lineErrors={lineErrors}
                  onAddEmptyLine={addEmptyLine}
                  onConsolidate={consolidateLines}
                  onScanToggle={() => {
                    const next = !scanOpen;
                    setScanOpen(next);
                    if (next) {
                      restartCamera();
                    }
                  }}
                  onToggleTorch={toggleTorch}
                  onManualCode={handleCodeScanned}
                  onRemoveLine={removeLine}
                  onUpdateLine={updateLine}
                  renderLineExtra={(line) => (
                    <>
                      {showValueFields &&
                        isUnpriced(line) &&
                        priceHintByLine[line._key] === false && (
                          <LineNoPriceSource />
                        )}
                      {renderModuleLineExtra(line)}
                    </>
                  )}
                  onPriceHintResult={(lineKey, suggested) =>
                    setPriceHintByLine(withPriceHint(lineKey, suggested))
                  }
                />
                {showValueFields && <MissingValueWarning lines={lines} />}
              </div>
            </section>
          </form>

          <FormSheetFooter
            isPending={isLoading}
            lineCount={lines.length}
            lineCountText={t("picker.lineCount", { count: lines.length })}
            cancelText={t("common:form.cancel")}
            submitText={submitLabel}
            onCancel={handleSheetClose}
            onSubmit={handleSubmit}
          />
        </div>
      </Sheet>

      {lineImport.importOpen && (
        <DocumentImportModal {...lineImport.modalProps} />
      )}

      <ConfirmDialog
        open={discardConfirmOpen}
        title={t("form.discardTitle")}
        message={t("form.discardMessage")}
        variant="danger"
        confirmLabel={t("form.discardConfirm")}
        cancelLabel={t("form.discardCancel")}
        onConfirm={() => {
          setDiscardConfirmOpen(false);
          onClose();
        }}
        onCancel={() => setDiscardConfirmOpen(false)}
      />
    </>
  );
}
