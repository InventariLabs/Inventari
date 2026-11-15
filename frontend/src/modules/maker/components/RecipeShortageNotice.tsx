import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, PackagePlus, ShoppingCart } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { Sheet, SheetBody, SheetFooter } from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocalized, unitLabel } from "@/lib/i18nHelpers";
import { useStorages } from "@/modules/shared/hooks/useStorages";
import {
  useAddIngredientStock,
  useOrderRecipeShortages,
} from "@/modules/maker/hooks/useRecipes";
import type { AvailabilityResponse } from "@/modules/maker/types/maker";

type AvailabilityItem = AvailabilityResponse["ingredients"][number];

interface RecipeShortageNoticeProps {
  recipeId: string;
  availability: AvailabilityResponse | undefined;
  /** May this account add stock (items:write)? */
  canAddStock: boolean;
  /** Is purchasing on for this organization, and may this account write it? */
  canOrder: boolean;
  onOrdered?: () => void;
}

function isShort(item: AvailabilityItem): boolean {
  // A null shortage is not "nothing missing" — it is "nobody can compare the
  // formula's measure with the shelf's", and the run is refused for it too.
  return item.shortage === null || Number(item.shortage) > 0;
}

/**
 * What one batch needs that the records do not hold, at the top of the
 * formula's page, with the two ways out of it.
 *
 * The page used to answer a shortage only when a run was attempted, two
 * screens away from the formula that caused it. The user can enter the stock
 * they have — quantity and price, one record per ingredient — or order what
 * they lack when purchasing is on, without leaving production.
 */
export function RecipeShortageNotice({
  recipeId,
  availability,
  canAddStock,
  canOrder,
  onOrdered,
}: RecipeShortageNoticeProps) {
  const { t } = useTranslation("maker");
  const orderShortages = useOrderRecipeShortages();
  const [stockOpen, setStockOpen] = useState(false);

  const short = useMemo(
    () => (availability?.ingredients ?? []).filter(isShort),
    [availability],
  );
  if (short.length === 0) return null;

  const names = short
    .slice(0, 3)
    .map((item) => item.child_template_name)
    .filter(Boolean)
    .join(", ");

  async function order() {
    try {
      const result = await orderShortages.mutateAsync(recipeId);
      if (result.purchase_order_id === null) {
        toast.success(
          (result.already_ordered_count ?? 0) > 0
            ? t("shortage.alreadyOrdered")
            : t("shortage.nothingToOrder"),
        );
      } else {
        toast.success(
          t("shortage.ordered", {
            number: result.number ?? "",
            lines: result.added_count,
          }),
        );
        onOrdered?.();
      }
    } catch (err) {
      toast.error(extractApiError(err, t("shortage.orderFailed")));
    }
  }

  return (
    <>
      <Card
        className="p-4 border-amber-200 bg-amber-50/60 dark:border-amber-900/60 dark:bg-amber-950/20"
        data-testid="maker-recipe-shortage-notice"
      >
        <div className="flex items-start gap-3">
          <AlertTriangle
            size={18}
            className="shrink-0 mt-0.5 text-amber-600"
            aria-hidden
          />
          <div className="min-w-0 flex-1 space-y-1">
            <h2 className="text-sm font-semibold text-on">
              {t("shortage.title")}
            </h2>
            <p className="text-xs text-on-muted">
              {t("shortage.body", { names })}
            </p>
            <ul className="text-xs text-on-muted space-y-0.5">
              {short.map((item) => (
                <li key={item.child_template_id} className="truncate">
                  <span className="text-on">
                    {item.child_template_name ?? item.child_template_id}
                  </span>
                  {" — "}
                  {item.shortage === null
                    ? t("shortage.unmeasurable")
                    : t("shortage.missing", {
                        quantity: formatQuantityLocalized(
                          t,
                          item.to_buy ?? item.shortage,
                          item.to_buy_uom_symbol ?? item.uom_symbol,
                        ),
                      })}
                </li>
              ))}
            </ul>
            {(canAddStock || canOrder) && (
              <div className="flex flex-wrap gap-2 pt-1">
                {canAddStock && (
                  <Button
                    size="sm"
                    variant="outline"
                    leftIcon={<PackagePlus size={14} />}
                    onClick={() => setStockOpen(true)}
                    data-testid="maker-recipe-add-stock"
                  >
                    {t("shortage.addStock")}
                  </Button>
                )}
                {canOrder && (
                  <Button
                    size="sm"
                    variant="outline"
                    leftIcon={<ShoppingCart size={14} />}
                    onClick={() => void order()}
                    disabled={orderShortages.isPending}
                    data-testid="maker-recipe-order-shortage"
                  >
                    {t("shortage.order")}
                  </Button>
                )}
              </div>
            )}
          </div>
        </div>
      </Card>

      {stockOpen && (
        <AddIngredientStockSheet
          onClose={() => setStockOpen(false)}
          items={short}
        />
      )}
    </>
  );
}

interface AddIngredientStockSheetProps {
  onClose: () => void;
  items: AvailabilityItem[];
}

interface StockRow {
  quantity: string;
  price: string;
}

/**
 * Enter the stock that is on the shelf for the ingredients a batch lacks.
 *
 * One record per ingredient, written through the same door a person uses
 * when they enter stock, so it posts a movement and a cost layer at the
 * price typed here. The price is optional: a quantity alone still fixes the
 * quantity, and the estimate then has a rate to ask later.
 */
