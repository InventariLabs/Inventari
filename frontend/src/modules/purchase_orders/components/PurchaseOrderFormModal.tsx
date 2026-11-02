import { useCallback, useEffect, useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { DiscardDraftDialog } from "@/components/ui/DiscardDraftDialog";
import { FormSheetFooter } from "@/components/ui/FormSheetFooter";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet } from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import { todayIso } from "@/utils/formatters";
import { CURRENCY_CODES, currencyLabel } from "@/lib/currencies";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useDiscardGuard } from "@/hooks/useDiscardGuard";
import { usePartnerPicker } from "@/hooks/usePartnerPicker";
import { InlineQueryError } from "@/components/ui/QueryResult";
import type { Partner, PartnerType } from "@/types";
import { SUPPLIER_ROLE_TYPES } from "@/module-sdk";
import { PartnerInlineCreate } from "@/modules/partners/moduleApi";
import {
  useCreatePurchaseOrder,
  useUpdatePurchaseOrder,
} from "../hooks/usePurchaseOrders";
import { usePoLineScanner } from "../hooks/usePoLineScanner";
import { POHeader } from "./POHeader";
import { PODocumentInfoSection } from "./PODocumentInfoSection";
import { POLinesSection, type POLineInput } from "./POLinesSection";
import { totalAmounts } from "@/utils/money";
import type {
  PurchaseOrder,
  PurchaseOrderCreate,
} from "@/modules/purchase_orders/types/purchase-orders";

interface Props {
  purchaseOrder?: PurchaseOrder;
  onClose: () => void;
  onSuccess: () => void;
}

function emptyLine(): POLineInput {
  return {
    id: `new-${Date.now()}`,
    product_template_id: null,
    name: "",
    sku: null,
    barcode: null,
    brand: null,
    image_url: null,
    quantity_ordered: 1,
    unit_price: "",
    tax_rate: "",
    uom_id: null,
  };
}

/** What a line holds once the reader has touched it — its id is bookkeeping. */
function lineContent({ id: _id, ...content }: POLineInput) {
  return JSON.stringify(content);
}

/** Line ids that still need a product name, keyed to their inline error. */
function collectEmptyNameErrors(
  lines: POLineInput[],
  message: string,
): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const l of lines) {
    if (!l.name.trim()) errors[l.id] = message;
  }
  return errors;
}

/**
 * The footer's totals. One pass, one rule — the backend's: three separate
 * reductions, each rounding its own unrounded running total, meant the printed
 * net plus the printed VAT did not add up to the printed gross.
 *
 * A line with no price yet leaves nothing to total, as on the saved order, so
 * the footer stays away rather than printing 0.00.
 */
function footerTotals(lines: POLineInput[]) {
  if (lines.some((l) => l.unit_price === "")) return {};
  const totals = totalAmounts(
    lines.map((l) => ({
      quantity: l.quantity_ordered,
      unit_price: l.unit_price,
      tax_rate: l.tax_rate,
    })),
  );
  return {
    subtotalAmount: totals.net.toFixed(2),
    totalTaxAmount: totals.tax.toFixed(2),
    totalAmount: totals.gross.toFixed(2),
  };
}

