import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AlertTriangle, Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { InlinePopover } from "./InlinePopover";
import { ALLERGEN_KEYS } from "../constants/allergens";

interface AllergenPickerProps {
  value: string[];
  onChange: (allergens: string[]) => void;
}

/**
 * Inline popover to pick EU 1169/2011 allergens for one ingredient.
 * Renders as a compact chip list + chevron trigger; opens a checkbox grid.
 */
export function AllergenPicker({ value, onChange }: AllergenPickerProps) {
  const { t } = useTranslation("recipes");
  const [isOpen, setIsOpen] = useState(false);

  const toggle = (key: string) => {
    onChange(
      value.includes(key) ? value.filter((v) => v !== key) : [...value, key],
    );
  };

  return (
    <InlinePopover
      open={isOpen}
      onOpenChange={setIsOpen}
      align="start"
      className="w-64 max-w-[calc(100vw-2rem)] p-3"
      trigger={
        <Button
          size="content"
          type="button"
          variant="outline"
          className={cn(
            "gap-1.5 px-2 py-1 rounded-lg text-xs transition-colors",
            value.length > 0
              ? "border-amber-300 bg-amber-50 text-on-warning"
              : "border-dashed border-border text-on-muted hover:text-on-secondary",
          )}
        >
          <AlertTriangle size={16} className="shrink-0" aria-hidden="true" />
          {value.length > 0
            ? t("allergens.selected", { count: value.length })
            : t("allergens.none")}
          <ChevronDown
            size={16}
            aria-hidden="true"
            className={cn("transition-transform", isOpen && "rotate-180")}
          />
        </Button>
      }
    >
      <>
        <div>
          <p className="text-xs font-medium text-on-muted uppercase tracking-widest mb-2">
            {t("allergens.title")}
          </p>
          <div className="grid grid-cols-2 gap-x-2 gap-y-1">
            {ALLERGEN_KEYS.map((key) => {
              const checked = value.includes(key);
              return (
                <label
                  key={key}
                  className={cn(
                    "flex items-center gap-1.5 px-1.5 py-1 rounded-md cursor-pointer text-xs transition-colors",
                    checked
                      ? "bg-amber-50 text-on-warning"
                      : "text-on-secondary hover:bg-surface-raised",
                  )}
                >
                  <Checkbox checked={checked} onChange={() => toggle(key)} />
                  <span className="truncate">{t(`allergens.${key}`)}</span>
                  {checked && (
                    <Check
                      size={11}
                      className="text-on-warning ml-auto shrink-0"
                    />
                  )}
                </label>
              );
            })}
          </div>
          <p className="mt-2 text-xs text-on-muted">{t("allergens.note")}</p>
        </div>
      </>
    </InlinePopover>
  );
}
