import { useEffect, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { toast } from "sonner";
import { ChefHat } from "lucide-react";
import { Sheet, SheetBody } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { StorageRequired } from "@/modules/shared/components/StorageRequired";
import {
  FIELD_LABEL_CLASS,
  LocationCombobox,
  readJson,
  useLocationOffer,
  useOfferedLocations,
  writeJson,
} from "@/module-sdk";
import type { SlotDataMap } from "@/lib/moduleRegistry";
import type { UomCategory } from "@/types";
import { ProductSearchInput } from "./ProductSearchInput";
import { ShortageModal } from "./ShortageModal";
import { parseShortageError } from "../lib/shortageError";
import { OUTPUT_LOCATION_SCOPE } from "../lib/outputLocationScope";
import { extractApiError } from "@/lib/errors";
import { QueryFailure } from "@/components/ui/QueryResult";
import { unitLabel } from "@/lib/i18nHelpers";
import { queryKeys } from "@/hooks/queries/keys";
import { findUom, isCountedUom, useUoms } from "@/modules/shared/hooks/useUoms";
import {
  createMakerRecipeFromCulinary,
  createProductionOrderFromBridge,
  discardBridgeRecipe,
  findBridgedRecipe,
  type MakerRecipeBridgeResult,
  type MakerRecipeFromCulinary,
} from "../api/recipeBridge";

interface CookForStockModalProps {
  open: boolean;
  onClose: () => void;
  /** The culinary recipe to snapshot into a maker recipe. */
  recipe: SlotDataMap["recipe_cook_for_stock"]["recipe"];
}

interface SelectedProduct {
  product_template_id: string;
  name: string;
  uom_id: string | null;
  uom_symbol: string | null;
}

/**
 * Where the last batch was sent.
 *
 * The field is required and rightly so — `ProductionOrder.output_storage_
 * location_id` is not nullable, and a finished batch with nowhere to land has
 * no StockQuant to belong to. But requiring an answer is not the same as
 * asking for one, and in a home installation the answer is the same every
 * time. So the question is asked once and remembered; a stale id that no
 * longer exists simply does not match and the field falls back to empty.
 */
const LAST_OUTPUT_LOCATION_KEY = "inventari:cookForStock:outputLocation";

function readLastOutputLocation(): string {
  // The guards (corrupted value, storage unavailable) live in the shared
  // reader; the shape check stays here, because a generic parameter is a
  // claim, not one.
  const stored = readJson<unknown>(LAST_OUTPUT_LOCATION_KEY, "");
  return typeof stored === "string" ? stored : "";
}

/**
 * The output product's unit as this sheet needs it.
 *
 * Servings are a count of portions. They stand for the batch's yield only
 * where the product is counted too (a piece, a pack) or has no unit yet; a
 * product kept in kilograms or litres is asked how much a batch makes, never
 * handed the number of servings — twelve servings are not twelve kilograms.
 * Until the unit catalogue has loaded a product with a unit is asked. The
 * product search does not always carry the unit's symbol; the catalogue names
 * it by id.
 */
function outputUnit(
  categories: UomCategory[] | undefined,
  product: SelectedProduct | null,
) {
  return {
    servingsFit: !product?.uom_id || isCountedUom(categories, product.uom_id),
    unitSymbol:
      findUom(categories, product?.uom_id)?.symbol ?? product?.uom_symbol,
  };
}

/**
 * The unit the yield is written in. A product with no unit is counted in
 * pieces; the figure never stands bare.
 */
function yieldUnit(
  t: TFunction<"recipes">,
  symbol: string | null | undefined,
  servingsFit: boolean,
): string {
  return unitLabel(t, symbol) || (servingsFit ? unitLabel(t, "pcs") : "");
}

/**
 * What the yield field starts from: the yield the pair's BOM already stores
 * (the bridge refuses another one), else the servings where they are an amount
 * in the product's unit, else nothing — the person is asked. A stored
 * weight or volume yield that is just the servings is a number taken for an
 * amount before the sheet asked, so it is not offered either; the line under
 * the field names it.
 */
function startingYield(
  storedYield: number | null,
  servingsFit: boolean,
  servings: number,
): string {
  if (storedYield !== null) {
    return !servingsFit && storedYield === servings ? "" : String(storedYield);
  }
  return servingsFit ? String(servings) : "";
}

/**
 * What a run comes to: the amount one batch makes times the number of
 * batches, or null while either is missing. Rounded to the four places the
 * backend keeps, which also hides binary noise (1.1 × 3).
 */
function planBatch(yieldText: string, scale: string) {
  // Four places is what the backend accepts for a yield too, so the number
  // sent and the number planned with are the same one.
  const yieldNum =
    yieldText.trim() === ""
      ? NaN
      : Math.round(Number(yieldText) * 10000) / 10000;
  const validYield = Number.isFinite(yieldNum) && yieldNum > 0;
  const scaleNum = Number(scale);
  const validScale = Number.isFinite(scaleNum) && scaleNum >= 1;
  const plannedQty =
    validYield && validScale
      ? String(Math.round(yieldNum * scaleNum * 10000) / 10000)
      : null;
  return { yieldNum, validYield, scaleNum, validScale, plannedQty };
}

function rememberOutputLocation(id: string): void {
  writeJson(LAST_OUTPUT_LOCATION_KEY, id);
}

/**
 * Recipe-to-production bridge modal: "Cook a batch for stock".
 *
 * Snapshots the culinary recipe into a maker recipe (one-way, frozen —
 * later edits of the culinary recipe never propagate) and creates a DRAFT
 * production order for the chosen product, scale and output location.
 * The maker recipe is reused when the same (product, culinary recipe) pair
 * was already snapshotted (idempotent backend contract).
 */
export function CookForStockModal({
  open,
  onClose,
  recipe,
}: CookForStockModalProps) {
  // The sheet speaks on the recipe page about the culinary recipe, in that
  // page's words; the production glossary (bomTerminology.test.ts) keeps the
  // kitchen word out of this module's own catalogue.
  const { t } = useTranslation("recipes");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  // Where a batch lands is a stock-flow question: the output picker offers
  // what may hold stock, never a place a module owns. Scoped at the query,
  // so the remembered and single-location defaults below cannot land on a
  // module's location either. No keepId — the modal opens holding nothing.
  const {
    total: storageCount,
    first: storages,
    isError: storagesFailed,
    error: storagesError,
    refetch: refetchStorages,
  } = useLocationOffer(OUTPUT_LOCATION_SCOPE);
  // The remembered place is asked of the same scope: the places on offer are
  // a search, not a list this modal holds, and a place that still exists may
  // have been archived or given to a module since the last batch.
  const remembered = readLastOutputLocation();
  const rememberedOffered = useOfferedLocations(open ? [remembered] : [], {
    excludeHeldBack: true,
  });

  const [product, setProduct] = useState<SelectedProduct | null>(null);
  const [scale, setScale] = useState("1");
  // What one batch makes, in the product's unit. `null` is "not typed yet":
  // the number then comes from the servings when they fit the product, and is
  // asked for when they do not.
  const [batchYield, setBatchYield] = useState<string | null>(null);
  const [storageId, setStorageId] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [shortage, setShortage] = useState<ReturnType<
    typeof parseShortageError
  > | null>(null);
  // The bridge builds two records in two calls. When the second one is
  // refused and the operator walks away, the first must not stay behind: a
  // formula in the production catalogue that nobody asked for and no screen
  // mentions. Remember what this attempt created so leaving takes it along.
  const strandedRecipeId = useRef<string | null>(null);

  // The location the last batch went to, or the only one there is. Asking for
  // a decision that has one sensible answer is pure cost, and both cases are
  // that: a home installation has one place to put things, and an operator
  // who filled this in yesterday is filling it in again.
  useEffect(() => {
    if (!open || storageId || !storageCount) return;
    if (rememberedOffered.isLoading) return;
    if (remembered && rememberedOffered.data?.includes(remembered)) {
      setStorageId(remembered);
      return;
    }
    if (storageCount === 1) setStorageId(storages[0].id);
  }, [
    open,
    storageId,
    storageCount,
    storages,
    remembered,
    rememberedOffered.isLoading,
    rememberedOffered.data,
  ]);

  const { data: uomCategories } = useUoms();

  const { servingsFit, unitSymbol } = outputUnit(uomCategories, product);
  // A pair that was bridged before keeps the yield its BOM stores, and the
  // bridge refuses another one, so the field starts from it — in its unit.
  const { data: bridged } = useQuery({
    queryKey: queryKeys.maker.bridgedRecipe(
      product?.product_template_id ?? "",
      recipe.id,
    ),
    queryFn: () => findBridgedRecipe(product!.product_template_id, recipe.id),
    enabled: open && !!product,
  });
  const storedYield = bridged ? Number(bridged.batch_yield_qty) : null;
  const yieldText =
    batchYield ?? startingYield(storedYield, servingsFit, recipe.servings);
  const unit = yieldUnit(
    t,
    bridged?.batch_yield_uom_symbol ?? unitSymbol,
    servingsFit,
  );

  const { yieldNum, validYield, scaleNum, validScale, plannedQty } = planBatch(
    yieldText,
    scale,
  );
  const canSubmit =
    !!product && validYield && validScale && !!storageId && !submitting;

  const handleSubmit = async (confirmShortage = false) => {
    if (!product || !storageId || plannedQty === null) return;
    setSubmitting(true);
    try {
      const payload: MakerRecipeFromCulinary = {
        source_recipe_id: recipe.id,
        output_template_id: product.product_template_id,
        name: recipe.name,
        // One batch = one culinary cook; the order's planned_qty scales it.
        batch_yield_qty: String(yieldNum),
      };
      const makerRecipe: MakerRecipeBridgeResult =
        await createMakerRecipeFromCulinary(payload);
      if (makerRecipe.created) strandedRecipeId.current = makerRecipe.id;
      // The pair has a BOM now: the next sheet on it starts from its yield,
      // not from a cached "no BOM yet" answer.
      void queryClient.invalidateQueries({
        queryKey: queryKeys.maker.recipesAll,
      });
      const order = await createProductionOrderFromBridge({
        output_template_id: product.product_template_id,
        recipe_id: makerRecipe.id,
        planned_qty: plannedQty,
        output_location_id: storageId,
        confirm_shortage: confirmShortage,
      });
      rememberOutputLocation(storageId);
      // The order adopted the snapshot; it is nobody's litter now.
      strandedRecipeId.current = null;
      toast.success(t("cookForStock.success"));
      onClose();
      navigate(`/maker/production/${order.id}`);
    } catch (err) {
      const shortageError = parseShortageError(err);
      if (shortageError) {
        setShortage(shortageError);
      } else {
        toast.error(extractApiError(err, t("cookForStock.error")));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleClose = () => {
    const stranded = strandedRecipeId.current;
    strandedRecipeId.current = null;
    // Fire and forget: a refusal here means the maker module found the
    // snapshot in use, which is the one case where keeping it is right.
    if (stranded) void discardBridgeRecipe(stranded).catch(() => undefined);
    onClose();
  };

  return (
    <>
      <Sheet
        open={open}
        onClose={handleClose}
        maxWidth="md"
        aria-label={t("cookForStock.title")}
      >
        <SheetBody className="p-5 space-y-4">
          <div className="flex items-center gap-3">
            <div className="p-2.5 rounded-xl bg-accent/10 text-accent">
              <ChefHat size={20} />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-on">
                {t("cookForStock.title")}
              </h2>
              <p className="text-sm text-on-muted">
                {t("cookForStock.subtitle", { name: recipe.name })}
              </p>
            </div>
          </div>

          <div className="space-y-1.5">
            {product ? (
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-raised/60 border border-border/60">
                <span className="flex-1 min-w-0 truncate text-sm text-on">
                  {product.name}
                </span>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => setProduct(null)}
                  aria-label={t("cookForStock.changeProduct")}
                >
                  {t("cookForStock.changeProduct")}
                </Button>
              </div>
            ) : (
              <ProductSearchInput
                onSelect={(p) => {
                  setBatchYield(null);
                  setProduct({
                    product_template_id: p.product_template_id,
                    name: p.name,
                    uom_id: p.uom_id ?? null,
                    uom_symbol: p.uom_symbol ?? null,
                  });
                }}
                label={t("cookForStock.productLabel")}
                placeholder={t("cookForStock.productPlaceholder")}
                testId="cook-for-stock-product-search"
              />
            )}
          </div>

          <Input
            id="cook-for-stock-yield"
            label={t("cookForStock.yieldLabel")}
            description={yieldDescription(
              t,
              storedYield,
              servingsFit,
              recipe.servings,
              unit,
            )}
            type="number"
            min="0"
            step="any"
            suffix={unit || undefined}
            value={yieldText}
            onChange={(e) => setBatchYield(e.target.value)}
            data-testid="cook-for-stock-yield-input"
          />

          <div className="grid grid-cols-2 gap-3">
            <Input
              id="cook-for-stock-scale"
              label={t("cookForStock.scaleLabel")}
              description={t("cookForStock.scaleHint")}
              type="number"
              min="1"
              step="1"
              value={scale}
              onChange={(e) => setScale(e.target.value)}
              data-testid="cook-for-stock-scale-input"
            />
            {/* A result, and it has to look like one: dressed as a field with
                a border and a box, it read as a second number to fill in, and
                the pair contradicted each other. No box, no border, and the
                arithmetic underneath saying where it came from. */}
            <div className="space-y-1.5">
              <span className={FIELD_LABEL_CLASS}>
                {t("cookForStock.plannedQty")}
              </span>
              <p
                className="h-10 flex items-center text-lg font-semibold text-on tabular-nums"
                data-testid="cook-for-stock-planned-qty"
              >
                {plannedQty === null
                  ? "—"
                  : unit
                    ? `${plannedQty} ${unit}`
                    : plannedQty}
              </p>
              <p className="text-xs text-on-muted">
                {t("cookForStock.plannedQtyFormula", {
                  qty: validYield
                    ? unit
                      ? `${yieldNum} ${unit}`
                      : yieldNum
                    : "—",
                  batches: validScale ? scaleNum : "—",
                })}
              </p>
            </div>
          </div>

          {/* The same picker the production sheet uses: a flat list of
              names cannot tell the shelf in the kitchen from the shelf in
              the cellar, and an organization with no locations at all needs
              a way to make one, not an empty dropdown. */}
          {storagesFailed ? (
            <QueryFailure
              error={storagesError}
              onRetry={() => refetchStorages()}
            />
          ) : storageCount === 0 ? (
            <StorageRequired
              variant="banner"
              purpose="stock"
              onCreated={(storage) => setStorageId(storage.id)}
            />
          ) : (
            <LocationCombobox
              id="cook-for-stock-storage"
              label={t("cookForStock.storageLabel")}
              title={t("cookForStock.storageLabel")}
              scope={OUTPUT_LOCATION_SCOPE}
              value={storageId}
              onChange={setStorageId}
              placeholder={t("cookForStock.storagePlaceholder")}
              searchPlaceholder={t("cookForStock.storageSearchPlaceholder")}
              emptyMessage={t("cookForStock.storageEmpty")}
            />
          )}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={handleClose}>
              {t("common:actions.cancel")}
            </Button>
            <Button
              onClick={() => handleSubmit(false)}
              disabled={!canSubmit}
              data-testid="cook-for-stock-submit"
            >
              <ChefHat size={16} />
              {submitting
                ? t("cookForStock.submitting")
                : t("cookForStock.submit")}
            </Button>
          </div>
        </SheetBody>
      </Sheet>

      {shortage && (
        <ShortageModal
          open
          variant={shortage.error === "shortage_blocked" ? "danger" : "warning"}
          shortages={shortage.shortages}
          canConfirm={shortage.error === "shortage_warning"}
          onConfirm={() => {
            setShortage(null);
            void handleSubmit(true);
          }}
          onCancel={() => setShortage(null)}
        />
      )}
    </>
  );
}

/**
 * The bridge as the recipes module asks for it: the recipe page renders the
 * `recipe_cook_for_stock` slot and owns when it is open, and this module, the
 * one whose records the batch creates, draws the sheet.
 */
export default function CookForStockSlot({
  data,
}: {
  data: SlotDataMap["recipe_cook_for_stock"];
}) {
  return (
    <CookForStockModal
      open={data.open}
      onClose={data.onClose}
      recipe={data.recipe}
    />
  );
}

/**
 * The line under the yield field (below the component: the key scan reads a
 * `t(` call in the namespace of the hook above it). A stored measured yield that is just the
 * servings is a number somebody took for an amount before the sheet asked; it
 * is named as doubtful, not recommended.
 */
function yieldDescription(
  t: TFunction<"recipes">,
  storedYield: number | null,
  servingsFit: boolean,
  servings: number,
  unit: string,
): string {
  if (storedYield !== null) {
    const amount = unit ? `${storedYield} ${unit}` : String(storedYield);
    return !servingsFit && storedYield === servings
      ? t("cookForStock.yieldStoredDoubtful", { amount })
      : t("cookForStock.yieldStored", { amount });
  }
  return servingsFit
    ? t("cookForStock.yieldHint", { servings })
    : t("cookForStock.yieldAsk", { servings });
}