function AddIngredientStockSheet({
  onClose,
  items,
}: AddIngredientStockSheetProps) {
  const { t } = useTranslation("maker");
  // A general picker: the stock goes on the shelves the organization keeps
  // things in, not on a module's virtual counterparts.
  const {
    data: locations = [],
    isLoading: locationsLoading,
    isError: locationsFailed,
  } = useStorages(undefined, { excludeModuleContexts: true });
  const addStock = useAddIngredientStock();
  const [locationId, setLocationId] = useState("");
  const [rows, setRows] = useState<Record<string, StockRow>>({});
  // Rows already written when a later one failed. A retry must not enter
  // them a second time — the stock would count twice — so they leave the
  // sheet as they land.
  const [savedIds, setSavedIds] = useState<string[]>([]);
  const remaining = items.filter(
    (item) => !savedIds.includes(item.child_template_id),
  );

  // A new batch of rows each time the sheet opens; a stale quantity from the
  // previous visit would be entered twice by a double click. The sheet is
  // mounted only while open, so this runs once per visit.
  useEffect(() => {
    setRows(
      Object.fromEntries(
        items.map((item) => [
          item.child_template_id,
          {
            quantity:
              item.to_buy ??
              (item.shortage === null ? "" : String(item.shortage)),
            price: "",
          },
        ]),
      ),
    );
  }, [items]);

  useEffect(() => {
    if (locationId !== "" || locations.length === 0) return;
    setLocationId(locations[0].id);
  }, [locationId, locations]);

  const rowsToSave = remaining.filter((item) => {
    const row = rows[item.child_template_id];
    return row !== undefined && Number(row.quantity) > 0;
  });

  async function save() {
    if (locationId === "") return;
    const toSave = rowsToSave;
    let saved = 0;
    try {
      for (const item of toSave) {
        const row = rows[item.child_template_id];
        await addStock.mutateAsync({
          name: item.child_template_name ?? t("shortage.stockFallbackName"),
          template_id: item.child_template_id,
          location_id: locationId,
          quantity: row.quantity,
          purchase_price: row.price.trim() === "" ? null : row.price.trim(),
        });
        saved += 1;
        setSavedIds((prev) => [...prev, item.child_template_id]);
      }
      toast.success(t("shortage.stockSaved"));
      onClose();
    } catch (err) {
      // The rows already written stay written and leave the sheet, so a
      // retry enters only what is left; the message says how many landed.
      toast.error(
        saved > 0
          ? t("shortage.stockSavePartial", { saved, total: toSave.length })
          : extractApiError(err, t("shortage.stockSaveFailed")),
      );
    }
  }

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="md"
      aria-labelledby="maker-add-stock-title"
    >
      <SheetBody className="p-5 space-y-4">
        <div>
          <h2
            id="maker-add-stock-title"
            className="text-lg font-semibold text-on"
          >
            {t("shortage.addStockTitle")}
          </h2>
          <p className="text-sm text-on-muted mt-1">
            {t("shortage.addStockHint")}
          </p>
        </div>

        <NativeSelect
          label={t("shortage.location")}
          value={locationId}
          onChange={(e) => setLocationId(e.target.value)}
          error={locationsFailed ? t("shortage.locationsFailed") : undefined}
          disabled={locationsLoading || locations.length === 0}
          data-testid="maker-add-stock-location"
        >
          {locations.length === 0 && (
            <option value="">
              {locationsFailed
                ? t("shortage.locationsFailed")
                : t("shortage.noLocations")}
            </option>
          )}
          {locations.map((location) => (
            <option key={location.id} value={location.id}>
              {location.name}
            </option>
          ))}
        </NativeSelect>

        <div className="space-y-2">
          {remaining.map((item) => {
            const row = rows[item.child_template_id] ?? {
              quantity: "",
              price: "",
            };
            return (
              <div
                key={item.child_template_id}
                className="px-3 py-2 rounded-lg bg-surface-raised/40 border border-border/60 space-y-2"
                data-testid="maker-add-stock-row"
              >
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-sm text-on truncate">
                    {item.child_template_name ?? item.child_template_id}
                  </span>
                  <span className="text-xs text-on-muted shrink-0">
                    {t("shortage.needs", {
                      quantity: formatQuantityLocalized(
                        t,
                        item.needed,
                        item.uom_symbol,
                      ),
                    })}
                  </span>
                </div>
                <div className="flex flex-wrap items-end gap-2">
                  <Input
                    wrapperClassName="w-28"
                    type="number"
                    min="0"
                    step="any"
                    label={t("shortage.quantity")}
                    value={row.quantity}
                    onChange={(e) =>
                      setRows((prev) => ({
                        ...prev,
                        [item.child_template_id]: {
                          ...row,
                          quantity: e.target.value,
                        },
                      }))
                    }
                    data-testid="maker-add-stock-quantity"
                  />
                  <span className="text-xs text-on-muted pb-2.5">
                    {unitLabel(t, item.to_buy_uom_symbol ?? item.uom_symbol)}
                  </span>
                  <Input
                    wrapperClassName="w-28"
                    type="number"
                    min="0"
                    step="0.01"
                    label={t("shortage.price")}
                    description={t("shortage.priceHint")}
                    value={row.price}
                    onChange={(e) =>
                      setRows((prev) => ({
                        ...prev,
                        [item.child_template_id]: {
                          ...row,
                          price: e.target.value,
                        },
                      }))
                    }
                    data-testid="maker-add-stock-price"
                  />
                </div>
              </div>
            );
          })}
        </div>
      </SheetBody>
      <SheetFooter className="p-4 flex justify-end gap-2">
        <Button variant="ghost" onClick={onClose}>
          {t("common:actions.cancel")}
        </Button>
        <Button
          onClick={() => void save()}
          disabled={
            addStock.isPending ||
            locationsFailed ||
            locationId === "" ||
            rowsToSave.length === 0
          }
          data-testid="maker-add-stock-save"
        >
          {t("shortage.addStockSave", { saved: rowsToSave.length })}
        </Button>
      </SheetFooter>
    </Sheet>
  );
}
