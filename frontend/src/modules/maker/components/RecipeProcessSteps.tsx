import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plus, Trash2, X } from "lucide-react";
import { toast } from "sonner";
import { extractApiError } from "@/lib/errors";
import { Card } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Textarea } from "@/components/ui/Textarea";
import { useCanManage } from "@/hooks/useCanWrite";
import { useUpdateMakerRecipe } from "@/modules/maker/hooks/useRecipes";
import type { MakerRecipe } from "@/modules/maker/types/maker";

interface RecipeProcessStepsProps {
  recipe: MakerRecipe;
}

/**
 * Ordered how-to steps for a recipe.
 *
 * The edit affordance is a labelled button, not a bare pencil icon: the
 * section used to look read-only, so nobody found the only way to write
 * the process down.
 */
export function RecipeProcessSteps({ recipe }: RecipeProcessStepsProps) {
  const { t } = useTranslation("maker");
  const updateRecipe = useUpdateMakerRecipe();
  // Steps are part of the formula, and the formula decides what production
  // consumes — writing them belongs to maker:manage. Reading them stays
  // with everybody.
  const canManage = useCanManage("maker");
  // null = not editing; otherwise the draft step list.
  const [draft, setDraft] = useState<string[] | null>(null);
  const [newStep, setNewStep] = useState("");

  const steps = recipe.process_steps ?? [];

  async function save() {
    if (draft === null) return;
    // A step edited down to nothing is a deletion the operator started and
    // did not finish — saving a blank line would show as an empty numbered
    // row forever.
    const cleaned = draft.map((step) => step.trim()).filter(Boolean);
    try {
      await updateRecipe.mutateAsync({
        recipeId: recipe.id,
        data: { process_steps: cleaned },
      });
      setDraft(null);
      setNewStep("");
      toast.success(t("detail.processStepsSaved"));
    } catch (err) {
      toast.error(extractApiError(err, t("detail.processStepsSaveFailed")));
    }
  }

  function addStep() {
    if (draft === null || newStep.trim() === "") return;
    setDraft([...draft, newStep.trim()]);
    setNewStep("");
  }

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-xs uppercase tracking-widest text-on-muted font-medium">
          {t("detail.processSteps")}
        </h3>
        {canManage &&
          (draft === null ? (
            <Button
              size="sm"
              variant="outline"
              onClick={() => setDraft(steps)}
              leftIcon={
                steps.length === 0 ? <Plus size={14} /> : <Pencil size={14} />
              }
              data-testid="maker-steps-edit"
            >
              {steps.length === 0
                ? t("detail.processStepsAddFirst")
                : t("detail.processStepsEdit")}
            </Button>
          ) : (
            <div className="flex items-center gap-1.5">
              <Button
                size="sm"
                variant="outline"
                onClick={save}
                disabled={updateRecipe.isPending}
                data-testid="maker-steps-save"
              >
                {t("detail.save")}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => {
                  setDraft(null);
                  setNewStep("");
                }}
                aria-label={t("common:actions.cancel")}
              >
                <X size={16} />
              </Button>
            </div>
          ))}
      </div>

      {draft === null ? (
        steps.length === 0 ? (
          <p className="text-sm text-on-muted">
            {t("detail.processStepsEmpty")}
          </p>
        ) : (
          <ol className="space-y-1.5">
            {steps.map((step, idx) => (
              <li key={idx} className="flex gap-2 text-sm text-on">
                <span className="text-on-muted font-medium w-5 flex-shrink-0">
                  {idx + 1}.
                </span>
                <span className="whitespace-pre-wrap">{step}</span>
              </li>
            ))}
          </ol>
        )
      ) : (
        <div className="space-y-2">
          {draft.map((step, idx) => (
            <div
              key={idx}
              className="flex items-start gap-2 px-3 py-2 rounded-lg bg-surface-raised/40 border border-border/60"
            >
              <span className="text-on-muted font-medium w-5 flex-shrink-0 text-sm pt-2.5">
                {idx + 1}.
              </span>
              {/* Editable in place. The row used to be read-only text with a
                  bin beside it, so fixing a typo in a multi-line instruction
                  meant deleting it and typing the whole thing again. */}
              <Textarea
                value={step}
                onChange={(e) =>
                  setDraft(
                    draft.map((s, i) => (i === idx ? e.target.value : s)),
                  )
                }
                rows={2}
                wrapperClassName="flex-1 min-w-0"
                className="text-sm min-h-16 resize-y"
                aria-label={t("detail.processStepsEditStep", {
                  number: idx + 1,
                })}
                data-testid={`maker-steps-edit-${idx}`}
              />
              {/* ui-pattern: destructive-as-neutral — the list being edited
                  is a draft in local state; nothing leaves the recipe until
                  the whole set is saved */}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setDraft(draft.filter((_, i) => i !== idx))}
                aria-label={t("common:actions.delete")}
              >
                <Trash2 size={14} className="text-red-500" />
              </Button>
            </div>
          ))}
          <div className="flex items-end gap-2 pt-1">
            {/* A step is an instruction, not a label — it wraps, and Enter
                inside it means a new line. Ctrl/⌘+Enter adds the step, so the
                keyboard shortcut the single-line field had is not lost. */}
            <Textarea
              value={newStep}
              onChange={(e) => setNewStep(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
                  e.preventDefault();
                  addStep();
                }
              }}
              rows={2}
              placeholder={t("detail.processStepsAddPlaceholder")}
              wrapperClassName="flex-1"
              className="text-sm min-h-16 resize-y"
              aria-label={t("detail.processStepsAdd")}
              data-testid="maker-steps-input"
            />
            <Button
              size="sm"
              variant="outline"
              onClick={addStep}
              disabled={newStep.trim() === ""}
              leftIcon={<Plus size={14} />}
              className="shrink-0"
            >
              {t("detail.processStepsAdd")}
            </Button>
          </div>
        </div>
      )}
    </Card>
  );
}
