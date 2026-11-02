import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowDown, ArrowUp, Columns3 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { useLocalStorage } from "@/hooks/useLocalStorage";
import type {
  EquipmentAssetItem,
  EquipmentSortDir,
  EquipmentSortKey,
} from "@/modules/equipment/api/equipment_assets";
import { daysUntil } from "@/utils/helpers";
import { AssetStatusBadge } from "./AssetStatusBadge";
import { fmt, getEquipmentMeta } from "./assetUtils";

const WARRANTY_SOON_DAYS = 30;
const COLUMN_STORAGE_KEY = "equipment:asset-table-columns";

type WarrantyState = "expired" | "expiring" | "active" | "none";

/** Warranty indicator shared with (dashboard alerts). */
export function getWarrantyState(item: EquipmentAssetItem): WarrantyState {
  const raw = getEquipmentMeta(item).warranty_until;
  if (!raw) return "none";
  // A warranty end is a day on the invoice; `daysUntil` reads it as one
  // (local midnight, rounded) instead of as midnight UTC against local
  // midnight, which moved the count by the reader's offset.
  const days = daysUntil(raw);
  if (days === null) return "none";
  if (days < 0) return "expired";
  if (days <= WARRANTY_SOON_DAYS) return "expiring";
  return "active";
}

interface Column {
  key: string;
  label: string;
  sortable?: EquipmentSortKey;
}

const TOGGLEABLE_COLUMNS = [
  "serial",
  "location",
  "assigned_to",
  "warranty",
  "status",
] as const;

const SORTABLE_COLUMNS: EquipmentSortKey[] = [
  "name",
  "warranty_until",
  "location",
];

function SortArrow({
  active,
  dir,
}: {
  active: boolean;
  dir: EquipmentSortDir;
}) {
  if (!active) return null;
  return dir === "asc" ? (
    <ArrowUp size={12} className="inline-block ml-1" aria-hidden="true" />
  ) : (
    <ArrowDown size={12} className="inline-block ml-1" aria-hidden="true" />
  );
}

interface AssetTableProps {
  items: EquipmentAssetItem[];
  /** False drops the selection column — the bulk actions it feeds are gone. */
  selectable?: boolean;
  selectedIds: Set<string>;
  onToggleSelect: (id: string) => void;
  onToggleSelectAll: () => void;
  sort: EquipmentSortKey;
  sortDir: EquipmentSortDir;
  onSortChange: (key: EquipmentSortKey) => void;
  /** Resolved by the page, so one storages query serves every row — a seeded
   *  location reads in the reader's language, not as the install-day literal. */
  locationLabel: (
    locationId: string | null | undefined,
    rawName: string | null | undefined,
  ) => string | null;
}

