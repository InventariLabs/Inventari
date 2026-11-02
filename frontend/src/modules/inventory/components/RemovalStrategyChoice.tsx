import { useTranslation } from "react-i18next";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";

const STRATEGIES = ["FIFO", "FEFO"] as const;
type RemovalStrategy = (typeof STRATEGIES)[number];

interface RemovalStrategyChoiceProps {
  label: string;
  hint?: string;
  /** The stored value; an empty or missing one reads as FIFO, as the stock
   *  engine reads it. */
  value: string | null | undefined;
  onChange: (strategy: RemovalStrategy) => void;
}

/**
 * Which stock leaves a shelf first — the product's own order, or the one a
 * category gives its new products.
 *
 * Both acronyms are shown with the sentence that says what they mean, so the
 * reader does not have to know them already.
 */
export function RemovalStrategyChoice({
  label,
  hint,
  value,
  onChange,
}: RemovalStrategyChoiceProps) {
  const { t } = useTranslation("items");
  return (
    <div className="space-y-1.5">
      <ChoiceGroup
        label={label}
        hint={hint}
        options={STRATEGIES.map((id) => ({ id, label: id }))}
        value={value || "FIFO"}
        onChange={(id) => onChange(id as RemovalStrategy)}
      />
      <p className="text-xs text-on-muted ml-1">
        {t("removalStrategy.fifoHelp")}
      </p>
      <p className="text-xs text-on-muted ml-1">
        {t("removalStrategy.fefoHelp")}
      </p>
    </div>
  );
}
