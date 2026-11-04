import { isInVirtualPlace } from "@/modules/shared/lib/storageUsage";
import { memo, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  QrCode,
  Barcode,
  CheckCircle,
  Edit2,
  FileText,
  Trash2,
  Hash,
  Plus,
  TrendingDown,
  Tag,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Checkbox } from "@/components/ui/Checkbox";
import Button from "@/components/ui/Button";
import { Tooltip } from "@/components/ui/Tooltip";
import { categoryLabel } from "@/lib/i18nHelpers";
import {
  badgeQuantity,
  usePartialPackage,
} from "@/modules/shared/hooks/usePartialPackage";
import { partialPackageOfSize } from "@/utils/partialPackage";
import {
  formatDate,
  getStorageLocationPath,
  splitLocationPath,
} from "@/utils/helpers";
import { toAmount } from "@/utils/formatters";
import type { Item, CategoryDTO, StorageLocationSummary } from "@/types";
import { itemSku, productCode } from "@/types";

import ExpiryChip from "./ExpiryChip";

interface ColumnContributorLike {
  key: string;
  render: (item: Item) => React.ReactNode;
}

interface ItemTableRowProps {
  item: Item;
  isSelected: boolean;
  onItemClick: (item: Item) => void;
  onConsume: (itemId: string) => void;
  onAddOne: (itemId: string) => void;
  onEdit: (itemId: string) => void;
  onDelete: (itemId: string) => void;
  onSetThreshold: (item: Item) => void;
  /** Whether to offer the row's actions — all of them write. */
  canWrite?: boolean;
  /** Whether the row may offer Delete — `items:delete`, a narrower key. */
  canDelete?: boolean;
  onToggleSelect: (id: string) => void;
  consumingId: string | null;
  showFreezeDate: boolean;
  showExpiryDate: boolean;
  extraBeforeName: ColumnContributorLike[];
  extraBeforeActions: ColumnContributorLike[];
  storages?: StorageLocationSummary[];
  categories?: CategoryDTO[];
}

/**
 * Where the product sits, written as the whole path.
 *
 * The row used to print `storage.name` alone, so a nested location read as
 * "Shelf A - Top" with no sign of which warehouse it belongs to — and it
 * joined its own segments with `·` while the rest of the product speaks
 * `LOCATION_PATH_SEPARATOR` (§14.2: one concept, one word — and one glyph).
 * `getStorageLocationPath` is the shared answer: the backend's `full_path`
 * when the record carries one, the ancestor walk when it does not.
 */
function getStoragePath(
  storageId: string | null | undefined,
  shelfLocation: string | null | undefined,
  storages: StorageLocationSummary[] | undefined,
  t: ReturnType<typeof useTranslation>["t"],
): string {
  const unknown = String(
    t("unknown", { ns: "common", defaultValue: "Unknown" }),
  );
  if (!storageId) return unknown;
  // The places have not arrived yet: a record is not "Unknown" for as long as
  // the list that names it is still on its way.
  if (!storages) return "";
  const storage = storages.find((s) => s.id === storageId);
  if (!storage) return unknown;
  return getStorageLocationPath(storage, shelfLocation, undefined, storages);
}

function getCategoryName(
  categoryId: string | null | undefined,
  categories: CategoryDTO[] | undefined,
  t: ReturnType<typeof useTranslation>["t"],
): string | null {
  if (!categoryId) return null;
  const category = categories?.find((c) => c.id === categoryId);
  if (!category) return null;
  return categoryLabel(t, category.code, category.name);
}

/** Where the record stands; a used-up one has no shelf to name. */
function ItemLocation({
  item,
  storages,
}: {
  item: Item;
  storages: StorageLocationSummary[] | undefined;
}) {
  const { t } = useTranslation(["items", "common"]);
  if (isInVirtualPlace(item.location_id, storages)) {
    return (
      <span className="text-sm text-on-muted">{t("items:usedUpPlace")}</span>
    );
  }
  return (
    <LocationLink
      locationId={item.location_id}
      path={getStoragePath(item.location_id, item.shelf_location, storages, t)}
    />
  );
}

