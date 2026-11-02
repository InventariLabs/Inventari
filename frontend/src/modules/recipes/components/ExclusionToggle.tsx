import { useTranslation } from "react-i18next";
import { Home } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import {
  useShoppingExclusions,
  useCreateShoppingExclusion,
  useDeleteShoppingExclusion,
} from "@/modules/recipes/hooks/useMealPlans";
import { extractApiError } from "@/lib/errors";
import { ExclusionGate } from "./ExclusionGate";

export function ExclusionToggle({
  name,
  templateId,
}: {
  name: string;
  templateId?: string | null;
}) {
  const { t } = useTranslation(["recipes", "common"]);
  // The exclusion is written through `recipes:write`; a reader gets no toggle
  // rather than one that ends in a 403.
  const canWrite = useCanWrite("recipes");
  const {
    data: exclusions = [],
    isError: exclusionsFailed,
    refetch,
  } = useShoppingExclusions();
  const createExclusion = useCreateShoppingExclusion();
  const deleteExclusion = useDeleteShoppingExclusion();

  function normalize(s: string): string {
    return s
      .trim()
      .toLowerCase()
      .normalize("NFD")
      .replace(/[\u0300-\u036f]/g, "")
      .split(/\s+/)
      .sort()
      .join(" ");
  }

  const normalizedName = normalize(name);
  const matching = exclusions.find((e) => e.name_normalized === normalizedName);
  const isExcluded = !!matching;

  function handleToggle() {
    if (isExcluded && matching) {
      deleteExclusion.mutate(matching.id, {
        onSuccess: () => {
          toast.success(t("meal_planner.exclusions_removed"));
        },
        onError: (err) => {
          toast.error(extractApiError(err, t("meal_planner.exclusions_error")));
        },
      });
    } else {
      createExclusion.mutate(
        { name, template_id: templateId ?? undefined },
        {
          onSuccess: () => {
            toast.success(t("meal_planner.exclusions_added"));
          },
          onError: (err: unknown) => {
            const detail =
              err instanceof Error
                ? (err as Error & { response?: { status?: number } }).response
                    ?.status
                : null;
            if (detail === 409) {
              toast.info(t("meal_planner.exclusions_already_exists"));
            } else {
              toast.error(
                extractApiError(err, t("meal_planner.exclusions_error")),
              );
            }
          },
        },
      );
    }
  }

  if (!canWrite) return null;

  return (
    <ExclusionGate failed={exclusionsFailed} onRetry={() => void refetch()}>
      <Button
        size="content"
        type="button"
        variant="ghost"
        onClick={handleToggle}
        className={`px-1.5 py-0.5 rounded-md text-xs font-medium gap-1 shrink-0 ${
          isExcluded
            ? "text-on font-medium bg-primary-50 border-primary-500 hover:bg-primary-50"
            : "text-on-muted hover:text-primary-600 hover:bg-surface-raised"
        }`}
        title={t("meal_planner.exclusions_toggle_tooltip")}
      >
        <Home size={16} fill={isExcluded ? "currentColor" : "none"} />
        {t("meal_planner.exclusions_toggle_label")}
      </Button>
    </ExclusionGate>
  );
}
