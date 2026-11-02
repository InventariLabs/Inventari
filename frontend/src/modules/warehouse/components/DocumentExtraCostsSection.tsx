/**
 * Freight, duty and insurance on a receipt — and what they do to the price.
 *
 * The point of the section is the last column: a person has to see that the
 * unit cost becomes 12.00 instead of 10.00 *before* they post. Afterwards
 * the answer is a refusal, because the goods may already have left and
 * spreading the invoice over what remains needs a general ledger this
 * product deliberately does not have.
 */
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useMoney } from "@/hooks/useMoney";
import { extractApiError } from "@/lib/errors";
import {
  useAddExtraCost,
  useExtraCosts,
  useRemoveExtraCost,
} from "@/modules/warehouse/hooks/useExtraCosts";
import type {
  ExtraCostAllocation,
  ExtraCostKind,
} from "@/modules/warehouse/api/extraCosts";

const KINDS: ExtraCostKind[] = ["freight", "duty", "insurance", "other"];
const METHODS: ExtraCostAllocation[] = ["value", "quantity", "weight"];

export function DocumentExtraCostsSection({
  documentId,
}: {
  documentId: string;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const money = useMoney();
  const { data } = useExtraCosts(documentId);
  const add = useAddExtraCost(documentId);
  const remove = useRemoveExtraCost(documentId);

  const [kind, setKind] = useState<ExtraCostKind>("freight");
  const [amount, setAmount] = useState("");
  const [method, setMethod] = useState<ExtraCostAllocation>("value");

  if (!data) return null;
  // Nothing to say on a posted receipt that never carried a cost: the
  // section would be a form nobody can use over a list with no rows.
  if (!data.editable && data.costs.length === 0) return null;

  const submit = () => {
    const value = amount.trim();
    if (!value) return;
    add.mutate(
      { kind, amount: value, allocation_method: method },
      {
        onSuccess: () => setAmount(""),
        onError: (error) =>
          toast.error(
            extractApiError(error, t("warehouse:extraCosts.addFailed")),
          ),
      },
    );
  };

  return (
    <Card className="p-4 sm:p-5 space-y-4">
      <div>
        <h2 className="text-lg font-semibold text-on">
          {t("warehouse:extraCosts.title")}
        </h2>
        <p className="text-sm text-on-secondary mt-1">
          {t("warehouse:extraCosts.subtitle")}
        </p>
      </div>

      {data.costs.length > 0 && (
        <ul className="divide-y divide-border border border-border rounded-xl overflow-hidden">
          {data.costs.map((cost) => (
            <li
              key={cost.id}
              className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm"
            >
              <span className="text-on">
                {t(`warehouse:extraCosts.kind.${cost.kind}`, {
                  defaultValue: cost.kind,
                })}
                <span className="text-on-muted">
                  {" · "}
                  {t(`warehouse:extraCosts.method.${cost.allocation_method}`, {
                    defaultValue: cost.allocation_method,
                  })}
                </span>
              </span>
              <span className="flex items-center gap-3">
                <span className="tabular-nums text-on">
                  {money(Number(cost.amount))}
                </span>
                {data.editable && (
                  <Button
                    variant="ghostDanger"
                    size="icon"
                    aria-label={t("warehouse:extraCosts.removeLabel")}
                    onClick={() => remove.mutate(cost.id)}
                  >
                    <Trash2 size={16} />
                  </Button>
                )}
              </span>
            </li>
          ))}
        </ul>
      )}

      {data.editable && (
        <div className="flex flex-wrap items-end gap-3">
          <NativeSelect
            label={t("warehouse:extraCosts.kindLabel")}
            wrapperClassName="w-full sm:w-40"
            value={kind}
            onChange={(event) => setKind(event.target.value as ExtraCostKind)}
          >
            {KINDS.map((value) => (
              <option key={value} value={value}>
                {t(`warehouse:extraCosts.kind.${value}`)}
              </option>
            ))}
          </NativeSelect>
          <Input
            label={t("warehouse:extraCosts.amountLabel")}
            wrapperClassName="w-full sm:w-32"
            inputMode="decimal"
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
          />
          <NativeSelect
            label={t("warehouse:extraCosts.methodLabel")}
            wrapperClassName="w-full sm:w-44"
            value={method}
            onChange={(event) =>
              setMethod(event.target.value as ExtraCostAllocation)
            }
          >
            {METHODS.map((value) => (
              <option key={value} value={value}>
                {t(`warehouse:extraCosts.method.${value}`)}
              </option>
            ))}
          </NativeSelect>
          <Button
            leftIcon={<Plus size={16} />}
            onClick={submit}
            isLoading={add.isPending}
            disabled={!amount.trim()}
          >
            {t("common:actions.add")}
          </Button>
        </div>
      )}

      {data.fell_back.length > 0 && (
        // Value allocation needs values and weight allocation needs weights;
        // a share of a total of zero is a division by zero, not a cost.
        <p className="text-xs text-on-muted">
          {t("warehouse:extraCosts.fellBack")}
        </p>
      )}

      {data.lines.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-left border-collapse text-sm">
            <thead>
              <tr className="border-b border-border text-xs font-medium text-on-secondary uppercase tracking-wider">
                <th scope="col" className="py-2 pr-3">
                  {t("warehouse:extraCosts.columns.line")}
                </th>
                <th scope="col" className="py-2 px-3 text-right">
                  {t("warehouse:extraCosts.columns.unitPrice")}
                </th>
                <th scope="col" className="py-2 px-3 text-right">
                  {t("warehouse:extraCosts.columns.share")}
                </th>
                <th scope="col" className="py-2 pl-3 text-right">
                  {t("warehouse:extraCosts.columns.unitCostAfter")}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.lines.map((line) => (
                <tr
                  key={line.line_id}
                  className="border-b border-border last:border-0"
                >
                  <td className="py-2 pr-3 text-on">
                    {line.product_name ?? "—"}
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums text-on-secondary">
                    {line.unit_price != null
                      ? money(Number(line.unit_price))
                      : "—"}
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums text-on-secondary">
                    {Number(line.surcharge) > 0
                      ? money(Number(line.surcharge))
                      : "—"}
                  </td>
                  <td className="py-2 pl-3 text-right tabular-nums font-medium text-on">
                    {line.unit_cost_after != null
                      ? money(Number(line.unit_cost_after))
                      : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}
