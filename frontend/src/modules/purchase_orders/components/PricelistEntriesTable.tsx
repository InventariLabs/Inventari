import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useMoney } from "@/hooks/useMoney";
import { formatDate } from "@/utils/formatters";
import { AlertTriangle, Coins, Pencil, Plus, Trash2 } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import type { PartnerPricelist } from "../api/pricelist";
import { findDuplicates } from "./pricelistDuplicates";

interface PricelistEntriesTableProps {
  entries: PartnerPricelist[];
  isLoading: boolean;
  onEdit: (entry: PartnerPricelist) => void;
  onDelete: (entry: PartnerPricelist) => void;
  onCreate: () => void;
  /** True drops the create button and the per-row actions — the table
   *  stays, as a list to read. */
  readOnly?: boolean;
  /** Empty product catalog — the add CTA is disabled and says why. */
  catalogEmpty: boolean;
}

/** What names a row when a screen reader reaches its actions. */
function rowName(entry: {
  product_name?: string | null;
  product_template_id: string;
}) {
  return entry.product_name || entry.product_template_id;
}

export function PricelistEntriesTable({
  entries,
  isLoading,
  onEdit,
  onDelete,
  onCreate,
  readOnly = false,
  catalogEmpty,
}: PricelistEntriesTableProps) {
  const { t } = useTranslation("purchase_orders");
  const money = useMoney();
  // Rows already in the table can still contradict each other; the API only
  // stops a new one from joining them.
  const duplicates = useMemo(() => findDuplicates(entries), [entries]);

  if (isLoading) {
    return (
      <div className="py-12 text-center text-sm text-on-secondary">
        {t("common:messages.loading")}
      </div>
    );
  }

  if (entries.length === 0) {
    return (
      <EmptyState
        icon={Coins}
        title={t("pricelist.emptyTitle")}
        description={t("pricelist.emptyDescription")}
        primaryAction={
          readOnly ? undefined : (
            <Button
              variant="primary"
              leftIcon={<Plus size={16} />}
              onClick={onCreate}
              disabled={catalogEmpty}
            >
              {t("pricelist.addPrice")}
            </Button>
          )
        }
      />
    );
  }

  return (
    <Card>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-inset text-left text-xs uppercase tracking-wide text-on-muted">
              <th scope="col" className="px-4 py-3">
                {t("pricelist.product")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("pricelist.price")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("pricelist.validity")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("pricelist.minQuantity")}
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                {t("pricelist.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {entries.map((entry) => (
              <tr
                key={entry.id}
                className="border-b border-surface-inset/60 last:border-0"
              >
                <td className="px-4 py-3 font-medium text-on">
                  {entry.product_name || entry.product_template_id}
                </td>
                <td className="px-4 py-3">
                  <span
                    className={
                      duplicates.shadowed.has(entry.id)
                        ? "text-on-muted line-through"
                        : undefined
                    }
                  >
                    {money(entry.unit_price, entry.currency)}
                  </span>
                  {/* Two prices for one offer are two answers to one
                      question. Which of them an order reads was invisible. */}
                  {duplicates.effective.has(entry.id) && (
                    <Badge variant="warning" className="ml-2 gap-1">
                      <AlertTriangle size={10} aria-hidden />
                      {t("pricelist.duplicateEffective")}
                    </Badge>
                  )}
                  {duplicates.shadowed.has(entry.id) && (
                    <span className="ml-2 text-xs text-on-muted">
                      {t("pricelist.duplicateShadowed")}
                    </span>
                  )}
                </td>
                <td className="px-4 py-3 text-on-secondary">
                  {formatDate(entry.valid_from)}
                  {entry.valid_to
                    ? ` → ${formatDate(entry.valid_to)}`
                    : ` → ${t("common:datePicker.empty")}`}
                </td>
                <td className="px-4 py-3 text-on-secondary">
                  {entry.min_quantity ?? "—"}
                </td>
                <td className="px-4 py-3">
                  {/* Icon-only, so each carries its words as an
                      `aria-label` and a tooltip — and the label names the
                      product, because nineteen rows of "Edit" and "Delete"
                      are thirty-eight identical names in a row (§11.4). */}
                  {!readOnly && (
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="iconSm"
                        aria-label={`${t("common:actions.edit")} ${rowName(entry)}`}
                        title={t("common:actions.edit")}
                        onClick={() => onEdit(entry)}
                      >
                        <Pencil size={14} />
                      </Button>
                      <Button
                        variant="ghostDanger"
                        size="iconSm"
                        aria-label={`${t("common:actions.delete")} ${rowName(entry)}`}
                        title={t("common:actions.delete")}
                        onClick={() => onDelete(entry)}
                      >
                        <Trash2 size={14} />
                      </Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
