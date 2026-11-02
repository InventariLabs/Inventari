import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import ReactMarkdown from "react-markdown";
import rehypeSanitize from "rehype-sanitize";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { Textarea } from "@/components/ui/Textarea";
import { Sheet, SheetActions, SheetFooter } from "@/components/ui/Sheet";
import {
  previewToDraft,
  composeDisplayText,
  lacksUnit,
  type DraftValue,
  type IngredientDraft,
} from "./importReviewUtils";
import { InstructionsMarkdownToolbar } from "./InstructionsMarkdownToolbar";
import ImportIngredientsTab from "./ImportIngredientsTab";
import type { RecipeCreateInput } from "@/modules/recipes/types/core";
import type { RecipeImportPreview } from "@/modules/recipes/types/nutrition";
import type { RecipeIngredientCreateInput } from "@/modules/recipes/types/core";

interface ImportReviewModalProps {
  preview: RecipeImportPreview;
  onSave: (data: RecipeCreateInput) => void;
  onBack: () => void;
  isSaving: boolean;
  /** Why the save failed — stays on screen, unlike a toast. */
  saveError?: string | null;
}

type Tab = "ingredients" | "instructions";

export default function ImportReviewModal({
  preview,
  onSave,
  onBack,
  isSaving,
  saveError,
}: ImportReviewModalProps) {
  const { t } = useTranslation("recipes");

  const [name, setName] = useState(preview.name);
  const [servings, setServings] = useState(String(preview.servings));
  const [prepTime, setPrepTime] = useState(
    preview.prep_time_minutes != null ? String(preview.prep_time_minutes) : "",
  );
  const [description, setDescription] = useState(preview.description ?? "");
  const [instructions, setInstructions] = useState(preview.instructions ?? "");

  const [ingredients, setIngredients] = useState<IngredientDraft[]>(() =>
    preview.ingredients.map((ing, i) => previewToDraft(ing, i)),
  );
  const [nextKey, setNextKey] = useState(preview.ingredients.length);

  const instructionsRef = useRef<HTMLTextAreaElement>(null);
  const [activeTab, setActiveTab] = useState<Tab>("ingredients");
  const [mdPreview, setMdPreview] = useState(true);

  function applyMarkdown(prefix: string, suffix: string, placeholder: string) {
    const el = instructionsRef.current;
    if (!el) return;
    const start = el.selectionStart;
    const end = el.selectionEnd;
    const sel = el.value.slice(start, end) || placeholder;
    const next =
      el.value.slice(0, start) + prefix + sel + suffix + el.value.slice(end);
    setInstructions(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(
        start + prefix.length,
        start + prefix.length + sel.length,
      );
    });
  }

  function applyLinePrefix(prefix: string) {
    const el = instructionsRef.current;
    if (!el) return;
    const pos = el.selectionStart;
    const lineStart = el.value.lastIndexOf("\n", pos - 1) + 1;
    const next =
      el.value.slice(0, lineStart) + prefix + el.value.slice(lineStart);
    setInstructions(next);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(pos + prefix.length, pos + prefix.length);
    });
  }

  const addIngredient = () => {
    setIngredients((prev) => [
      ...prev,
      previewToDraft({ name: "", quantity: 1 }, nextKey),
    ]);
    setNextKey((k) => k + 1);
  };

  const removeIngredient = (key: number) => {
    setIngredients((prev) => prev.filter((i) => i._key !== key));
  };

  const updateIngredient = (
    key: number,
    field: keyof IngredientDraft,
    value: DraftValue,
  ) => {
    setIngredients((prev) =>
      prev.map((i) => {
        if (i._key !== key) return i;
        const updated = { ...i, [field]: value };
        // When display quantity changes, scale metric quantity proportionally
        if (field === "quantity" && i.original_unit_text) {
          const newDisplayQty = parseFloat(String(value)) || 0;
          updated.metric_quantity = String(
            parseFloat((newDisplayQty * i.conversion_ratio).toFixed(3)),
          );
        }
        // For metric-only ingredients, keep metric in sync
        if (field === "quantity" && !i.original_unit_text) {
          updated.metric_quantity = String(value);
        }
        return updated;
      }),
    );
  };

  const unitMissing = ingredients.some(lacksUnit);

  const handleSave = () => {
    const recipeIngredients: RecipeIngredientCreateInput[] = ingredients.map(
      (ing, idx) => ({
        name: ing.name.trim(),
        quantity: Number(ing.metric_quantity) || 1,
        uom_id: ing.uom_id,
        template_id: ing.template_id,
        ingredient_group_name: ing.group_name,
        is_optional: ing.is_optional,
        is_spice: ing.is_spice_forced,
        allergens: ing.allergens,
        sort_order: idx,
        display_text: composeDisplayText(ing),
        original_quantity: ing.original_unit_text
          ? Number(ing.quantity) || null
          : null,
        original_unit_text: ing.original_unit_text,
      }),
    );

    const data: RecipeCreateInput = {
      name: name.trim(),
      description: description.trim() || undefined,
      instructions: instructions.trim() || undefined,
      servings: Number(servings) || 1,
      prep_time_minutes: prepTime ? Number(prepTime) : undefined,
      image_source_url: preview.image_source_url ?? undefined,
      source_url: preview.source_url ?? undefined,
      tags: preview.tags,
      ingredients: recipeIngredients,
    };

    onSave(data);
  };

  return (
    <Sheet
      open
      onClose={onBack}
      maxWidth="3xl"
      aria-label={t("import_export.review_title")}
    >
      {/* Header */}
      <div className="flex items-center gap-3 px-5 pt-4 pb-3 border-b border-border shrink-0">
        <Button
          type="button"
          variant="ghost"
          size="iconSm"
          onClick={onBack}
          aria-label={t("common:actions.back")}
          className="text-on-muted hover:text-on-secondary"
        >
          <ArrowLeft size={16} />
        </Button>
        <div>
          <h2 className="text-base font-semibold text-on">
            {t("import_export.review_title")}
          </h2>
          <p className="text-xs text-on-secondary">
            {t("import_export.review_subtitle")}
          </p>
        </div>
      </div>

      {preview.parse_warning === "llm_fallback" && (
        <div
          role="alert"
          className="mx-5 mt-3 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-on-warning shrink-0"
        >
          {t("import_export.review_parse_warning")}
        </div>
      )}

      {/* Scrollable body */}
      <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {/* Recipe metadata */}
        <div className="grid grid-cols-1 sm:grid-cols-3 items-end gap-3">
          <Input
            wrapperClassName="sm:col-span-3"
            label={t("import_export.review_recipe_name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
          <Textarea
            wrapperClassName="sm:col-span-3"
            label={t("form.description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("form.description_placeholder")}
            rows={2}
            className="resize-none"
          />
          <Input
            label={t("import_export.review_servings")}
            type="number"
            min={1}
            value={servings}
            onChange={(e) => setServings(e.target.value)}
          />
          <Input
            label={t("import_export.review_prep_time")}
            type="number"
            min={0}
            value={prepTime}
            onChange={(e) => setPrepTime(e.target.value)}
          />
        </div>

        <Tabs
          defaultValue="ingredients"
          value={activeTab}
          onValueChange={(tab) => setActiveTab(tab as Tab)}
        >
          <TabsList>
            <TabsTrigger value="ingredients" size="sm">
              {t("import_export.tab_ingredients")}
            </TabsTrigger>
            <TabsTrigger value="instructions" size="sm">
              {t("import_export.tab_instructions")}
            </TabsTrigger>
          </TabsList>

          <TabsContent value="instructions" className="mt-4 space-y-2">
            <InstructionsMarkdownToolbar
              mdPreview={mdPreview}
              onTogglePreview={() => setMdPreview((v) => !v)}
              onBold={() =>
                applyMarkdown(
                  "**",
                  "**",
                  t("import_export.md_placeholder_bold"),
                )
              }
              onItalic={() =>
                applyMarkdown(
                  "*",
                  "*",
                  t("import_export.md_placeholder_italic"),
                )
              }
              onHeading={() => applyLinePrefix("## ")}
              onBulletList={() => applyLinePrefix("- ")}
              onOrderedList={() => applyLinePrefix("1. ")}
              t={t}
            />

            {mdPreview ? (
              <div
                className="min-h-[50vh] rounded-xl border border-border px-4 py-3 text-sm overflow-y-auto
                  [&_h2]:text-base [&_h2]:font-semibold [&_h2]:mt-4 [&_h2]:mb-2
                  [&_h3]:text-sm [&_h3]:font-semibold [&_h3]:mt-3 [&_h3]:mb-1
                  [&_p]:mb-2 [&_p]:leading-relaxed
                  [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:mb-2
                  [&_ol]:list-decimal [&_ol]:pl-5 [&_ol]:mb-2
                  [&_li]:mb-1
                  [&_strong]:font-semibold [&_em]:italic"
              >
                {instructions.trim() ? (
                  <ReactMarkdown rehypePlugins={[rehypeSanitize]}>
                    {instructions}
                  </ReactMarkdown>
                ) : (
                  <p className="text-on-muted italic">
                    {t("import_export.md_empty")}
                  </p>
                )}
              </div>
            ) : (
              <Textarea
                ref={instructionsRef}
                aria-label={t("form.instructions")}
                value={instructions}
                onChange={(e) => setInstructions(e.target.value)}
                className="w-full min-h-[50vh] rounded-xl border border-border px-3 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-primary-300 resize-y leading-relaxed font-mono"
              />
            )}
          </TabsContent>

          <TabsContent value="ingredients" className="mt-4 space-y-2">
            <ImportIngredientsTab
              ingredients={ingredients}
              hasOriginalText={preview.ingredients.some((i) => i.original_text)}
              onUpdate={updateIngredient}
              onRemove={removeIngredient}
              onAdd={addIngredient}
            />
          </TabsContent>
        </Tabs>
      </div>

      {unitMissing && (
        <p
          role="status"
          className="mx-5 mb-3 shrink-0 rounded-xl bg-amber-50 px-3 py-2 text-sm text-on-warning"
        >
          {t("import_export.review_units_needed")}
        </p>
      )}

      {saveError && (
        <p
          role="alert"
          className="mx-5 mb-3 shrink-0 rounded-xl bg-red-50 px-3 py-2 text-sm text-on-danger"
        >
          {saveError}
        </p>
      )}

      {/* Footer */}
      <SheetFooter>
        <SheetActions>
          <Button variant="outline" onClick={onBack}>
            {t("import_export.review_back")}
          </Button>
          <Button
            onClick={handleSave}
            disabled={isSaving || !name.trim() || unitMissing}
          >
            {isSaving
              ? t("import_export.review_saving")
              : t("import_export.review_save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
