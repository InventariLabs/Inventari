import { useTranslation } from "react-i18next";
import { DateInput } from "@/components/ui/DateInput";
import { useIsHomeProfile } from "@/modules/maker/hooks/useIsHomeProfile";

interface BestBeforeFieldProps {
  id: string;
  value: string;
  onChange: (value: string) => void;
  /** The day the goods are made: no batch keeps for less than nothing. */
  min?: string;
  shelfLifeDays?: number | null;
}

/**
 * The best-before of a batch a run puts on the shelf, with the line that says
 * where the proposed date came from. One field for every door of a run — the
 * dialog that completes it, a portion, the finish.
 */
export function BestBeforeField({
  id,
  value,
  onChange,
  min,
  shelfLifeDays,
}: BestBeforeFieldProps) {
  const { t } = useTranslation("maker");
  const home = useIsHomeProfile();
  return (
    <div className="space-y-1">
      <DateInput
        id={id}
        label={t("batches.bestBeforeLabel")}
        value={value}
        onChange={onChange}
        min={min}
        presets={["plus6Months", "plus1Year"]}
      />
      <p className="text-xs text-on-muted">
        {shelfLifeDays
          ? t("batches.bestBeforeFromShelfLife", { count: shelfLifeDays })
          : t(
              home
                ? "batches.bestBeforeNoShelfLifeHome"
                : "batches.bestBeforeNoShelfLife",
            )}
      </p>
    </div>
  );
}
