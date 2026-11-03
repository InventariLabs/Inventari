import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import type { ReorderRule, ReplenishmentAlert } from "../api/reorder-rules";
import { formatQuantityValue } from "@/utils/formatters";
import { useMediaQuery } from "@/hooks/useMediaQuery";

interface ReorderRulesTableProps {
  rules: ReorderRule[];
  isLoading: boolean;
  alertByRule: Map<string, ReplenishmentAlert>;
  locationName: (id: string) => string;
  partnerName: (id: string | null | undefined) => string;
  onEdit: (rule: ReorderRule) => void;
  onDelete: (rule: ReorderRule) => void;
  /** True when a search or a location filter is what emptied the list. */
  isFiltered: boolean;
  onCreate: () => void;
  /** True drops the create button and the per-row actions — the table
   *  stays, as a list to read. */
  readOnly?: boolean;
  /** Empty product catalog — the add CTA is disabled and says why. */
  catalogEmpty: boolean;
}

/** What names a row when a screen reader reaches its actions. */
function rowName(rule: {
  product_name?: string | null;
  product_template_id: string;
}) {
  return rule.product_name || rule.product_template_id;
}

export function ReorderRulesTable({
  rules,
  isLoading,
  alertByRule,
  locationName,
  partnerName,
  onEdit,
  onDelete,
  isFiltered,
  onCreate,
  readOnly = false,
  catalogEmpty,
}: ReorderRulesTableProps) {
  const { t } = useTranslation("purchase_orders");
  const isPhone = useMediaQuery("(max-width: 767px)");

  if (isLoading) {
    return (
      <div className="py-12 text-center text-sm text-on-secondary">
        {t("common:messages.loading")}
      </div>
    );
  }

  if (rules.length === 0) {
    // A sentence in the middle of an empty page told the reader to add a rule
    // and gave them nothing to add it with — and said the same thing when it
    // was a filter, not an empty account, that hid every row.
    return isFiltered ? (
      <EmptyState
        icon={Search}
        title={t("reorderRules.emptyFilteredTitle")}
        description={t("reorderRules.emptyFilteredDescription")}
      />
    ) : (
      <EmptyState
        icon={RefreshCw}
        title={t("reorderRules.emptyTitle")}
        description={t("reorderRules.emptyDescription")}
        primaryAction={
          readOnly ? undefined : (
            <Button
              variant="primary"
              leftIcon={<Plus size={16} />}
              onClick={onCreate}
              disabled={catalogEmpty}
            >
              {t("reorderRules.addRule")}
            </Button>
          )
        }
      />
    );
  }

  const actions = (rule: ReorderRule) => (
    <div className="flex justify-end gap-1">
      <Button
        variant="ghost"
        size="iconSm"
        aria-label={`${t("common:actions.edit")} ${rowName(rule)}`}
        title={t("common:actions.edit")}
        onClick={() => onEdit(rule)}
      >
        <Pencil size={14} />
      </Button>
      <Button
        variant="ghostDanger"
        size="iconSm"
        aria-label={`${t("common:actions.delete")} ${rowName(rule)}`}
        title={t("common:actions.delete")}
        onClick={() => onDelete(rule)}
      >
        <Trash2 size={14} />
      </Button>
    </div>
  );

  // A phone gets one card per rule: the seven columns of the table pushed
  // safety stock, the supplier and the edit and delete buttons off the right
  // edge, announced only by a scrollbar.
  if (isPhone) {
    return (
      <Card>
        <CardContent className="p-0">
          <ul className="divide-y divide-surface-inset/60">
            {rules.map((rule) => {
              const alert = alertByRule.get(rule.id);
              return (
                <li key={rule.id} className="flex items-start gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1 space-y-1">
                    <p className="text-sm font-medium text-on">
                      {rowName(rule)}
                      {alert && (
                        <span className="ml-2 inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                          <AlertTriangle size={10} />
                          {t("reorderRules.low")}
                        </span>
                      )}
                    </p>
                    <p className="text-xs text-on-secondary">
                      {locationName(rule.location_id)}
                    </p>
                    <dl className="grid grid-cols-3 gap-2 text-xs">
                      <div>
                        <dt className="text-on-muted">
                          {t("reorderRules.min")}
                        </dt>
                        <dd className="text-on">
                          {formatQuantityValue(rule.min_quantity)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-on-muted">
                          {t("reorderRules.max")}
                        </dt>
                        <dd className="text-on">
                          {formatQuantityValue(rule.max_quantity)}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-on-muted">
                          {t("reorderRules.safety")}
                        </dt>
                        <dd className="text-on">
                          {formatQuantityValue(rule.safety_stock)}
                        </dd>
                      </div>
                    </dl>
                    <p className="text-xs text-on-secondary">
                      {t("reorderRules.preferredPartner")}:{" "}
                      {partnerName(rule.preferred_partner_id)}
                    </p>
                  </div>
                  {!readOnly && <div className="shrink-0">{actions(rule)}</div>}
                </li>
              );
            })}
          </ul>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-surface-inset text-left text-xs uppercase tracking-wide text-on-muted">
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.product")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.location")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.min")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.max")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.safety")}
              </th>
              <th scope="col" className="px-4 py-3">
                {t("reorderRules.preferredPartner")}
              </th>
              <th scope="col" className="px-4 py-3 text-right">
                {t("reorderRules.actions")}
              </th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const alert = alertByRule.get(rule.id);
              return (
                <tr
                  key={rule.id}
                  className="border-b border-surface-inset/60 last:border-0"
                >
                  <td className="px-4 py-3 font-medium text-on">
                    {rule.product_name || rule.product_template_id}
                    {alert && (
                      <span className="ml-2 inline-flex items-center gap-1 rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-medium text-amber-800">
                        <AlertTriangle size={10} />
                        {t("reorderRules.low")}
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {locationName(rule.location_id)}
                  </td>
                  <td className="px-4 py-3">
                    {formatQuantityValue(rule.min_quantity)}
                  </td>
                  <td className="px-4 py-3">
                    {formatQuantityValue(rule.max_quantity)}
                  </td>
                  <td className="px-4 py-3">
                    {formatQuantityValue(rule.safety_stock)}
                  </td>
                  <td className="px-4 py-3">
                    {partnerName(rule.preferred_partner_id)}
                  </td>
                  <td className="px-4 py-3">
                    {/* Icon-only, so each carries its words as an
                        `aria-label` and a tooltip — and the label names the
                        product the rule is about, so one row can be told
                        from the next (§11.4). */}
                    {!readOnly && actions(rule)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}