export default function PurchaseOrderFormModal({
  purchaseOrder,
  onClose,
  onSuccess,
}: Props) {
  const { t, i18n } = useTranslation(["purchase_orders", "common"]);
  const isEdit = Boolean(purchaseOrder);
  const titleId = useId();

  const [partnerId, setPartnerId] = useState(purchaseOrder?.partner_id ?? "");
  const [scheduledDate, setScheduledDate] = useState(
    purchaseOrder?.scheduled_date ?? "",
  );
  const [notes, setNotes] = useState(purchaseOrder?.notes ?? "");
  const orgCurrency = useOrganizationCurrency();
  // currency defaults to the organization currency and is always
  // sent, so no order can be created without one. The field is editable so an
  // order against a supplier billing in another currency records that currency
  // instead of silently writing the organization's own.
  const [currency, setCurrency] = useState<string | null>(
    purchaseOrder?.currency ?? orgCurrency ?? null,
  );

  // The organization query resolves after the form mounts; once it does, fill
  // the still-empty currency with the organization default without touching a
  // value the user already chose.
  useEffect(() => {
    setCurrency((current) => current ?? orgCurrency ?? null);
  }, [orgCurrency]);
  const [lines, setLines] = useState<POLineInput[]>(
    purchaseOrder?.lines.map((l) => ({
      id: l.id,
      product_template_id: l.product_template_id,
      name: l.name,
      sku: null,
      barcode: null,
      brand: null,
      image_url: null,
      quantity_ordered: Number(l.quantity_ordered),
      unit_price: l.unit_price ?? "",
      tax_rate: l.tax_rate ?? "",
      uom_id: l.uom_id,
    })) ?? [emptyLine()],
  );

  // A form opened on an existing order is dirty once it differs from that
  // order; a new one once anything is typed or picked. The organization
  // currency that fills in after mount is not the reader's work, so only a
  // currency they chose themselves counts.
  const [initialLines] = useState(() => lines.map(lineContent));
  const [initialFields] = useState({
    partnerId,
    scheduledDate,
    notes,
  });
  const [currencyChosen, setCurrencyChosen] = useState(false);
  const isDirty =
    partnerId !== initialFields.partnerId ||
    scheduledDate !== initialFields.scheduledDate ||
    notes !== initialFields.notes ||
    currencyChosen ||
    lines.length !== initialLines.length ||
    lines.some((l, i) => lineContent(l) !== initialLines[i]);

  const [nameErrors, setNameErrors] = useState<Record<string, string>>({});

  const [partnerCreateOpen, setPartnerCreateOpen] = useState(false);
  const [partnerCreateQuery, setPartnerCreateQuery] = useState("");

  const {
    handleCodeScanned,
    scanOpen,
    toggleScan,
    scanLoading,
    isCameraActive,
    scannerError,
    isTorchOn,
    toggleTorch,
  } = usePoLineScanner({ onAddOrIncrementLine: setLines });

  // a purchase order always comes from the supplier role set —
  // the same set the backend enforces on confirmation.
  const {
    options: partners,
    setSearch: setPartnerSearch,
    loading: partnersLoading,
    error: partnersError,
    retry: retryPartners,
  } = usePartnerPicker(SUPPLIER_ROLE_TYPES, partnerId);
  const createMutation = useCreatePurchaseOrder();
  const updateMutation = useUpdatePurchaseOrder();

  const addLine = () => setLines((prev) => [...prev, emptyLine()]);

  const removeLine = (id: string) =>
    setLines((prev) => prev.filter((l) => l.id !== id));

  const updateLineData = (id: string, data: Partial<POLineInput>) => {
    setLines((prev) => prev.map((l) => (l.id === id ? { ...l, ...data } : l)));
    if (data.name !== undefined) {
      setNameErrors((prev) => {
        if (!(data.name ?? "").trim() || !(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
  };

  // the "supplier is not on the list" problem also exists here, so
  // mount the same inline partner-create shortcut the documents form uses —
  // without discarding the lines already entered.
  const handlePartnerCreate = useCallback((query: string) => {
    setPartnerCreateQuery(query);
    setPartnerCreateOpen(true);
  }, []);

  const handlePartnerCreated = useCallback(
    (partner: Partner) => {
      // A role the order's supplier picker does not list would sit beneath
      // the placeholder looking empty while the form read it as filled.
      // The layer stays open; its type select is the recovery.
      if (!SUPPLIER_ROLE_TYPES.includes(partner.type as PartnerType)) return;
      setPartnerId(partner.id);
      setPartnerCreateOpen(false);
      setPartnerCreateQuery("");
    },
    [setPartnerId],
  );

  const handlePartnerCreateCancel = useCallback(() => {
    setPartnerCreateOpen(false);
    setPartnerCreateQuery("");
  }, []);

  // Escape while the shortcut is open must close the shortcut first, not the
  // whole order form with every line in it. And once the form holds work, every
  // exit — Escape, the close button, the backdrop, Cancel — asks first.
  const discard = useDiscardGuard(
    isDirty,
    onClose,
    t("purchase_orders:guardName"),
  );
  const requestClose = discard.requestClose;
  const handleSheetClose = useCallback(() => {
    if (partnerCreateOpen) {
      handlePartnerCreateCancel();
      return;
    }
    requestClose();
  }, [partnerCreateOpen, handlePartnerCreateCancel, requestClose]);

  const handleSave = async () => {
    if (lines.length === 0) {
      toast.error(t("atLeastOneLine"));
      return;
    }
    const hasEmptyName = lines.some((l) => !l.name.trim());
    if (hasEmptyName) {
      setNameErrors(collectEmptyNameErrors(lines, t("form.lineNameRequired")));
      toast.error(t("allLinesNeedProduct"));
      return;
    }
    if (scheduledDate && scheduledDate < todayIso()) {
      toast.error(t("form.scheduledDatePast"));
      return;
    }

    const payload: PurchaseOrderCreate = {
      partner_id: partnerId || undefined,
      scheduled_date: scheduledDate || undefined,
      // An emptied field sends null, not a missing key: clearing the
      // note has to reach the column.
      notes: notes.trim() ? notes.trim() : null,
      currency: currency ?? undefined,
      lines: lines.map((l) => ({
        product_template_id: l.product_template_id || undefined,
        name: l.name,
        quantity_ordered: l.quantity_ordered,
        unit_price: l.unit_price || undefined,
        uom_id: l.uom_id,
        tax_rate: l.tax_rate || undefined,
      })),
    };

    try {
      if (isEdit && purchaseOrder) {
        await updateMutation.mutateAsync({
          id: purchaseOrder.id,
          data: payload,
        });
        toast.success(t("updateSuccess"));
      } else {
        await createMutation.mutateAsync(payload);
        toast.success(t("createSuccess"));
      }
      onSuccess();
    } catch (err) {
      toast.error(extractApiError(err, t("unknownError")));
    }
  };

  const isPending = createMutation.isPending || updateMutation.isPending;

  return (
    <Sheet
      open
      onClose={handleSheetClose}
      maxWidth="6xl"
      aria-label={isEdit ? t("form.titleEdit") : t("form.titleCreate")}
      className="overflow-hidden"
    >
      <POHeader
        isEdit={isEdit}
        onClose={handleSheetClose}
        titleId={titleId}
        titleCreate={t("form.titleCreate")}
        titleEdit={t("form.titleEdit")}
        subtitleCreate={t("form.subtitleCreate")}
        subtitleEdit={t("form.subtitleEdit")}
      />

      <div className="flex-1 space-y-5 overflow-y-auto bg-surface-card p-4 sm:p-5">
        <PODocumentInfoSection
          partnerId={partnerId}
          partners={partners}
          onPartnerSearch={setPartnerSearch}
          partnersLoading={partnersLoading}
          scheduledDate={scheduledDate}
          notes={notes}
          onPartnerChange={setPartnerId}
          onScheduledDateChange={setScheduledDate}
          onNotesChange={setNotes}
          eyebrow={t("form.documentSectionEyebrow")}
          hint={t("form.documentSectionHint")}
          partnerLabel={t("form.partner")}
          partnerRequiredHint={t("form.partnerRequiredHint")}
          selectPartnerPlaceholder={t("form.selectPartner")}
          searchPartnerPlaceholder={t("form.searchPartner")}
          noPartnersFoundMessage={t("form.noPartnersFound")}
          scheduledDateLabel={t("form.scheduledDate")}
          scheduledDateMin={todayIso()}
          notesLabel={t("form.notes")}
          onPartnerCreate={handlePartnerCreate}
          createPartnerLabel={t("form.createNewPartner")}
        />
        {partnersError != null && (
          <InlineQueryError error={partnersError} onRetry={retryPartners} />
        )}

        {partnerCreateOpen && (
          <div className="mt-3">
            <PartnerInlineCreate
              initialName={partnerCreateQuery}
              roleTypes={SUPPLIER_ROLE_TYPES}
              onCreated={handlePartnerCreated}
              onCancel={handlePartnerCreateCancel}
            />
          </div>
        )}

        <NativeSelect
          label={t("form.currency")}
          value={currency ?? ""}
          onChange={(e) => {
            setCurrencyChosen(true);
            setCurrency(e.target.value || null);
          }}
          wrapperClassName="w-full sm:w-64"
        >
          <option value="">{t("form.currencyPlaceholder")}</option>
          {CURRENCY_CODES.map((code) => (
            <option key={code} value={code}>
              {code} — {currencyLabel(code, i18n.language)}
            </option>
          ))}
        </NativeSelect>

        <POLinesSection
          lines={lines}
          scanOpen={scanOpen}
          scanLoading={scanLoading}
          isCameraActive={isCameraActive}
          scannerError={scannerError}
          isTorchOn={isTorchOn}
          onToggleScan={toggleScan}
          onAddLine={addLine}
          onToggleTorch={toggleTorch}
          onManualCode={handleCodeScanned}
          onUpdateData={updateLineData}
          onRemove={removeLine}
          t={t}
          currency={currency}
          nameErrors={nameErrors}
          {...footerTotals(lines)}
          subtotalLabel={t("form.subtotal")}
          taxAmountLabel={t("form.taxAmount")}
          totalLabel={t("form.total")}
        />
      </div>

      <FormSheetFooter
        isPending={isPending}
        lineCount={lines.length}
        lineCountText={t("form.lineCount", { count: lines.length })}
        cancelText={t("common:form.cancel")}
        submitText={isEdit ? t("form.save") : t("form.create")}
        onCancel={handleSheetClose}
        onSubmit={handleSave}
      />
      <DiscardDraftDialog {...discard.dialogProps} />
    </Sheet>
  );
}
