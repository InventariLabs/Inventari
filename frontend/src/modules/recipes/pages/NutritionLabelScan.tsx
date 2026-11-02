import { useRef, useState } from "react";
import { Camera, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { visionApi } from "@/lib/api/vision";
import { compressImage } from "@/lib/imageUtils";
import { extractApiError } from "@/lib/errors";
import { logger } from "@/utils/logger";
import type { IngredientDefaultCreate } from "@/modules/recipes/types/nutrition-defaults";

/**
 * What the label reader returns, and which field of this form it fills.
 *
 * The reading is the nutrition module's own field group, normalised to
 * 100 g / 100 ml — which is the basis this table stores, so nothing is
 * converted on the way in.
 */
const FROM_LABEL: ReadonlyArray<[string, keyof IngredientDefaultCreate]> = [
  ["energy_kcal", "calories_kcal"],
  ["proteins", "protein_g"],
  ["fat", "fat_g"],
  ["carbohydrates", "carbs_g"],
  ["fiber", "fiber_g"],
  ["sugars", "sugar_g"],
  ["salt", "salt_g"],
];

interface NutritionLabelScanProps {
  /** Applied to the draft, never saved — the person checks the numbers. */
  onRead: (values: Partial<IngredientDefaultCreate>) => void;
  t: (key: string, options?: Record<string, unknown>) => string;
}

/**
 * Reading a nutrition table off a photograph instead of copying it by hand.
 *
 * Adding an ingredient here meant transcribing seven numbers from a package,
 * and a processed one — vinegar, oil, butter — prints all seven on its label.
 * The reading is a proposal: it fills the form the person is already looking
 * at, and nothing reaches the table until they save it. These numbers go on
 * to count the calories in every recipe using the ingredient, which is not a
 * place for an unread answer.
 */
export function NutritionLabelScan({ onRead, t }: NutritionLabelScanProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [reading, setReading] = useState(false);

  const onFile = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Cleared straight away so photographing the same label twice — after a
    // reading nobody liked — still fires a change.
    event.target.value = "";
    if (!file) return;

    setReading(true);
    try {
      const result = await visionApi.extractNutrition(
        await compressImage(file),
      );
      const values: Partial<IngredientDefaultCreate> = {};
      for (const [read, field] of FROM_LABEL) {
        const value = result[read];
        if (typeof value === "number" && Number.isFinite(value)) {
          Object.assign(values, { [field]: value });
        }
      }
      const count = Object.keys(values).length;
      if (count === 0) {
        toast.warning(t("recipes:ingredient_defaults.scan_nothing_read"));
        return;
      }
      onRead(values);
      toast.success(t("recipes:ingredient_defaults.scan_read", { count }));
    } catch (error: unknown) {
      toast.error(
        extractApiError(error, t("recipes:ingredient_defaults.scan_failed")),
      );
      logger.error(error);
    } finally {
      setReading(false);
    }
  };

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className="gap-1.5"
        disabled={reading}
        onClick={() => inputRef.current?.click()}
      >
        {reading ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <Camera size={16} />
        )}
        {reading
          ? t("recipes:ingredient_defaults.scan_reading")
          : t("recipes:ingredient_defaults.scan_label")}
      </Button>
      <input
        ref={inputRef}
        type="file"
        accept="image/*"
        // On a phone this opens the camera rather than the gallery: the label
        // being read is on a package in the reader's hand.
        capture="environment"
        className="hidden"
        onChange={(event) => void onFile(event)}
      />
    </>
  );
}
