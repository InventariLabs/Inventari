import { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Check,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  Pencil,
  Trash2,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { useCanManage } from "@/hooks/useCanWrite";
import { UomSelect } from "@/modules/shared/components/UomSelect";
import {
  useDeleteBomLine,
  useUpdateBomLine,
} from "@/modules/maker/hooks/useRecipes";
import { BomTreeEditor } from "@/modules/maker/components/BomTreeEditor";
import { BatchYieldEditor } from "@/modules/maker/components/BatchYieldEditor";
import { RecipeIngredientForm } from "@/modules/maker/components/RecipeIngredientForm";
import { YieldLossNote } from "@/modules/maker/components/YieldLossNote";
import { RecipeProcessSteps } from "@/modules/maker/components/RecipeProcessSteps";
import { useFlatUoms } from "@/modules/shared/hooks/useUoms";
import { formatQuantityLocalized } from "@/lib/i18nHelpers";
import type { BomLine, MakerRecipe } from "@/modules/maker/types/maker";

interface CompositionTabProps {
  recipe: MakerRecipe;
}

interface EditState {
  lineId: string;
  qty: string;
  yieldLoss: string;
  /** Empty string = keep the line's current unit (legacy line without uom_id). */
  uomId: string;
}

export function CompositionTab({ recipe }: CompositionTabProps) {
  const { t } = useTranslation("maker");
  const { data: uoms = [], isError: unitsFailed } = useFlatUoms();
  // Lines, yield and process steps decide what a production run consumes —
  // the purpose card gives that decision to the manager. The floor reads
  // the composition and runs the orders.
  const canManage = useCanManage("maker");
  const { mutateAsync: updateLine, isPending } = useUpdateBomLine();
  const deleteLine = useDeleteBomLine();
  const [editing, setEditing] = useState<EditState | null>(null);
  const [pendingDelete, setPendingDelete] = useState<BomLine | null>(null);
  const [showTree, setShowTree] = useState(false);

  // Per-recipe lines come from the recipe detail payload — correct for
  // products that share one template across multiple formulas.
  const lines = recipe.lines ?? [];

  const startEdit = (
    lineId: string,
    qty: string,
    yieldLoss: string,
    uomId: string,
    unit: string,
  ) => {
    // A legacy line carries a unit as free text and no id. Reading
    // the id back off the symbol lets the picker show what the line
    // already says instead of an em dash; an unrecognised symbol
    // keeps the line as it was.
    // Without the catalogue that read comes back empty for every legacy line,
    // and the editor would open on a unit that looks unset.
    if (!uomId && unitsFailed) {
      toast.error(t("common:messages.error"));
      return;
    }
    const resolved = uomId || uoms.find((u) => u.symbol === unit)?.id || "";
    setEditing({ lineId, qty, yieldLoss, uomId: resolved });
  };

  const saveEdit = async () => {
    if (!editing) return;
    try {
      await updateLine({
        recipeId: recipe.id,
        lineId: editing.lineId,
        data: {
          qty_per_batch: editing.qty,
          yield_loss_pct: editing.yieldLoss,
          uom_id: editing.uomId === "" ? null : editing.uomId,
        },
      });
      setEditing(null);
      toast.success(t("detail.line.saved"));
    } catch (error) {
      toast.error(extractApiError(error, t("detail.line.saveFailed")));
    }
  };

  async function confirmDelete() {
    if (!pendingDelete) return;
    try {
      await deleteLine.mutateAsync({
        recipeId: recipe.id,
        lineId: pendingDelete.id,
      });
      toast.success(t("composition.ingredientRemoved"));
    } catch (err) {
      toast.error(
        extractApiError(err, t("composition.errors.removeIngredient")),
      );
    } finally {
      setPendingDelete(null);
    }
  }

  return (
    <div className="space-y-4">
      <Card className="p-4 space-y-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium">
              {t("composition.ingredientsTitle")}
            </h3>
            <p className="text-xs text-on-muted mt-0.5">
              {t("composition.perBatchHint")}
            </p>
          </div>
          {canManage && <BatchYieldEditor recipe={recipe} />}
        </div>

        {lines.length === 0 ? (
          /* The empty tab is where the question "what is this screen for?"
             gets asked, and it was the one screen with no answer on it. One
             paragraph, and only while there is nothing else to read. */
          <div
            className="py-6 text-center text-sm text-on-muted space-y-2"
            data-testid="maker-composition-intro"
          >
            <p>{t("composition.emptyLines")}</p>
            <p className="mx-auto max-w-prose">
              {t("composition.introduction")}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {lines.map((line) => {
              const isEditing = editing?.lineId === line.id;
              const thumbnail = line.child_template_image_url ? (
                <img
                  src={line.child_template_image_url}
                  alt=""
                  className="shrink-0 w-8 h-8 rounded object-cover"
                />
              ) : (
                <span className="shrink-0 w-8 h-8 rounded bg-accent/10 flex items-center justify-center">
                  <FlaskConical size={16} className="text-accent" />
                </span>
              );
              return (
                <div
                  key={line.id}
                  className="flex flex-wrap items-center gap-x-2 gap-y-1.5 px-3 py-2 rounded-lg bg-surface-raised/40 border border-border/60"
                >
                  {isEditing ? (
                    <>
                      {thumbnail}
                      <span className="flex-1 min-w-[7rem] truncate text-sm text-on">
                        {line.child_template_name ?? line.child_template_id}
                      </span>
                      <div className="flex basis-full flex-wrap items-center gap-2">
                        <Input
                          wrapperClassName="w-20"
                          value={editing?.qty ?? ""}
                          onChange={(e) =>
                            setEditing((prev) =>
                              prev ? { ...prev, qty: e.target.value } : prev,
                            )
                          }
                          className="h-8 text-sm"
                          aria-label={t("detail.line.qtyLabel")}
                        />
                        <div className="w-24">
                          <UomSelect
                            compact
                            inline
                            value={editing?.uomId || null}
                            onChange={(id) =>
                              setEditing((prev) =>
                                prev ? { ...prev, uomId: id } : prev,
                              )
                            }
                          />
                        </div>
                        <Input
                          wrapperClassName="w-16"
                          value={editing?.yieldLoss ?? ""}
                          onChange={(e) =>
                            setEditing((prev) =>
                              prev
                                ? { ...prev, yieldLoss: e.target.value }
                                : prev,
                            )
                          }
                          className="h-8 text-sm"
                          aria-label={t("detail.line.yieldLabel")}
                        />
                        <span className="text-xs text-on-muted">%</span>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={saveEdit}
                          disabled={isPending}
                          aria-label={t("common:actions.save")}
                        >
                          <Check size={16} className="text-accent-600" />
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setEditing(null)}
                          aria-label={t("common:actions.cancel")}
                        >
                          <X size={16} />
                        </Button>
                      </div>
                    </>
                  ) : (
                    <>
                      {thumbnail}
                      <span className="flex-1 min-w-[7rem] truncate text-sm text-on">
                        {line.child_template_name ?? line.child_template_id}
                      </span>
                      {/* The figures and actions travel as one group: on a
                          320px row they drop under the name together rather
                          than leaving it a few pixels wide. */}
                      <div className="ml-auto flex items-center gap-2">
                        <span className="text-sm font-medium text-on">
                          {formatQuantityLocalized(
                            t,
                            line.qty_per_batch,
                            line.unit,
                          )}
                        </span>
                        <YieldLossNote pct={line.yield_loss_pct} />
                        {canManage && (
                          <>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() =>
                                startEdit(
                                  line.id,
                                  line.qty_per_batch,
                                  line.yield_loss_pct,
                                  line.uom_id ?? "",
                                  line.unit,
                                )
                              }
                              aria-label={t("detail.edit")}
                              className="min-w-11 md:min-w-0"
                            >
                              <Pencil size={14} />
                            </Button>
                            <Button
                              size="sm"
                              variant="ghost"
                              onClick={() => setPendingDelete(line)}
                              aria-label={t("composition.removeIngredient")}
                              data-testid="maker-composition-delete-line"
                              className="min-w-11 md:min-w-0"
                            >
                              <Trash2 size={14} className="text-red-500" />
                            </Button>
                          </>
                        )}
                      </div>
                    </>
                  )}
                </div>
              );
            })}
          </div>
        )}

        {canManage && (
          <RecipeIngredientForm
            recipeId={recipe.id}
            outputTemplateId={recipe.output_template_id}
          />
        )}
      </Card>

      {/* Sub-assemblies: the only view that shows a formula nested inside a
          formula, and the only place a line can be re-parented. It used to
          live on the removed /maker/bom screen — and that sentence stayed a
          comment while the reader was left to open the panel and guess.
          Re-parenting writes the formula, so the whole section is the
          manager's. */}
      {canManage && (
        <div>
          {" "}
          <Button
            size="content"
            type="button"
            variant="ghost"
            onClick={() => setShowTree((v) => !v)}
            className="px-1 min-h-11 md:min-h-0 min-w-11 md:min-w-0 gap-1 text-xs uppercase tracking-widest text-on-muted font-medium hover:text-on hover:bg-transparent active:bg-transparent"
            aria-expanded={showTree}
            aria-describedby="maker-composition-tree-hint"
            data-testid="maker-composition-tree-toggle"
          >
            {showTree ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
            {t("bom.treeToggle")}
          </Button>
          <p
            id="maker-composition-tree-hint"
            className="px-1 mt-1 text-xs text-on-muted max-w-prose"
            data-testid="maker-composition-tree-hint"
          >
            {t("bom.treeHint")}
          </p>
          {showTree && (
            <div className="mt-3">
              <BomTreeEditor templateId={recipe.output_template_id} />
            </div>
          )}
        </div>
      )}

      <RecipeProcessSteps recipe={recipe} />

      <ConfirmDialog
        open={pendingDelete !== null}
        title={t("composition.removeConfirm.title")}
        message={t("composition.removeConfirm.description", {
          name:
            pendingDelete?.child_template_name ??
            pendingDelete?.child_template_id ??
            "",
        })}
        variant="danger"
        confirmLabel={t("composition.removeIngredient")}
        onConfirm={confirmDelete}
        onCancel={() => setPendingDelete(null)}
      />
    </div>
  );
}
