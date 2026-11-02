import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import { useQueryClient } from "@tanstack/react-query";
import {
  createEmptyQuickAddLineDraft,
  type QuickAddLineDraft,
  type ReceiptDraftLine,
} from "@/modules/warehouse/components/documentFormShared";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { extractApiError } from "@/lib/errors";
import { queryKeys } from "@/hooks/queries/keys";

/**
 * Where a receipt's lines have to name a catalogue product. The panel then
 * makes the product it describes before the line is added, and the line it
 * was opened from gives way to the one it adds.
 */
export interface QuickAddCatalogue {
  /** Off for the documents whose lines may stay as typed. */
  namesAProduct: boolean;
  lines: ReceiptDraftLine[];
  replaceLine: (key: string, line: ReceiptDraftLine) => void;
}

function draftToLine(
  draft: QuickAddLineDraft,
  productTemplateId?: string,
): ReceiptDraftLine {
  return {
    _key: crypto.randomUUID(),
    item_id: draft.item_id,
    product_template_id: productTemplateId,
    name: draft.name,
    brand: draft.brand || undefined,
    barcode: draft.barcode || undefined,
    sku: draft.sku || undefined,
    image_url: draft.image_url,
    quantity: draft.quantity ?? 1,
    uom_id: draft.uom_id,
    batch_number: draft.batch_number,
    serial_number: draft.serial_number || undefined,
    expiry_date: draft.expiry_date,
    notes: draft.notes,
    unit_price: "",
    tax_rate: "",
  };
}

/** The panel describes a product the catalogue does not hold yet. */
function quickAddMakesProduct(draft: QuickAddLineDraft): boolean {
  return !draft.item_id && !draft.product_template_id;
}

/**
 * Quick-add-line flow of the document form: draft state, open/close, and
 * submit (appends the draft as a new line). Extracted from
 * DocumentFormModal to keep the modal focused on the form itself.
 */
export function useQuickAddLine(
  appendLine: (line: ReceiptDraftLine) => void,
  receipt?: QuickAddCatalogue,
) {
  const catalogue = receipt?.namesAProduct ? receipt : undefined;
  const { t } = useTranslation(["warehouse", "common"]);
  const queryClient = useQueryClient();
  const [quickAddOpen, setQuickAddOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [quickAddDraft, setQuickAddDraft] = useState<QuickAddLineDraft>(
    createEmptyQuickAddLineDraft(),
  );

  const openQuickAdd = useCallback((prefill?: Partial<QuickAddLineDraft>) => {
    setQuickAddDraft({
      ...createEmptyQuickAddLineDraft(),
      ...prefill,
    });
    setQuickAddOpen(true);
  }, []);

  // Everything the typed line already says carries into the panel, so making
  // the product neither asks for it a second time nor drops it: the code and
  // brand go onto the product, the serial stays with the line.
  const openForTypedLine = (key: string, name: string) => {
    const line = catalogue?.lines.find((candidate) => candidate._key === key);
    openQuickAdd({
      name,
      replaces: key,
      brand: line?.brand ?? "",
      barcode: line?.barcode ?? "",
      sku: line?.sku ?? "",
      serial_number: line?.serial_number ?? "",
      quantity: line?.quantity ?? 1,
      uom_id: line?.uom_id ?? null,
      batch_number: line?.batch_number ?? "",
      expiry_date: line?.expiry_date ?? "",
      notes: line?.notes ?? "",
    });
  };

  const closeQuickAdd = useCallback(() => {
    setQuickAddOpen(false);
    setQuickAddDraft(createEmptyQuickAddLineDraft());
  }, []);

  // The product a receipt line names: the one the draft already carries, or
  // one made now from its name and unit. Undefined when the make failed —
  // the reader keeps the panel and what they typed into it.
  const productFor = async (
    draft: QuickAddLineDraft,
  ): Promise<string | null | undefined> => {
    if (!catalogue || !quickAddMakesProduct(draft)) {
      return draft.product_template_id ?? null;
    }
    if (!draft.uom_id) {
      toast.error(t("common:productQuickCreate.uomRequired"));
      return undefined;
    }
    setCreating(true);
    try {
      const product = await productTemplatesApi.create(
        draft.name.trim(),
        draft.uom_id,
        { brand: draft.brand, barcode: draft.barcode },
      );
      void queryClient.invalidateQueries({
        queryKey: queryKeys.productTemplates.count,
      });
      return product.id;
    } catch (error) {
      toast.error(extractApiError(error, t("common:productQuickCreate.error")));
      return undefined;
    } finally {
      setCreating(false);
    }
  };

  const handleQuickAddSubmit = async () => {
    if (!quickAddDraft.name.trim()) {
      toast.error(t("common:validation.nameRequired"));
      return;
    }

    // An emptied quantity field is a decision to name none, not a silent
    // single piece — the field reports null and the line stops here.
    if (quickAddDraft.quantity === null) {
      toast.error(t("common:validation.quantityRequired"));
      return;
    }

    const productTemplateId = await productFor(quickAddDraft);
    if (productTemplateId === undefined) return;
    const line = draftToLine(quickAddDraft, productTemplateId ?? undefined);
    if (catalogue && quickAddDraft.replaces) {
      catalogue.replaceLine(quickAddDraft.replaces, line);
    } else {
      appendLine(line);
    }
    toast.success(t("warehouse:lines.addedOne", { name: quickAddDraft.name }));
    closeQuickAdd();
  };

  return {
    quickAddOpen,
    quickAddDraft,
    setQuickAddDraft,
    openQuickAdd,
    openForTypedLine: catalogue ? openForTypedLine : undefined,
    closeQuickAdd,
    handleQuickAddSubmit,
    // The panel's half of the line editor's props, wired once here.
    editorProps: {
      quickAddOpen,
      quickAddValue: quickAddDraft,
      quickAddMakesProduct:
        Boolean(catalogue) && quickAddMakesProduct(quickAddDraft),
      quickAddCreating: creating,
      onQuickAddChange: (updates: Partial<QuickAddLineDraft>) =>
        setQuickAddDraft((current) => ({ ...current, ...updates })),
      onQuickAddSubmit: () => void handleQuickAddSubmit(),
      onQuickAddCancel: closeQuickAdd,
      onCreateProduct: catalogue ? openForTypedLine : undefined,
    },
  };
}