/** "+1", where a unit can be added: not to a used-up record. */
function AddOneButton({
  item,
  storages,
  label,
  onAddOne,
}: {
  item: Item;
  storages: StorageLocationSummary[] | undefined;
  label: string;
  onAddOne: (itemId: string) => void;
}) {
  if (isInVirtualPlace(item.location_id, storages)) return null;
  return (
    <Button
      size="iconSm"
      variant="ghost"
      onClick={() => onAddOne(item.id)}
      className="relative group/tooltip text-on-muted hover:text-primary-600 hover:bg-primary-50"
      aria-label={label}
    >
      <Plus size={16} />
      <Tooltip label={label} />
    </Button>
  );
}

/** The location cell's link: the leaf of the path first, the road to it behind. */
function LocationLink({
  locationId,
  path,
}: {
  locationId: string | null | undefined;
  path: string;
}) {
  const { leaf, parents } = splitLocationPath(path);
  return (
    <Link
      to={`/inventory/locations/${locationId}`}
      className="block min-w-0 text-sm text-on-secondary underline decoration-border underline-offset-2 hover:text-accent-700 hover:decoration-accent-600 transition-colors"
      title={path}
      aria-label={path}
    >
      <span className="block break-words font-medium">{leaf}</span>
      {parents && (
        <span
          data-testid="item-location-parents"
          className="block truncate text-xs text-on-muted"
        >
          {parents}
        </span>
      )}
    </Link>
  );
}

/**
 * The quantity cell's control. Setting the alert writes the product
 * (items:write), so an account that cannot write reads the quantity and is
 * offered no sheet whose save would answer 403.
 */
function StockAlertTrigger({
  item,
  canWrite,
  onSetThreshold,
  children,
}: {
  item: Item;
  canWrite: boolean;
  onSetThreshold: (item: Item) => void;
  children: ReactNode;
}) {
  const { t } = useTranslation(["items"]);
  if (!canWrite) {
    return (
      <div className="flex items-center justify-end gap-1.5 px-2 py-1">
        {children}
      </div>
    );
  }
  return (
    <Button
      size="content"
      variant="ghost"
      onClick={() => onSetThreshold(item)}
      title={t("setStockAlert")}
      className="justify-end gap-1.5 px-2 py-1 rounded-lg transition-colors relative hover:bg-surface-raised"
    >
      {children}
      <span className="sr-only">
        {t("items:setStockAlertForItem", { name: item.name })}
      </span>
    </Button>
  );
}

