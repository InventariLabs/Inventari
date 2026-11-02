import { Camera } from "lucide-react";
import { Button } from "@/components/ui/Button";
import NutritionScanner from "./NutritionScanner";
import type { Item } from "@/types";

interface NutritionEmptyStateProps {
  item: Item;
  showScanner: boolean;
  /**
   * Whether the form for typing the values in is rendered below. A product
   * with no template has no place to save them, and then the camera really is
   * the only route — the copy has to say which of the two it is.
   */
  hasManualEntry: boolean;
  /**
   * Whether the vision module is enabled. Where it is off there is no camera
   * route, so the button hides and the copy stops mentioning it.
   */
  visionEnabled: boolean;
  onToggleScanner: () => void;
  onCloseScanner: () => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function NutritionEmptyState({
  item,
  showScanner,
  hasManualEntry,
  visionEnabled,
  onToggleScanner,
  onCloseScanner,
  t,
}: NutritionEmptyStateProps) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-surface p-4">
      <div className="flex items-center justify-between">
        <div>
          <p className="text-xs font-medium text-on-secondary">
            {t("nutrition:title")}
          </p>
          {/* Static calls, not a variable key: the i18n gate reads the call
              sites, and the copy has to say which routes exist (camera,
              manual, neither). */}
          <p className="text-xs text-on-muted mt-0.5">
            {hasManualEntry
              ? visionEnabled
                ? t("nutrition:noDataRoutes")
                : t("nutrition:noDataManual")
              : visionEnabled
                ? t("nutrition:noData")
                : t("nutrition:noDataNone")}
          </p>
        </div>
        {visionEnabled && (
          <Button
            size="content"
            type="button"
            variant="outline"
            onClick={onToggleScanner}
            className="ml-3 shrink-0 gap-1.5 rounded-xl border px-3 py-2 text-xs font-medium text-on-secondary shadow-sm hover:border-primary-400 hover:text-primary-600 active:scale-95"
          >
            <Camera size={14} />
            <span>{t("nutrition:scanTable")}</span>
          </Button>
        )}
      </div>
      {showScanner && (
        <NutritionScanner
          itemId={item.id}
          templateId={item.template_id ?? undefined}
          onClose={onCloseScanner}
          onSuccess={() => {}}
        />
      )}
    </div>
  );
}
