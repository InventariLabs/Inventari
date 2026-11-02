import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Factory } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { TypedSlot } from "@/module-sdk";
import { useModules } from "@/contexts/ModulesContext";
import type { Recipe } from "../types/core";

/**
 * Header button for the recipe-to-production bridge — visible only when the
 * maker module is enabled. It owns the open state; the sheet behind it is the
 * maker module's, drawn through the `recipe_cook_for_stock` slot (the Sheet
 * renders as a fixed overlay, so it is safe inside the header actions
 * container).
 */
export function CookForStockButton({
  recipe,
  className,
  labelClassName = "hidden sm:inline",
}: {
  recipe: Recipe;
  className?: string;
  /**
   * in the page header the label collapses to icon-only below sm.
   * Contexts that only exist on phones (the ⋯ overflow menu) must pass ""
   * so the menu item keeps a readable label.
   */
  labelClassName?: string;
}) {
  const { t } = useTranslation("recipes");
  const { isModuleEnabled } = useModules();
  const [open, setOpen] = useState(false);
  if (!isModuleEnabled("maker")) return null;
  return (
    <>
      <Button
        variant="outline"
        onClick={() => setOpen(true)}
        className={`gap-2 ${className ?? ""}`}
        data-testid="cook-for-stock-button"
      >
        <Factory size={16} />
        <span className={labelClassName}>{t("cookForStock.button")}</span>
      </Button>
      <TypedSlot
        name="recipe_cook_for_stock"
        data={{ open, onClose: () => setOpen(false), recipe }}
      />
    </>
  );
}
