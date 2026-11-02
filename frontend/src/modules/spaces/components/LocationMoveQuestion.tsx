import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import type { StorageMoveScope } from "@/lib/api/storages";
import type {
  MoveQuestionProps,
  MoveRelocation,
} from "@/modules/spaces/hooks/useMoveQuestion";

/**
 * A moved location that holds stock: did it physically move?
 *
 * Both answers are always offered. A move to another top-level location — a
 * zone carried to another building — starts on "it physically moved"; a move
 * within one starts on "correcting the layout", the far more common reason to
 * drag a shelf inside its own warehouse. The sentence above each choice says
 * what is about to move before anything is saved.
 */
export function LocationMoveQuestion({
  scopes,
  onAnswer,
  onCancel,
}: MoveQuestionProps) {
  const { t } = useTranslation("locations");
  const [choices, setChoices] = useState<Record<number, MoveRelocation>>({});

  useEffect(() => {
    if (!scopes) return;
    setChoices(
      Object.fromEntries(
        scopes.map((scope) => [
          scope.index,
          scope.warehouse_changes ? "physical" : "correction",
        ]),
      ),
    );
  }, [scopes]);

  return (
    <ConfirmDialog
      open={scopes !== null}
      title={t("moveQuestion.title")}
      message={t("moveQuestion.description")}
      confirmLabel={t("moveQuestion.confirm")}
      onConfirm={() => onAnswer(choices)}
      onCancel={onCancel}
    >
      <div className="space-y-4">
        {(scopes ?? []).map((scope) => (
          <div key={scope.index} className="space-y-2">
            <p className="text-sm text-on">{scopeSentence(t, scope)}</p>
            <ChoiceGroup
              label={t("moveQuestion.choiceLabel", { name: scope.name })}
              layout="grid"
              options={[
                { id: "correction", label: t("moveQuestion.correction") },
                { id: "physical", label: t("moveQuestion.physical") },
              ]}
              value={choices[scope.index] ?? "correction"}
              onChange={(id) =>
                setChoices((prev) => ({
                  ...prev,
                  [scope.index]: id as MoveRelocation,
                }))
              }
            />
          </div>
        ))}
        <p className="text-xs text-on-muted">
          {t("moveQuestion.physicalHint")}
        </p>
      </div>
    </ConfirmDialog>
  );
}

function scopeSentence(
  t: ReturnType<typeof useTranslation>["t"],
  scope: StorageMoveScope,
): string {
  const products = t("moveQuestion.products", { count: scope.products });
  const destination = scope.to_path ?? t("moveQuestion.topLevel");
  if (scope.locations_inside === 0) {
    return t("moveQuestion.scopeNoInside", {
      name: scope.name,
      products,
      destination,
    });
  }
  const inside = t("moveQuestion.locationsInside", {
    count: scope.locations_inside,
  });
  return t("moveQuestion.scope", {
    name: scope.name,
    inside,
    products,
    destination,
  });
}
