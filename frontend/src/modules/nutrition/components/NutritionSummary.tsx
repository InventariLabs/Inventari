import React from "react";
import { useTranslation } from "react-i18next";
import type { SlotDataMap } from "@/lib/moduleRegistry/slotProps";
import { formatQuantityLocale } from "@/utils/formatters";
import CommunityDataNote from "./CommunityDataNote";

type Props = { data?: Partial<SlotDataMap["stock_action_extra"]> };

/**
 * Compact nutrition summary for Quick Action sheets.
 *
 * The values arrive on the scanned product, which is the only thing this slot
 * is handed. It used to look for an `item` first — a field the slot has never
 * carried — so the read that mattered was the second half of a fallback.
 */
const NutritionSummary: React.FC<Props> = ({ data }) => {
  const { t } = useTranslation("nutrition");

  const metadata = (data?.template?.metadata ?? {}) as Record<string, unknown>;
  const nutrition = (metadata.nutrition || {}) as Record<string, unknown>;
  const nutriscore = metadata.nutriscore as string | undefined;

  if (!nutrition.energy_kcal && !metadata.off_enriched) {
    return null;
  }

  const formatVal = (val: unknown) => {
    if (val === undefined || val === null || val === "") return "-";
    const num = typeof val === "string" ? parseFloat(val) : (val as number);
    if (isNaN(num)) return "-";
    // At most one decimal, no padding — the shape the browser's locale used
    // to print, now in the interface's own language.
    return formatQuantityLocale(String(num), 1);
  };

  const fields = [
    { label: String(t("energy")), value: nutrition.energy_kcal, unit: "kcal" },
    { label: String(t("proteins")), value: nutrition.proteins, unit: "g" },
    { label: String(t("fat")), value: nutrition.fat, unit: "g" },
    {
      label: String(t("carbohydrates")),
      value: nutrition.carbohydrates,
      unit: "g",
    },
    { label: String(t("sugars")), value: nutrition.sugars, unit: "g" },
    { label: String(t("salt")), value: nutrition.salt, unit: "g" },
    { label: String(t("fiber")), value: nutrition.fiber, unit: "g" },
  ].filter((f) => f.value !== undefined && f.value !== null);

  return (
    <div className="flex flex-col gap-4 animate-in fade-in slide-in-from-top-2 duration-500">
      <div className="grid grid-cols-3 gap-2">
        {/* Main Stats with Tiles */}
        {fields.map((f) => (
          <div
            key={f.label}
            className="bg-surface-card/50 border border-border rounded-xl p-2 flex flex-col items-center justify-center shadow-sm"
          >
            <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest leading-none mb-1 text-center">
              {f.label}
            </p>
            <div className="flex items-baseline gap-0.5">
              <span className="text-sm font-semibold text-on leading-none">
                {formatVal(f.value)}
              </span>
              <span className="text-[10px] font-medium text-on-muted uppercase">
                {f.unit}
              </span>
            </div>
          </div>
        ))}

        {/* Nutri-Score Tile */}
        {nutriscore && (
          <div className="bg-surface-card/50 border border-border rounded-xl p-2 flex flex-col items-center justify-center shadow-sm">
            <p className="text-[10px] font-medium text-on-muted uppercase tracking-widest leading-none mb-1">
              Nutri
            </p>
            <div
              className={`w-6 h-6 rounded-lg flex items-center justify-center text-xs font-medium text-white shadow-sm ${
                ["A", "B"].includes(nutriscore.toUpperCase())
                  ? "bg-accent-500"
                  : nutriscore.toUpperCase() === "C"
                    ? "bg-yellow-500"
                    : nutriscore.toUpperCase() === "D"
                      ? "bg-orange-500"
                      : "bg-red-500"
              }`}
            >
              {nutriscore.toUpperCase()}
            </div>
          </div>
        )}
      </div>
      <CommunityDataNote metadata={metadata} />
    </div>
  );
};

export default NutritionSummary;
