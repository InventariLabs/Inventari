import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { formatMoney } from "@/utils/formatters";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import {
  useAddCostLine,
  useUpdateCostLine,
  useDeleteCostLine,
} from "@/modules/maker/hooks/useRecipes";
import type {
  RecipeCostLine,
  RecipeCostLineKind,
} from "@/modules/maker/types/maker";

interface CostLinesEditorProps {
  recipeId: string;
  lines: RecipeCostLine[];
}

interface DraftLine {
  /** null = new line, otherwise the id of the line being edited. */
  id: string | null;
  kind: RecipeCostLineKind;
  label: string;
  amount: string;
}

const KINDS: RecipeCostLineKind[] = ["LABOR", "PACKAGING", "OVERHEAD", "OTHER"];

const KIND_BADGE: Record<string, "info" | "secondary" | "warning" | "outline"> =
  {
    LABOR: "info",
    PACKAGING: "secondary",
    OVERHEAD: "warning",
    OTHER: "outline",
  };

const EMPTY_DRAFT: DraftLine = {
  id: null,
  kind: "LABOR",
  label: "",
  amount: "",
};

export function CostLinesEditor({ recipeId, lines }: CostLinesEditorProps) {
  const { t, i18n } = useTranslation("maker");
  const currency = useOrganizationCurrency();
  const { mutateAsync: addLine } = useAddCostLine();
  const { mutateAsync: updateLine } = useUpdateCostLine();
  const { mutate: deleteLine } = useDeleteCostLine();
  const [draft, setDraft] = useState<DraftLine | null>(null);
  const [pendingDelete, setPendingDelete] = useState<RecipeCostLine | null>(
    null,
  );

  // The sum lives beside the lines it sums: the tab above used to repeat
  // this section's heading on a summary card of its own, so the reader met
  // the same label and the same figure twice on one screen. The heading
  // already says "/ batch", so the sum does not repeat the unit; and one
  // line is its own sum, so the figure is not printed a second time.
  const totalFixed = lines.reduce((sum, line) => sum + Number(line.amount), 0);

  const draftValid =
    draft !== null &&
    draft.label.trim().length > 0 &&
    draft.amount.trim() !== "" &&
    !Number.isNaN(Number(draft.amount));

  async function saveDraft() {
    if (!draft || !draftValid) return;
    const payload = {
      kind: draft.kind,
      label: draft.label.trim(),
      amount: draft.amount.trim(),
    };
    try {
      if (draft.id === null) {
        await addLine({ recipeId, data: payload });
      } else {
        await updateLine({ recipeId, lineId: draft.id, data: payload });
      }
      setDraft(null);
      toast.success(t("detail.cost.lineSaved"));
    } catch (err) {
      toast.error(
        extractApiError(
          err,
          t("detail.cost.lineSaveFailed", {
            defaultValue: "Failed to save cost line",
          }),
        ),
      );
    }
  }

  function confirmDelete() {
    if (!pendingDelete) return;
    deleteLine(
      { recipeId, lineId: pendingDelete.id },
      {
        onSuccess: () => {
          toast.success(t("detail.cost.lineDeleted"));
          setPendingDelete(null);
        },
        onError: (err) => {
          toast.error(
            extractApiError(
              err,
              t("detail.cost.lineDeleteFailed", {
                defaultValue: "Failed to delete cost line",
              }),
            ),
          );
          setPendingDelete(null);
        },
      },
    );
  }

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium">
          {t("detail.cost.fixedCosts")}
        </h3>
        <div className="flex items-center gap-2 sm:gap-3">
          {lines.length > 1 && (
            <p className="text-sm font-medium text-on tabular-nums">
              {formatMoney(totalFixed, currency, i18n.language)}
            </p>
          )}
          {draft === null && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDraft({ ...EMPTY_DRAFT })}
              leftIcon={<Plus size={14} />}
              data-testid="maker-cost-line-add"
            >
              {t("detail.cost.addLine")}
            </Button>
          )}
        </div>
      </div>

      {lines.length === 0 && draft === null ? (
        <p className="text-sm text-on-muted">{t("detail.cost.noFixed")}</p>
      ) : (
        <div className="space-y-2">
          {lines.map((line) => {
            return (
              <div
                key={line.id}
                className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 py-2 rounded-lg bg-surface-raised/40 border border-border/60"
              >
                <Badge variant={KIND_BADGE[line.kind] ?? "secondary"}>
                  {t(`detail.cost.kind.${line.kind}`, {
                    defaultValue: line.kind,
                  })}
                </Badge>
                <span className="flex-1 min-w-[7rem] truncate text-sm text-on">
                  {line.label}
                </span>
                {/* The amount and the actions travel as one group: on a
                    320px row they drop under the label together rather
                    than leaving it a few pixels wide. */}
                <div className="ml-auto flex items-center gap-2">
                  <span className="text-sm font-medium text-on">
                    {formatMoney(line.amount, currency, i18n.language)}
                  </span>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() =>
                      setDraft({
                        id: line.id,
                        kind: line.kind as RecipeCostLineKind,
                        label: line.label,
                        amount: line.amount,
                      })
                    }
                    aria-label={t("detail.edit")}
                  >
                    <Pencil size={14} />
                  </Button>
                  <Button
                    size="sm"
                    variant="ghostDanger"
                    onClick={() => setPendingDelete(line)}
                    aria-label={t("common:actions.delete")}
                  >
                    <Trash2 size={14} />
                  </Button>
                </div>
              </div>
            );
          })}

          {draft && (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-surface-raised/40 border border-accent-200">
              <NativeSelect
                wrapperClassName="w-32"
                value={draft.kind}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    kind: e.target.value as RecipeCostLineKind,
                  })
                }
                className="h-8 text-sm"
                aria-label={t("detail.cost.lineKind")}
                data-testid="maker-cost-line-kind"
              >
                {KINDS.map((kind) => (
                  <option key={kind} value={kind}>
                    {t(`detail.cost.kind.${kind}`)}
                  </option>
                ))}
              </NativeSelect>
              <Input
                wrapperClassName="flex-1 min-w-0"
                value={draft.label}
                onChange={(e) => setDraft({ ...draft, label: e.target.value })}
                className="h-8 text-sm"
                placeholder={t("detail.cost.lineLabelPlaceholder")}
                aria-label={t("detail.cost.lineLabel")}
                data-testid="maker-cost-line-label"
              />
              <Input
                wrapperClassName="w-28"
                type="number"
                step="0.01"
                min="0"
                value={draft.amount}
                onChange={(e) => setDraft({ ...draft, amount: e.target.value })}
                className="h-8 text-sm"
                aria-label={t("detail.cost.lineAmount")}
                // The only money field in the app that did not say which
                // currency it was in — while the line it saves is rendered
                // right above with the organization's, three characters away.
                rightIcon={
                  currency ? (
                    <span className="text-on-muted text-xs">{currency}</span>
                  ) : undefined
                }
                data-testid="maker-cost-line-amount"
              />
              <Button
                size="sm"
                variant="ghost"
                onClick={saveDraft}
                disabled={!draftValid}
                aria-label={t("common:actions.save")}
              >
                <Check size={16} className="text-accent-600" />
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDraft(null)}
                aria-label={t("common:actions.cancel")}
              >
                <X size={16} />
              </Button>
            </div>
          )}
        </div>
      )}

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("detail.cost.deleteConfirm.title")}
        message={t("detail.cost.deleteConfirm.description", {
          label: pendingDelete?.label ?? "",
        })}
        confirmLabel={t("common:actions.delete")}
        cancelLabel={t("common:actions.cancel")}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
        variant="danger"
      />
    </Card>
  );
}
