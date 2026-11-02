import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface Props {
  value: number;
  onChange: (v: number) => void;
  /** Text to the left of the stepper. Omit where a heading already says it. */
  label?: string;
  /** Unit rendered after the number, e.g. "servings". */
  unit?: string;
  cleanHint?: string | null;
  /**
   * `sm` for a sheet or a compact row, `lg` for the ingredients header where
   * the count is the thing being read. The module had one of each, written
   * twice; the difference was only ever the size of the digit — and the copy
   * that lived inline had the accessible names the shared one was missing.
   */
  size?: "sm" | "lg";
  /** Extra controls rendered beside the plus button (e.g. a reset). */
  children?: React.ReactNode;
}

export default function ServingsSelector({
  value,
  onChange,
  label,
  unit,
  cleanHint,
  size = "sm",
  children,
}: Props) {
  const { t } = useTranslation("recipes");
  return (
    <div>
      <div className="flex items-center gap-3">
        {label && <span className="text-sm text-on-secondary">{label}</span>}
        <div className="flex items-center gap-1">
          <Button
            size="iconSm"
            variant="ghost"
            onClick={() => onChange(Math.max(1, value - 1))}
            aria-label={t("a11y.decrease_servings")}
            title={t("a11y.decrease_servings")}
          >
            −
          </Button>
          <span
            className={cn(
              "text-center",
              size === "lg" ? "min-w-[2.5rem]" : "w-8",
            )}
          >
            <span
              className={cn(
                "text-on",
                size === "lg" ? "text-lg font-semibold" : "font-semibold",
              )}
            >
              {value}
            </span>
            {unit && <span className="text-xs text-on-muted ml-1">{unit}</span>}
          </span>
          <Button
            size="iconSm"
            variant="ghost"
            onClick={() => onChange(value + 1)}
            aria-label={t("a11y.increase_servings")}
            title={t("a11y.increase_servings")}
          >
            +
          </Button>
          {children}
        </div>
      </div>
      {cleanHint && (
        <p className="text-xs text-on-warning mt-1.5">{cleanHint}</p>
      )}
    </div>
  );
}
