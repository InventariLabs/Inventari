import React, { useState } from "react";
import { logger } from "@/utils/logger";
import { Camera, Loader2, X, Check, Save } from "lucide-react";
import { visionApi } from "@/lib/api/vision";
import { itemsApi } from "@/lib/api/items";
import { extractApiError } from "@/lib/errors";
import type { ProductTemplateNutritionInfo } from "@/lib/api/productTemplates";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  isVisionConfigured,
  useAiPurposes,
} from "@/modules/settings/hooks/useAiConnections";
import { compressImage } from "@/lib/imageUtils";
import { Sheet, SheetActions } from "@/components/ui/Sheet";
import { Button } from "@/components/ui/Button";
import {
  useUpdateNutrition,
  useSaveNutritionToItem,
} from "@/modules/nutrition/hooks/useNutrition";

interface Props {
  itemId: string;
  templateId?: string;
  onSuccess: (newData: Record<string, unknown>) => void;
  onClose: () => void;
}

const NutritionScanner: React.FC<Props> = ({
  itemId,
  templateId,
  onSuccess,
  onClose,
}) => {
  const { t } = useTranslation(["nutrition", "common", "labels"]);
  // Same promise rule as the quick-add camera, including the silence: only
  // a registry that ANSWERED rules the sentences — answered and bound, the
  // promise; answered and unbound, the how-to and a capture control that
  // does not lead into the backend's refusal; unanswered, neither.
  const { data: purposes, isSuccess: registryAnswered } = useAiPurposes();
  const visionConfigured = registryAnswered && isVisionConfigured(purposes);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [extractedData, setExtractedData] = useState<Record<
    string,
    unknown
  > | null>(null);
  const updateNutrition = useUpdateNutrition();
  const saveNutritionToItem = useSaveNutritionToItem();

  const handleCapture = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsAnalyzing(true);
    try {
      const compressedFile = await compressImage(file);
      const result = await visionApi.extractNutrition(compressedFile);
      setExtractedData(result);
      toast.success(t("scanner.success"));
    } catch (error: unknown) {
      toast.error(extractApiError(error, t("scanner.error")));
      logger.error(error);
    } finally {
      setIsAnalyzing(false);
    }
  };

  const handleApply = async () => {
    if (!extractedData) return;

    try {
      if (templateId) {
        const nutritionInfo: ProductTemplateNutritionInfo = {
          calories_kcal: extractedData.energy_kcal as number | undefined,
          protein_g: extractedData.proteins as number | undefined,
          fat_g: extractedData.fat as number | undefined,
          carbs_g: extractedData.carbohydrates as number | undefined,
          fiber_g: extractedData.fiber as number | undefined,
          sugar_g: extractedData.sugars as number | undefined,
          salt_g: extractedData.salt as number | undefined,
        };
        await updateNutrition.mutateAsync({
          templateId,
          nutritionInfo,
          itemId,
        });
        toast.success(t("scanner.saveSuccess"));
        onSuccess({ nutrition_info: nutritionInfo });
        onClose();
      } else {
        const item = await itemsApi.getById(itemId);
        const currentMetadata = item.metadata || {};

        const updatedMetadata = {
          ...currentMetadata,
          off_enriched: true,
          nutrition_source: "vision_capture",
          nutrition: {
            ...extractedData,
            energy_kcal: extractedData.energy_kcal,
            proteins: extractedData.proteins,
            fat: extractedData.fat,
            carbohydrates: extractedData.carbohydrates,
            sugars: extractedData.sugars,
            salt: extractedData.salt,
            fiber: extractedData.fiber,
            saturated_fat: extractedData.saturated_fat,
            nova_group: extractedData.nova_group,
          },
          ingredients: extractedData.ingredients || currentMetadata.ingredients,
        };

        await saveNutritionToItem.mutateAsync({
          itemId,
          metadata: updatedMetadata,
        });
        toast.success(t("scanner.saveSuccess"));
        onSuccess(updatedMetadata);
        onClose();
      }
    } catch (error) {
      toast.error(
        t("scanner.saveError", { defaultValue: "Error saving data" }),
      );
      logger.error(error);
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="lg"
      backdropOpacity={80}
      className="overflow-hidden"
      aria-label={t("scanner.title")}
    >
      <div className="p-6 border-b flex items-center justify-between bg-primary-50/50">
        <div className="flex items-center gap-3">
          <div className="p-2 bg-primary-100 text-primary-600 rounded-xl">
            <Camera size={24} />
          </div>
          <div>
            <h3 className="font-semibold text-on uppercase tracking-tight">
              {t("scanner.title")}
            </h3>
            <p className="text-xs text-on-secondary font-medium text-primary-700/60">
              {t("scanner.subtitle")}
            </p>
          </div>
        </div>
        <Button
          variant="ghost"
          size="icon"
          onClick={onClose}
          className="rounded-full text-on-muted hover:bg-surface-card active:bg-surface-card"
          aria-label={t("common:a11y.close")}
        >
          <X size={20} />
        </Button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
        {!extractedData ? (
          <div className="space-y-8 py-10 text-center">
            <div className="w-24 h-24 bg-surface rounded-full flex items-center justify-center mx-auto text-on-muted border border-dashed border-border">
              {isAnalyzing ? (
                <Loader2 size={40} className="animate-spin text-primary-600" />
              ) : (
                <Camera size={40} />
              )}
            </div>
            <div className="max-w-xs mx-auto">
              <h4 className="font-semibold text-on mb-2">
                {t("scanner.howItWorksTitle")}
              </h4>
              {registryAnswered && (
                <p className="text-sm text-on-secondary leading-relaxed italic">
                  {visionConfigured
                    ? t("scanner.howItWorksDesc")
                    : t("scanner.howItWorksNoAi")}
                </p>
              )}
              {registryAnswered && !visionConfigured && (
                // The same door the quick-add camera offers: the refusal
                // sentence names what is missing, the link names where to
                // fix it.
                <Link
                  to="/settings/ai"
                  className="inline-flex items-center gap-1 text-sm font-medium text-on-primary hover:underline mt-1"
                >
                  {t("labels:quickAdd.visionSettingsLink")}
                </Link>
              )}
            </div>

            <label
              className={`block w-full cursor-pointer ${isAnalyzing || (registryAnswered && !visionConfigured) ? "opacity-50 pointer-events-none" : ""}`}
            >
              <div className="bg-primary-700 dark:bg-primary-800 text-white py-4 px-6 rounded-2xl font-semibold hover:bg-primary-800 dark:hover:bg-primary-900 active:scale-95 transition-all flex items-center justify-center gap-3">
                <Camera size={24} />
                <span>
                  {isAnalyzing
                    ? t("scanner.recognizing")
                    : t("scanner.takePhoto")}
                </span>
              </div>
              <input
                type="file"
                accept="image/*"
                capture="environment"
                className="hidden"
                // CSS alone used to block the capture: a disabled state no
                // assistive technology could see. The attribute makes the
                // refusal real for the control itself.
                disabled={registryAnswered && !visionConfigured}
                onChange={handleCapture}
              />
            </label>
          </div>
        ) : (
          <div className="space-y-6 animate-in slide-in-from-bottom-4 duration-300">
            <div className="bg-accent-50 border border-accent-100 rounded-2xl p-4 flex items-start gap-3">
              <Check className="text-accent-600 mt-1" size={20} />
              <div>
                <p className="font-semibold text-accent-800 text-sm">
                  {t("scanner.success")}
                </p>
                <p className="text-xs text-accent-700/70">
                  {t("scanner.checkData")}
                </p>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              {[
                {
                  label: String(t("scanner.energy")),
                  value: extractedData.energy_kcal,
                  unit: "kcal",
                },
                {
                  label: String(t("proteins")),
                  value: extractedData.proteins,
                  unit: "g",
                },
                {
                  label: String(t("fat")),
                  value: extractedData.fat,
                  unit: "g",
                },
                {
                  label: String(t("scanner.carbs")),
                  value: extractedData.carbohydrates,
                  unit: "g",
                },
                {
                  label: String(t("scanner.sugars")),
                  value: extractedData.sugars,
                  unit: "g",
                },
                {
                  label: String(t("scanner.salt")),
                  value: extractedData.salt,
                  unit: "g",
                },
              ].map((n, idx) => (
                <div
                  key={`${n.label}-${idx}`}
                  className="bg-surface p-3 rounded-xl border border-border"
                >
                  <p className="text-[10px] font-medium text-on-muted uppercase mb-1">
                    {n.label}
                  </p>
                  <p className="text-lg font-semibold text-on">
                    {(n.value as string | number) ?? "-"}{" "}
                    <span className="text-[10px] text-on-muted">{n.unit}</span>
                  </p>
                </div>
              ))}
            </div>

            {(extractedData.ingredients as string | null | undefined) && (
              <div className="bg-surface p-4 rounded-xl border border-border">
                <p className="text-[10px] font-medium text-on-muted uppercase mb-2">
                  {t("ingredients")}
                </p>
                <p className="text-xs text-on-secondary italic leading-relaxed line-clamp-4">
                  {extractedData.ingredients as string}
                </p>
              </div>
            )}

            <SheetActions className="pt-2">
              <Button
                size="content"
                variant="outline"
                onClick={() => setExtractedData(null)}
                className="py-4 border rounded-2xl font-medium uppercase text-xs hover:bg-surface active:bg-surface"
              >
                {t("scanner.retry")}
              </Button>
              <Button
                size="content"
                onClick={handleApply}
                className="py-4 rounded-2xl font-medium uppercase text-xs"
              >
                <Save size={18} />
                {t("scanner.save")}
              </Button>
            </SheetActions>
          </div>
        )}
      </div>
    </Sheet>
  );
};

export default NutritionScanner;
