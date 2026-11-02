import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import type {
  CategoryDTO,
  FieldDefinition,
  Item,
  StorageLocationSummary,
} from "@/types";
import { itemSku, productCode } from "@/types";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useFreeLabel } from "@/modules/inventory/hooks/useFreeLabel";
import ItemUseBy, { isOpenedRecord } from "./ItemUseBy";
import { effectiveExpiry } from "@/utils/effectiveExpiry";
import {
  categoryLabel,
  formatQuantityLocalized,
  makeTDynamic,
} from "@/lib/i18nHelpers";
import { computeFieldDefinitions } from "@/modules/inventory/hooks/computeFieldDefinitions";
import { getLabel } from "@/modules/inventory/components/FieldRenderers/helpers";
import { useMoney } from "@/hooks/useMoney";
import {
  quantityText,
  usePartialPackage,
} from "@/modules/shared/hooks/usePartialPackage";
import { useShowInventoryValue } from "@/modules/shared/hooks/useShowInventoryValue";
import { getStorageLocationPath } from "@/utils/helpers";
import { formatDate, toAmount } from "@/utils/formatters";
import {
  isVirtualUsage,
  virtualUsageLabel,
} from "@/modules/shared/lib/storageUsage";

interface ItemDetailOverviewProps {
  item: Item;
  storages: StorageLocationSummary[] | undefined;
  categories: CategoryDTO[] | undefined;
}

/** The product's issue order. FIFO answers when nothing was set — the same
 *  reading the stock engine gives an empty one; a record without a product
 *  has no row. */
function removalStrategyText(item: Item): string | null {
  if (!item.template) return null;
  return item.template.removal_strategy ?? "FIFO";
}

/** One labelled value. Rows with nothing in them are not rendered at all. */
function Field({ label, children }: { label: string; children: ReactNode }) {
  if (children === null || children === undefined || children === "")
    return null;
  return (
    <div className="py-3 border-b border-border">
      <dt className="text-xs font-medium text-on-muted uppercase tracking-wide">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-on break-words">{children}</dd>
    </div>
  );
}

/** A field's answer as the reader reads it, or null when it holds none. A
 *  saved false is an answer — the form stores it only when someone unticks
 *  the box, and an import stores a "no" — so it reads as No, not as blank. */
function answerText(
  field: FieldDefinition,
  value: unknown,
  [yes, no]: [string, string],
): string | null {
  if (value === null || value === undefined || value === "") return null;
  if (field.type === "boolean") return value === true ? yes : no;
  if (field.type === "date") return formatDate(String(value));
  if (Array.isArray(value)) return value.length > 0 ? value.join(", ") : null;
  if (typeof value === "object") {
    const money = value as { amount?: unknown; currency?: unknown };
    return money.amount
      ? `${money.amount} ${money.currency ?? ""}`.trim()
      : null;
  }
  return String(value);
}

/**
 * The product fields the record's location and category ask for, with what
 * the record answered. A field set on a warehouse applies to every shelf
 * inside it, so the definitions are the form's own — computeFieldDefinitions
 * over the same location and category — and an answer typed into the form
 * reads back here under the label it was asked by.
 */
function FieldAnswers({
  item,
  storage,
  category,
}: {
  item: Item;
  storage: StorageLocationSummary | undefined;
  category: CategoryDTO | undefined;
}) {
  const { t } = useTranslation(["items", "common"]);
  const tDyn = makeTDynamic(t);
  const fields = computeFieldDefinitions({
    selectedCategory: category,
    selectedStorage: storage,
    uomCategoryName: null,
  }).filter((f) => f.is_custom && f.visible !== false);
  return (
    <>
      {fields.map((field) => (
        <Field key={field.key} label={getLabel(field, tDyn)}>
          {answerText(field, item.metadata?.[field.key], [
            t("items:fieldOptions.yes"),
            t("items:fieldOptions.no"),
          ])}
        </Field>
      ))}
    </>
  );
}

/**
 * The product's label code, with the way to take that label off again. A
 * label put on the wrong product is put right where it is seen: freeing it
 * leaves the product as it is.
 */
function LabelCodeField({ item }: { item: Item }) {
  const { t } = useTranslation(["items", "labels"]);
  const canWrite = useCanWrite("items");
  const { freeLabel, isFreeing, confirmDialogProps } = useFreeLabel();
  const code = item.label_code;
  return (
    <Field label={t("items:detail.labelCode")}>
      {code ? (
        <span className="inline-flex flex-wrap items-center gap-2">
          {code}
          {canWrite && (
            <Button
              size="content"
              variant="ghost"
              className="px-2 py-1 text-xs"
              disabled={isFreeing}
              aria-label={t("labels:actions.freeLabelNamed", { code })}
              onClick={() => void freeLabel(code, item.name)}
            >
              {t("labels:actions.freeLabel")}
            </Button>
          )}
          <ConfirmDialog {...confirmDialogProps} />
        </span>
      ) : null}
    </Field>
  );
}

