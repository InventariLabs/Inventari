import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useCanWrite } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { useDebounce } from "@/module-sdk";
import { todayIso } from "@/utils/formatters";
import {
  useCreateProductionOrder,
  useProductionPreview,
  useRecordMadeProduction,
} from "@/modules/maker/hooks/useProduction";
import { parseShortageError } from "@/modules/maker/lib/shortageError";
import { defaultBestBefore } from "@/modules/maker/lib/bestBefore";
import { useBatchChoice } from "@/modules/maker/hooks/useBatchChoice";
import type { IngredientBatchQuery } from "@/modules/maker/api/batches";
import type { ProductOption } from "@/modules/maker/api/products";
import type {
  ProductionMode,
  ProductionOrderCreateInput,
  ShortageEntry,
} from "@/modules/maker/types/maker";

export interface PreselectedProduct {
  output_template_id: string;
  name: string;
  recipe_id?: string | null;
  /** A quantity to start the form with, e.g. what a reorder alert asks to make. */
  quantity?: string;
  /** Opens the form as a plan rather than as a run already made. */
  mode?: ProductionMode;
}

function preselectedOption(product: PreselectedProduct): ProductOption {
  return {
    product_template_id: product.output_template_id,
    name: product.name,
    sku: null,
    barcode: null,
    brand: null,
    uom_id: null,
    uom_symbol: null,
    image_url: null,
    is_stub: false,
  };
}

interface PayloadInput {
  mode: ProductionMode;
  selected: ProductOption | null;
  parsedQty: number;
  storageId: string;
  productionDate: string;
  notes: string;
  outputLotName: string;
  preselectedProduct?: PreselectedProduct;
}

function buildPayload({
  mode,
  selected,
  parsedQty,
  storageId,
  productionDate,
  notes,
  outputLotName,
  preselectedProduct,
}: PayloadInput): ProductionOrderCreateInput | null {
  if (!selected || !storageId) return null;
  if (Number.isNaN(parsedQty) || parsedQty <= 0) return null;
  return {
    output_template_id: selected.product_template_id,
    planned_qty: String(parsedQty),
    output_location_id: storageId,
    notes: notes.trim() || null,
    output_lot_name: outputLotName.trim() || null,
    // A plan is for a day — the day it appears in To do. A run already
    // made is dated by its recording.
    ...(mode === "planned" && productionDate
      ? { production_date: productionDate }
      : {}),
    // Link the order to the source formula only while the preselected
    // product is still the selected one — a changed product has no recipe.
    ...(preselectedProduct &&
    selected.product_template_id === preselectedProduct.output_template_id
      ? { recipe_id: preselectedProduct.recipe_id ?? null }
      : {}),
  };
}

/** The run the ingredient batch plan is asked for, once the form names one. */
function batchQueryOf(
  payload: ProductionOrderCreateInput | null,
): IngredientBatchQuery | null {
  if (!payload) return null;
  return {
    output_template_id: payload.output_template_id,
    planned_qty: String(payload.planned_qty),
    output_location_id: payload.output_location_id,
    recipe_id: payload.recipe_id ?? null,
  };
}

/**
 * The production sheet's form: what is being recorded, where, how much, and
 * the live preview of what that run takes.
 *
 * The preview is asked for the product, the quantity and the location —
 * what the run needs depends on those, not on the notes or the day — and
 * debounced as text, since a fresh object every render never settles.
 */