/** A single virtualizable item row in the desktop table. */
function ItemTableRowBase({
  item,
  isSelected,
  onItemClick,
  onConsume,
  onAddOne,
  onEdit,
  onDelete,
  onSetThreshold,
  onToggleSelect,
  canWrite = true,
  canDelete,
  consumingId,
  showFreezeDate,
  showExpiryDate,
  extraBeforeName,
  extraBeforeActions,
  storages,
  categories,
}: ItemTableRowProps) {
  const { t } = useTranslation(["items", "categories", "common"]);

  const hasThreshold = item.min_quantity != null;
  // The quantity crosses the wire as a Decimal string; the comparison runs
  // on the number it denotes (TECHNICAL_DECISIONS §18).
  const qty = toAmount(item.quantity) ?? 0;
  const isLow = hasThreshold && qty <= (item.min_quantity ?? 0);
  // Empty when the product records no unit — which is most of them. The row
  // still fills the unit slot, with a mark rather than an invented "pcs".
  const effectiveUnit = item.uom?.symbol ?? "";
  // A partly used package reads in the product's weight or volume unit, not
  // as a fraction of a piece. Only the screen changes; the stored quantity
  // stays in the card's unit.
  const partial = usePartialPackage()(item);
  const badge = badgeQuantity(t, item, partial);

  // The row's icon actions say what they do in one place: these words are
  // the accessible name and the tooltip both, so the two cannot drift.
  const consumeLabel = t("items:actions.consume1unit");
  const addOneLabel = t("items:actions.addOneUnit");
  const editLabel = t("items:actions.edit");
  const detailsLabel = t("items:detail.viewDetails");

  // A real table, not a stack of cards: hairline row dividers via border-b,
  // no per-row boxes. The border lives on the cells because a `<tr>` cannot
  // carry one with the table's `border-separate`.
  const cell = `px-4 py-2 align-middle border-b transition-colors ${
    isSelected
      ? "bg-accent-50/30 border-accent-200"
      : "bg-surface-card border-border group-hover:bg-surface-raised"
  }`;
  const lastCell = `${cell} pr-4`;

  const quantityContent = (
    <>
      {/* Right-aligned digits against a left-aligned unit slot, so the
                numbers form a column. Aligning the pair as one block put the
                digits wherever the unit's width left them: "10 szt." sat far
                left of "8 g", and nothing in the column lined up. */}
      <span className="font-medium text-sm leading-none tabular-nums text-on text-right">
        {badge.number}
      </span>
      {/* The unit slot is always filled, with the symbol or with the
                mark the product uses for a value it does not have.
                Not printing anything was meant to avoid inventing "pcs" for a
                product that records no unit — but 2661 of 3243 products record
                none, so the column was a wall of bare numbers that read as
                complete. "10" with nothing after it does not stop a reader
                assuming pieces; it just moves the invention off the screen and
                into their head. "10 —" says the quantity is known and the unit
                is not, which is the truth. */}
      {/* Lower case, and no `uppercase` to force it. The catalogue
                already writes these correctly — "szt.", "kg", "g", "ml" — and
                the class was overriding good data with bad: unit symbols are
                case-sensitive, so "G" is not a gram and "ML" is not how a
                millilitre is written. Polish abbreviates them lower case
                besides, and shouting them made the unit outweigh the number
                it belongs to.
                The slot has a minimum width so the digits beside it line up
                across rows; a long unit grows its own row rather than being
                cut. */}
      <span
        className="min-w-[2.75rem] text-left text-xs font-medium text-on-muted"
        title={effectiveUnit ? undefined : t("items:stock.noUnitRecorded")}
      >
        {badge.unit || "—"}
      </span>
      {partial && (
        <span className="text-xs text-on-muted whitespace-nowrap">
          {partialPackageOfSize(t, partial)}
        </span>
      )}
      {/* What the button shows (the number, the unit, and for a partly
                used package the full size) leads the name and the purpose
                follows, read but not shown. The button first announced itself
                as "1 PCS." — the title names nothing once there is content —
                and then by an `aria-label` that spelled the shown parts
                mid-sentence, which is not the run of text a voice user sees
                (WCAG 2.5.3). The space collapses between flex items on screen
                and keeps the two parts two words in the name. */}{" "}
    </>
  );

  return (
    <tr data-testid="item-row" className="group">
      {/* Checkbox */}
      <td className={cell}>
        <Checkbox
          checked={isSelected}
          onChange={() => onToggleSelect(item.id)}
          className="w-4 h-4 text-accent-600 focus:ring-accent-500"
          aria-label={t("items:actions.select", {
            defaultValue: "Select {{name}}",
            name: item.name,
          })}
        />
      </td>

      {/* Product Info — the row's primary target is a real button, so the
          product is reachable by keyboard. Its accessible name is computed
          from the content (name, brand, code, SKU, category) rather than
          pinned to an aria-label, which would silence all of it. */}
      <td className={cell}>
        {/* eslint-disable-next-line no-restricted-syntax -- full-width content target with the row's own layout, not a chrome button; Button variants would impose padding/height/rounding */}
        <button
          type="button"
          // The focus ring is the app's, not Chrome's default outline — the
          // same token set `<Button>` uses.
          className="flex w-full items-center gap-4 text-left rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          onClick={() => onItemClick(item)}
        >
          {item.image_url ? (
            <img
              src={item.image_url}
              // Decorative here: the product name sits right next to the
              // thumbnail, and alt text would announce it twice.
              alt=""
              loading="lazy"
              className="w-10 h-10 rounded-lg object-cover border border-border shadow-sm"
            />
          ) : null}
          <div className="min-w-0 max-w-xs">
            <div className="flex items-start gap-2">
              <p
                data-testid="item-name"
                className="text-sm font-semibold text-on group-hover:text-accent-700 transition-colors leading-tight truncate"
                title={item.name}
              >
                {item.name}
              </p>
              {item.brand && (
                <span className="shrink-0 text-[10px] font-medium text-on-secondary uppercase tracking-tight bg-surface-raised px-1.5 py-0.5 rounded mt-0.5">
                  {item.brand}
                </span>
              )}
            </div>
            <div className="flex flex-wrap gap-1.5 mt-1">
              {item.label_code && item.label_code.startsWith("STM-") ? (
                <span className="flex items-center gap-1 font-mono font-semibold text-[10px] text-accent-600 bg-accent-50 px-1.5 py-0.5 rounded border border-accent-100 uppercase tracking-tighter">
                  <QrCode size={10} />
                  {item.label_code}
                </span>
              ) : productCode(item) ? (
                <span className="flex items-center gap-1 font-mono font-semibold text-[10px] text-on-secondary bg-surface-raised px-1.5 py-0.5 rounded border border-border uppercase tracking-tighter">
                  <Barcode size={10} />
                  {productCode(item)}
                </span>
              ) : null}
              {itemSku(item) && (
                <span className="flex items-center gap-1 font-mono font-semibold text-[10px] text-on-secondary bg-surface-raised px-1.5 py-0.5 rounded border border-border uppercase tracking-tighter">
                  <Tag size={10} />
                  {itemSku(item)}
                </span>
              )}
              {item.serial_number && (
                <span
                  className="flex items-center gap-1 font-mono font-semibold text-[10px] text-on-secondary bg-surface-raised px-1.5 py-0.5 rounded border border-border uppercase tracking-tighter"
                  title={t("items:fields.serial_number")}
                >
                  <Hash size={10} />
                  {item.serial_number}
                </span>
              )}
              {getCategoryName(item.category_id, categories, t) && (
                <span className="flex items-center gap-1.5 text-[10px] font-medium text-on-secondary bg-surface-raised px-1.5 py-0.5 rounded uppercase tracking-wider">
                  <span className="w-2 h-2 rounded-full bg-current opacity-50 shrink-0" />
                  {getCategoryName(item.category_id, categories, t)}
                </span>
              )}
            </div>
          </div>
        </button>
      </td>

      {/* Extra columns: position=after-name */}
      {extraBeforeName.map((c) => (
        <td key={c.key} className={cell}>
          {c.render(item)}
        </td>
      ))}

      {/* Location — the name of a place opens the place.
          It used to narrow this list to that storage instead, which made the
          link a no-op exactly where a reader is most likely to press it: on
          the list it had just narrowed, every row names the same storage, so
          the destination was the page already on screen. Narrowing by storage
          is what the filter panel is for. The storage's own page always has
          something to show.

          The leaf comes first and is never cut: a product held in twelve
          records on twelve shelves of one warehouse differs only in its last
          segment, and a one-line path truncated at the end printed twelve
          identical rows. Only the road to the leaf ("Pantry Building › Dry
          Goods") is truncated, on a line of its own, and `title` carries
          what truncation took away.

          Each line is one `block` box with no hole in it: as inline text the
          link wrapped, and the interline gap down the middle of the cell
          swallowed the click a reader aims at its centre. `aria-label` keeps
          the whole path as the link's name. */}
      <td className={cell}>
        <ItemLocation item={item} storages={storages} />
      </td>

      {/* Quantity — the low-stock state says so in a word, exactly like the
 mobile card since. Amber tints and a dashed border
          made "below threshold" and "has a threshold, is fine" one state for
          anyone who does not separate those two hues; the second state is
          a product setting, not list information, and now shows nothing. */}
      <td className={cell}>
        <div className="flex items-center justify-end gap-2">
          <StockAlertTrigger
            item={item}
            canWrite={canWrite}
            onSetThreshold={onSetThreshold}
          >
            {quantityContent}
          </StockAlertTrigger>
          {isLow && (
            <Badge variant="warning" className="gap-1 px-1.5 py-0 shrink-0">
              <TrendingDown size={10} />
              <span>{t("items:stock.lowStock")}</span>
            </Badge>
          )}
        </div>
      </td>

      {/* Freeze Date */}
      {showFreezeDate && (
        <td className={`${cell} text-xs font-medium text-on-secondary`}>
          {item.freeze_date ? (
            formatDate(item.freeze_date, t)
          ) : (
            <span className="opacity-20 text-xl font-light">-</span>
          )}
        </td>
      )}

      {/* Expiry Date */}
      {showExpiryDate && (
        <td className={cell}>
          <ExpiryChip
            item={item}
            fallback={
              <span className="opacity-20 text-xl font-light text-on-muted ml-2">
                -
              </span>
            }
          />
        </td>
      )}

      {/* Extra columns: position=before-actions */}
      {extraBeforeActions.map((c) => (
        <td key={c.key} className={cell}>
          {c.render(item)}
        </td>
      ))}

      {/* Actions — always visible: contrast comes from the colour tokens,
          not from an opacity that reads as "disabled" and never exists on a
 touch screen (UI_GUIDELINES §2.9). */}
      <td className={lastCell}>
        <div className="flex items-center justify-end gap-1">
          {/* The page — history, movements, labels — is a read; a viewer
              reaches it too, so it sits outside the write gate. */}
          <Link
            to={`/inventory/items/${item.id}`}
            aria-label={detailsLabel}
            className="relative group/tooltip inline-flex h-8 w-8 items-center justify-center rounded-lg text-on-muted hover:text-primary-600 hover:bg-primary-50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <FileText size={16} />
            <Tooltip label={detailsLabel} />
          </Link>
          {canWrite && (
            <>
              {/* Each icon-only button carries its words in a tooltip of the
                app's own, on hover and on keyboard focus — `title` answers
                hover only and stacks a second bubble beside this one. The
                tooltip text and the `aria-label` are the same variable, so
                "activate Remove 1 unit" cannot land on a control named
                "Remove" (WCAG 2.5.3). */}
              <Button
                size="iconSm"
                variant="ghost"
                onClick={() => onConsume(item.id)}
                disabled={consumingId === item.id}
                className="relative group/tooltip text-on-muted hover:text-accent-600 hover:bg-accent-50"
                aria-label={consumeLabel}
              >
                {consumingId === item.id ? (
                  <span className="text-[10px] font-medium">...</span>
                ) : (
                  <CheckCircle size={16} />
                )}
                <Tooltip label={consumeLabel} />
              </Button>
              {/* The opposite of the button beside it. "+1" existed only in the
              actions sheet, one click deeper than the action it undoes. */}
              <AddOneButton
                item={item}
                storages={storages}
                label={addOneLabel}
                onAddOne={onAddOne}
              />
              <Button
                size="iconSm"
                variant="ghost"
                onClick={() => onEdit(item.id)}
                className="relative group/tooltip text-on-muted hover:text-primary-600 hover:bg-primary-50"
                aria-label={editLabel}
              >
                <Edit2 size={16} />
                <Tooltip label={editLabel} />
              </Button>
              <DeleteAction
                canDelete={canDelete}
                label={t("items:actions.delete")}
                onClick={() => onDelete(item.id)}
              />
            </>
          )}
        </div>
      </td>
    </tr>
  );
}

/**
 * The row's destructive action, and the line that separates it from the safe
 * ones: flush against a safe action it read as one cluster (§2.13a), and with
 * nothing to separate, the line would point at the edit button. Marked at
 * rest, not only on hover — on touch, pre-tap hover never happens.
 *
 * A reader without `items:delete` gets nothing: the endpoint checks the
 * narrower key, and a dimmed button the API would refuse is still an offer.
 */
function DeleteAction({
  canDelete,
  label,
  onClick,
}: {
  canDelete?: boolean;
  label: string;
  onClick: () => void;
}) {
  if (!canDelete) return null;
  return (
    <>
      <span aria-hidden="true" className="w-px h-5 shrink-0 bg-border mx-1" />
      <Button
        size="iconSm"
        variant="ghostDanger"
        onClick={onClick}
        className="relative group/tooltip"
        aria-label={label}
      >
        <Trash2 size={16} />
        <Tooltip label={label} />
      </Button>
    </>
  );
}

export const ItemTableRow = memo(ItemTableRowBase);