/**
 * Everything the record says about itself, in one place.
 *
 * The action sheet over the list answers "what can I do with this"; this
 * answers "what is this". Two decisions the first draft got wrong and this
 * one does not: the name is not repeated here, because the page header
 * already carries it, and the fields share one flowing two-column list
 * rather than two fixed cards — a record with four values put three in the
 * left card and left the right one holding a single row.
 *
 * A field the record does not carry is absent rather than empty: a column of
 * blank rows buries the handful that have values.
 */
export default function ItemDetailOverview({
  item,
  storages,
  categories,
}: ItemDetailOverviewProps) {
  const { t } = useTranslation([
    "items",
    "categories",
    "common",
    "locations",
    "inventory",
  ]);
  const enabledModules = useEnabledModulesOptional();
  const money = useMoney();
  const partial = usePartialPackage()(item);
  const showInventoryValue = useShowInventoryValue();

  const storage = storages?.find((s) => s.id === item.location_id);
  const category = categories?.find((c) => c.id === item.category_id);
  const categorySource = category ?? item.category;
  const categoryName = categorySource
    ? categoryLabel(t, categorySource.code, categorySource.name)
    : null;

  // The system moved the record here itself when the last unit left — this
  // row is the only witness on the record's own screen, and the way back
  // (Move to a shelf, then Add) has to be discoverable from it.
  const inVirtualStorage =
    storage !== undefined &&
    isVirtualUsage(storage.usage) &&
    (toAmount(item.quantity) ?? 0) <= 0;

  return (
    <Card className="p-6">
      <dl className="grid grid-cols-1 sm:grid-cols-2 gap-x-10">
        <Field label={t("items:itemBrand")}>{item.brand}</Field>
        <Field label={t("items:itemCategory")}>{categoryName}</Field>
        <Field label={t("items:itemQuantity")}>
          {quantityText(t, item, partial)}
        </Field>
        {/* The row above says where this record is; the shelves say where
            the product is, in every place that holds it and out of which
            batch. Only offered where an organization keeps that record at
            all (ADR-004). */}
        <Field label={t("inventory:stock.whereItLies")}>
          {item.template_id && recordsMovements(enabledModules) ? (
            <Link
              to={`/inventory/stock?template=${item.template_id}`}
              className="text-primary-600 hover:text-primary-700 hover:underline"
            >
              {t("inventory:stock.seeForProduct")}
            </Link>
          ) : null}
        </Field>
        <Field label={t("items:itemStorage")}>
          {storage ? (
            <span className="inline-flex flex-wrap items-center gap-1.5">
              {getStorageLocationPath(storage, item.shelf_location)}
              {isVirtualUsage(storage.usage) && storage.usage && (
                <span className="px-1.5 py-0.5 rounded-md bg-surface-inset text-on-secondary text-[10px] font-medium uppercase tracking-wide">
                  {virtualUsageLabel(t, storage.usage)}
                </span>
              )}
            </span>
          ) : null}
        </Field>
        <Field label={t("items:itemShelfLocation")}>
          {storage ? null : item.shelf_location}
        </Field>
        <Field label={t("items:fields.serial_number")}>
          {item.serial_number}
        </Field>
        <Field label={t("items:fields.barcode")}>{productCode(item)}</Field>
        <Field label="SKU">{itemSku(item)}</Field>
        <LabelCodeField item={item} />
        {/* The purchase price is a stock-value figure; a profile that does
            not show stock value does not show it here either, the way the
            add form already leaves it out on that profile. */}
        <Field label={t("items:fields.purchase_price")}>
          {showInventoryValue && item.purchase_price != null
            ? money(item.purchase_price)
            : null}
        </Field>
        <Field label={t("items:detail.minQuantity")}>
          {item.min_quantity != null
            ? formatQuantityLocalized(t, item.min_quantity, item.uom?.symbol)
            : null}
        </Field>
        <Field label={t("items:detail.removalStrategy")}>
          {removalStrategyText(item)}
        </Field>
        <Field label={t("items:itemWeight")}>
          {/* The weight is converted, not stored, and arrives with the
              scale of the conversion — "1.600" for an item weighing 1.6 kg.
              The number of digits is not a claim about the scale it was
              weighed on. */}
          {item.weight != null
            ? formatQuantityLocalized(t, item.weight, item.weight_unit ?? "kg")
            : null}
        </Field>
        <Field label={t("items:itemExpiryDate")}>
          {effectiveExpiry(item) ? formatDate(effectiveExpiry(item)) : null}
        </Field>
        <Field label={t("items:detail.useBy")}>
          {isOpenedRecord(item) ? <ItemUseBy item={item} /> : null}
        </Field>
        <Field label={t("items:table.freezeDate")}>
          {item.freeze_date ? formatDate(item.freeze_date) : null}
        </Field>
        <Field label={t("items:detail.addedOn")}>
          {item.added_date ? formatDate(item.added_date) : null}
        </Field>
        <FieldAnswers item={item} storage={storage} category={category} />
        <Field label={t("items:detail.description")}>{item.description}</Field>
        {inVirtualStorage && (
          <div className="sm:col-span-2 rounded-xl bg-surface-inset px-4 py-3 text-sm text-on-secondary">
            {t("items:detail.virtualStorageHint")}
          </div>
        )}
      </dl>
    </Card>
  );
}