export function useProductionForm(
  open: boolean,
  /** What the stock picker offers (`useLocationOffer`): how many places, and
   * the first two — enough to take the only one there is. */
  offer: { total: number | undefined; first: { id: string }[] },
  preselectedProduct: PreselectedProduct | undefined,
  /** The mode a fresh form opens in: a screen that is about planning opens it as a plan. */
  startAs: ProductionMode,
) {
  const { t } = useTranslation("maker");
  // Recording a run already made posts stock, which only an account that may
  // write items can do; everyone else plans.
  const canRecordMade = useCanWrite("items");
  const [chosenMode, setMode] = useState<ProductionMode>(startAs);
  const mode: ProductionMode = canRecordMade ? chosenMode : "planned";
  const [selected, setSelected] = useState<ProductOption | null>(null);
  const [qty, setQty] = useState("");
  const [storageId, setStorageId] = useState("");
  const [productionDate, setProductionDate] = useState(todayIso);
  const [notes, setNotes] = useState("");
  const [outputLotName, setOutputLotName] = useState("");
  // The best-before the person typed; null follows the proposal (today plus
  // the product's shelf life) until they change it.
  const [typedBestBefore, setBestBefore] = useState<string | null>(null);

  useEffect(() => {
    if (open) return;
    setBestBefore(null);
    setMode(startAs);
    setSelected(null);
    setQty("");
    setStorageId("");
    setProductionDate(todayIso());
    setNotes("");
    setOutputLotName("");
  }, [open, startAs]);

  // The only warehouse location is the answer; asking for it is a chore.
  const onlyStorageId = offer.total === 1 ? offer.first[0].id : null;
  useEffect(() => {
    if (open && onlyStorageId && storageId === "") setStorageId(onlyStorageId);
  }, [open, onlyStorageId, storageId]);

  // Pre-select the output product when the sheet was opened from a
  // formula card. The product stays changeable via the Change button.
  useEffect(() => {
    if (!open || !preselectedProduct) return;
    setSelected(preselectedOption(preselectedProduct));
    if (preselectedProduct.quantity) setQty(preselectedProduct.quantity);
    if (preselectedProduct.mode) setMode(preselectedProduct.mode);
  }, [open, preselectedProduct]);

  const parsedQty = Number(qty);
  const requirements = [
    selected === null ? t("create.hints.product") : null,
    Number.isNaN(parsedQty) || parsedQty <= 0
      ? t("create.hints.quantity")
      : null,
    storageId === "" ? t("create.hints.storage") : null,
  ].filter((requirement) => requirement !== null);

  const payload = buildPayload({
    mode,
    selected,
    parsedQty,
    storageId,
    productionDate,
    notes,
    outputLotName,
    preselectedProduct,
  });
  const previewKey = useDebounce(
    payload
      ? JSON.stringify({
          output_template_id: payload.output_template_id,
          planned_qty: payload.planned_qty,
          output_location_id: payload.output_location_id,
          recipe_id: payload.recipe_id,
        })
      : null,
    300,
  );
  const previewPayload = useMemo<ProductionOrderCreateInput | null>(
    () => (previewKey ? JSON.parse(previewKey) : null),
    [previewKey],
  );
  const preview = useProductionPreview(open ? previewPayload : null);
  // A run already made says which batches it took; a plan decides that when
  // it closes.
  const batches = useBatchChoice(
    open && mode === "made" ? batchQueryOf(previewPayload) : null,
  );
  const bestBefore =
    typedBestBefore ??
    defaultBestBefore(todayIso(), preview.data?.shelf_life_days);

  const unit = preview.data?.planned_uom_symbol ?? selected?.uom_symbol ?? null;
  // The recipe is written per batch; the person writes what came out.
  const batchYield = preview.data?.batch_yield_qty;
  // The hint's sentence ends the batch with its own full stop, and a unit
  // written "szt." brings one of its own: one is enough.
  const batch = batchYield
    ? formatQuantityLocalized(t, batchYield, unit).replace(/\.$/, "")
    : "";
  let batchHint: string | undefined;
  if (batch && mode === "made")
    batchHint = t("create.batchHintMade", { batch });
  else if (batch) batchHint = t("create.batchHintPlanned", { batch });

  return {
    mode,
    setMode,
    canRecordMade,
    selected,
    setSelected,
    qty,
    setQty,
    parsedQty,
    storageId,
    setStorageId,
    productionDate,
    setProductionDate,
    notes,
    setNotes,
    outputLotName,
    setOutputLotName,
    bestBefore,
    setBestBefore,
    shelfLifeDays: preview.data?.shelf_life_days ?? null,
    batches,
    requirements,
    canPreview: requirements.length === 0,
    payload,
    preview,
    unit: unit ? unitLabel(t, unit) : null,
    batchHint,
  };
}

export type ProductionForm = ReturnType<typeof useProductionForm>;

export interface ShortageState {
  variant: "warning" | "danger";
  shortages: ShortageEntry[];
}

/**
 * Saving the sheet: a run already made in one step, a plan as a draft
 * through the shortage strategy (warn, then "create anyway"; block).
 */
export function useProductionSave(
  form: ProductionForm,
  {
    onClose,
    onSuccess,
  }: { onClose: () => void; onSuccess?: (id: string) => void },
) {
  const { t } = useTranslation("maker");
  const navigate = useNavigate();
  const createMutation = useCreateProductionOrder();
  const madeMutation = useRecordMadeProduction();
  const [shortageState, setShortageState] = useState<ShortageState | null>(
    null,
  );

  function finish(orderId: string, message: string) {
    setShortageState(null);
    toast.success(message);
    onClose();
    if (onSuccess) onSuccess(orderId);
    else navigate(`/maker/production/${orderId}`);
  }

  function refuse(err: unknown, confirmShortage: boolean) {
    const shortageInfo = parseShortageError(err);
    // A run already made is refused only for a line whose unit cannot be
    // compared with its stock; a plan by the shortage strategy.
    if (
      shortageInfo &&
      (shortageInfo.error !== "shortage_warning" || !confirmShortage)
    ) {
      setShortageState({
        variant:
          shortageInfo.error === "shortage_warning" ? "warning" : "danger",
        shortages: shortageInfo.shortages,
      });
      return;
    }
    toast.error(extractApiError(err, t("create.errors.create")));
  }

  function save(confirmShortage = false) {
    const payload = form.payload;
    if (!payload) {
      toast.error(t("create.errors.missingFields"));
      return;
    }
    if (form.mode === "made") {
      const made = {
        ...payload,
        best_before: form.bestBefore || null,
        ingredient_lots: form.batches.payload,
      };
      madeMutation.mutate(made, {
        onSuccess: (order) => finish(order.id, t("create.successMade")),
        onError: (err) => refuse(err, false),
      });
      return;
    }
    createMutation.mutate(
      { ...payload, confirm_shortage: confirmShortage },
      {
        onSuccess: (order) => finish(order.id, t("create.success")),
        onError: (err) => refuse(err, confirmShortage),
      },
    );
  }

  return {
    save,
    isSaving: createMutation.isPending || madeMutation.isPending,
    shortageState,
    setShortageState,
  };
}