export function AssetTable({
  items,
  selectable = true,
  selectedIds,
  onToggleSelect,
  onToggleSelectAll,
  sort,
  sortDir,
  onSortChange,
  locationLabel,
}: AssetTableProps) {
  const { t } = useTranslation("equipment");
  const [visible, setVisible] = useLocalStorage<string[]>(COLUMN_STORAGE_KEY, [
    ...TOGGLEABLE_COLUMNS,
  ]);

  const columns: Column[] = [
    { key: "name", label: t("table.columns.name"), sortable: "name" },
    ...(visible.includes("serial")
      ? [{ key: "serial", label: t("table.columns.serial") } satisfies Column]
      : []),
    ...(visible.includes("location")
      ? [
          {
            key: "location",
            label: t("table.columns.location"),
            sortable: "location",
          } satisfies Column,
        ]
      : []),
    ...(visible.includes("assigned_to")
      ? [
          {
            key: "assigned_to",
            label: t("table.columns.assignedTo"),
          } satisfies Column,
        ]
      : []),
    ...(visible.includes("warranty")
      ? [
          {
            key: "warranty",
            label: t("table.columns.warranty"),
            sortable: "warranty_until",
          } satisfies Column,
        ]
      : []),
    ...(visible.includes("status")
      ? [{ key: "status", label: t("table.columns.status") } satisfies Column]
      : []),
  ];

  const allSelected = items.length > 0 && selectedIds.size === items.length;

  const toggleColumn = (key: string) => {
    setVisible((prev) =>
      prev.includes(key) ? prev.filter((k) => k !== key) : [...prev, key],
    );
  };

  const warrantyCell = (item: EquipmentAssetItem) => {
    const state = getWarrantyState(item);
    const raw = getEquipmentMeta(item).warranty_until;
    if (state === "none") {
      return <span className="text-on-muted">—</span>;
    }
    const badgeClass = {
      expired:
        "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/40 dark:text-red-300 dark:border-red-900",
      expiring:
        "bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900",
      active:
        "bg-accent-50 text-accent-700 border-accent-200 dark:bg-accent-900/40 dark:text-accent-200 dark:border-accent-800",
    }[state];
    // Static keys per state — the i18n unused-key gate skips dynamic
    // template literals and would flag these as orphans.
    const labels: Record<Exclude<WarrantyState, "none">, string> = {
      expired: t("table.warranty.expired"),
      expiring: t("table.warranty.expiring"),
      active: t("table.warranty.active"),
    };
    return (
      <span
        className={`inline-flex items-center px-1.5 py-0.5 rounded-md border text-xs font-medium ${badgeClass}`}
        title={raw ? fmt(raw) : undefined}
      >
        {labels[state]}
        <span className="ml-1 text-on-muted">{raw ? fmt(raw) : ""}</span>
      </span>
    );
  };

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center justify-end px-3 py-2 border-b border-border">
        <details className="relative">
          <summary className="inline-flex items-center gap-1.5 text-xs text-on-muted hover:text-on cursor-pointer list-none">
            <Columns3 size={14} aria-hidden="true" />
            {t("table.columns.title")}
          </summary>
          <div className="absolute right-0 z-10 mt-1 w-44 rounded-lg border border-border bg-surface-card shadow-lg p-2 space-y-1">
            {TOGGLEABLE_COLUMNS.map((key) => (
              <label
                key={key}
                className="flex items-center gap-2 text-xs text-on-secondary px-2 py-1.5 rounded hover:bg-surface-muted cursor-pointer"
              >
                <input
                  type="checkbox"
                  checked={visible.includes(key)}
                  onChange={() => toggleColumn(key)}
                  className="rounded border-border"
                />
                {t(`table.columns.${key}`)}
              </label>
            ))}
          </div>
        </details>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm min-w-[640px]">
          <thead>
            <tr className="border-b border-border text-left">
              {selectable && (
                <th className="w-10 px-3 py-2.5">
                  <Checkbox
                    checked={allSelected}
                    onChange={onToggleSelectAll}
                    aria-label={t("actions.select_all")}
                    className="h-6 w-6 text-primary-600 focus:ring-primary-500"
                  />
                </th>
              )}
              {columns.map((col) => (
                <th
                  key={col.key}
                  className="px-3 py-2.5 font-medium text-on-secondary"
                  // Which column the rows are ordered by, and which way. A
                  // screen reader otherwise announces four identical column
                  // buttons with no way to tell which one is in effect.
                  aria-sort={
                    col.sortable && sort === col.sortable
                      ? sortDir === "asc"
                        ? "ascending"
                        : "descending"
                      : undefined
                  }
                >
                  {col.sortable && SORTABLE_COLUMNS.includes(col.sortable) ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="contentSm"
                      onClick={() =>
                        onSortChange(col.sortable as EquipmentSortKey)
                      }
                      className="p-0 uppercase text-xs tracking-wide text-on-secondary hover:text-on"
                      aria-label={t("table.sortBy", { column: col.label })}
                    >
                      {col.label}
                      <SortArrow active={sort === col.sortable} dir={sortDir} />
                    </Button>
                  ) : (
                    <span className="uppercase text-xs tracking-wide">
                      {col.label}
                    </span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {items.map((item) => {
              const meta = getEquipmentMeta(item);
              return (
                <tr
                  key={item.id}
                  className="border-b border-border last:border-0 hover:bg-surface-muted"
                >
                  {selectable && (
                    <td className="px-3 py-2.5">
                      <Checkbox
                        checked={selectedIds.has(item.id)}
                        onChange={() => onToggleSelect(item.id)}
                        aria-label={t("list.select_item", { name: item.name })}
                        className="text-primary-600 focus:ring-primary-500"
                      />
                    </td>
                  )}
                  <td className="px-3 py-2.5 text-sm font-semibold text-on">
                    {/* The row's primary target is a real link, not a
                        click on the row: the asset is reachable by
                        keyboard, the middle button opens it in a new tab,
                        and the accessible name is computed from the content
                        (the asset's name), not pinned to an aria-label,
                        which would silence it. */}
                    <Link
                      to={`/equipment/${item.id}`}
                      // The focus ring is the app's, not Chrome's default
                      // outline — the same token set `<Button>` uses.
                      className="block w-full max-w-[240px] truncate text-left rounded-lg focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background"
                      title={item.name}
                    >
                      {item.name}
                    </Link>
                  </td>
                  {columns.some((c) => c.key === "serial") && (
                    <td className="px-3 py-2.5 text-on-muted font-mono text-xs">
                      {meta.serial_number ?? meta.asset_tag ?? "—"}
                    </td>
                  )}
                  {columns.some((c) => c.key === "location") && (
                    <td className="px-3 py-2.5 text-on-muted">
                      {locationLabel(item.location_id, item.location_name) ??
                        "—"}
                    </td>
                  )}
                  {columns.some((c) => c.key === "assigned_to") && (
                    <td className="px-3 py-2.5 text-on-muted">
                      {/* A place is in the Location column: the list reports
                          the place an asset is checked out to as where it is. */}
                      {(item.holder_kind !== "location" && item.holder_name) ||
                        "—"}
                    </td>
                  )}
                  {columns.some((c) => c.key === "warranty") && (
                    <td className="px-3 py-2.5">{warrantyCell(item)}</td>
                  )}
                  {columns.some((c) => c.key === "status") && (
                    <td className="px-3 py-2.5">
                      <AssetStatusBadge status={meta.status} />
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
