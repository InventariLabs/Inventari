import { useState, useEffect, useMemo, useRef } from "react";
import { useTranslation } from "react-i18next";

import { resolveLang } from "@/i18n/languages";
import { useFormGuard } from "@/hooks/useFormGuard";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Textarea } from "@/components/ui/Textarea";
import { Checkbox } from "@/components/ui/Checkbox";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { FIELD_LABEL_CLASS } from "@/components/ui/fieldLabel";
import LoadingSpinner from "@/components/LoadingSpinner";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { useDebouncedIngredientLookup } from "@/modules/recipes/hooks/useIngredientDefaults";
import {
  useUploadRecipeImage,
  useDeleteRecipeImage,
} from "@/modules/recipes/hooks/useRecipes";
import { recipesApi } from "@/modules/recipes/api/recipes";
import type {
  Recipe,
  RecipeCreate,
  RecipeIngredient,
} from "@/modules/recipes/types/core";
import type { IngredientDefaultLookupResponse } from "@/modules/recipes/types/nutrition-defaults";
import RecipeIngredientsSection, {
  type IngredientDraft,
} from "./RecipeIngredientsSection";
import RecipeMarkdownEditor from "./RecipeMarkdownEditor";

interface Props {
  initial?: Partial<Recipe>;
  /** create mode can hand the picked photo over — it is uploaded
   *  after the recipe exists, because the image endpoint needs the id. */
  onSubmit: (data: RecipeCreate, imageFile?: File | null) => void;
  onCancel: () => void;
  isLoading?: boolean;
  /**
   * The record to edit is still on its way. The sheet stands at once with a
   * spinner in it, and the form takes its place inside the very same sheet
   * when `initial` lands — a second sheet mounted for the form replayed the
   * entrance (the backdrop blinked out, the panel slid in again).
   */
  loading?: boolean;
}

/** A draft row as the wire carries it: no editor key. The picking override
 *  keeps its null (auto) — settling it to false would pin every loaded row. */
function wireRow({ _key: _ignored, ...rest }: IngredientDraft) {
  return rest;
}

/** A saved ingredient as the form edits it: the figures as text, the optional
 *  wire fields settled — the row's tri-state keeps its null. */
function draftRow(ing: RecipeIngredient, i: number): IngredientDraft {
  return {
    ...ing,
    _key: i,
    quantity: String(ing.quantity),
    price: ing.price != null ? String(ing.price) : "",
    picking_skip: ing.picking_skip ?? null,
    allergens: ing.allergens ?? [],
    calories_kcal_per_100g:
      ing.calories_kcal_per_100g != null
        ? String(ing.calories_kcal_per_100g)
        : "",
  };
}

/** What is wrong with each named ingredient line, keyed the way the rows read it. */
function ingredientErrors(
  ingredients: IngredientDraft[],
  t: (key: string) => string,
): Record<string, string> {
  const errs: Record<string, string> = {};
  ingredients.forEach((ing, idx) => {
    if (!ing.name.trim()) return;
    if (!ing.quantity || Number(ing.quantity) <= 0)
      errs[`ing_qty_${idx}`] = t("form.errors.ingredient_qty_min");
    // An amount with no unit is no amount: "Salt 1" could not be weighed
    // against the shelf, and reached the shopping list as "1 —".
    if (!ing.uom_id)
      errs[`ing_uom_${idx}`] = t("form.errors.ingredient_unit_required");
  });
  return errs;
}

function emptyIngredient(key: number): IngredientDraft {
  return {
    _key: key,
    name: "",
    quantity: "1",
    uom_id: null,
    uom_symbol: null,
    is_optional: false,
    is_spice: false,
    picking_skip: null,
    sort_order: key,
    calories_kcal_per_100g: "",
    price: "",
    allergens: [],
  };
}

/**
 * Auto-fill kcal and inferred allergens for the ingredients of a recipe loaded
 * for editing, looking each name up at most once per form. The effect used to
 * write state and depend on `ingredients`: a lookup answering allergens but no
 * kcal left the ingredient in `missing`, the fresh array identity re-armed the
 * effect, and one ingredient produced a steady stream of GETs for as long as
 * the dialog stayed open.
 *
 * The in-flight promise is held per (recipe, language, name) in a ref that
 * survives StrictMode's throwaway remount, and whichever effect pass is still
 * mounted when it resolves applies the answer. Latching the lookup before it
 * resolves would let the setup-cleanup-setup drop the answer and never re-ask.
 */
function useIngredientDefaultsAutofill(
  loaded: RecipeIngredient[] | undefined,
  recipeId: string | null,
  lang: string,
  setIngredients: React.Dispatch<React.SetStateAction<IngredientDraft[]>>,
) {
  const lookups = useRef(
    new Map<string, Promise<IngredientDefaultLookupResponse>>(),
  );
  useEffect(() => {
    const ingredients = loaded ?? [];
    const keyOf = (name: string) =>
      `${recipeId ?? "new"}|${lang}|${name.trim().toLowerCase()}`;
    const lookup = (name: string) => {
      const key = keyOf(name);
      let pending = lookups.current.get(key);
      if (!pending) {
        pending = recipesApi.lookupIngredientDefault(name.trim(), lang);
        lookups.current.set(key, pending);
      }
      return pending;
    };
    const missing = ingredients.filter(
      (i) => i.name.trim().length >= 2 && i.calories_kcal_per_100g == null,
    );
    if (!missing.length) return;
    let mounted = true;
    (async () => {
      for (const ing of missing) {
        try {
          const result = await lookup(ing.name);
          if (!mounted) return;
          const hasKcal = result.found && result.calories_kcal != null;
          const hasAllergens = Boolean(result.allergens?.length);
          if (!hasKcal && !hasAllergens) continue;
          setIngredients((prev) =>
            prev.map((i) => {
              if (i.name.trim().toLowerCase() !== ing.name.trim().toLowerCase())
                return i;
              let patched = i;
              if (hasKcal && patched.calories_kcal_per_100g === "") {
                patched = {
                  ...patched,
                  calories_kcal_per_100g: String(result.calories_kcal),
                };
              }
              // Fill inferred allergens for ingredients missing them
              if (hasAllergens && !patched.allergens?.length) {
                patched = { ...patched, allergens: result.allergens };
              }
              return patched;
            }),
          );
        } catch {
          // ignore — lookup failure is non-fatal
        }
      }
    })();
    return () => {
      mounted = false;
    };
  }, [loaded, lang, recipeId, setIngredients]);
}

/**
 * The sheet around the recipe form. It owns the `Sheet` so that one stays
 * mounted from the first frame of a slow edit until the form closes: what
 * changes when the recipe arrives is only what is inside it.
 */
export default function RecipeForm({ loading, ...props }: Props) {
  const { t } = useTranslation(["recipes", "common"]);
  const { initial, onCancel } = props;
  // The form inside knows whether it holds work worth asking about; until it
  // is mounted there is nothing to lose and the sheet just closes.
  const leaveRef = useRef<(() => void) | null>(null);
  const editing = loading || !!initial;
  const title = editing ? t("form.edit_title") : t("form.create_title");
  return (
    <Sheet
      open
      onClose={() => (leaveRef.current ?? onCancel)()}
      maxWidth="3xl"
      className="overflow-hidden"
      aria-label={title}
    >
      {loading ? (
        <>
          <SheetHeader
            title={title}
            onClose={onCancel}
            closeLabel={t("common:actions.close")}
            className="px-5 py-4 shrink-0"
          />
          <SheetBody>
            <LoadingSpinner />
          </SheetBody>
        </>
      ) : (
        <RecipeFormContent {...props} leaveRef={leaveRef} />
      )}
    </Sheet>
  );
}

/**
 * What the form owes the sheet that holds it, returning the form's ref.
 *
 * The loading header's close button held the focus and went with it when the
 * form took its place; with it gone the sheet's Tab trap has no end to wrap
 * at, so the first field takes it. And the sheet asks the form before it
 * closes (`leaveRef`), so a filled-in form is not thrown away unasked.
 */
function useSheetHandover(
  leaveRef: React.MutableRefObject<(() => void) | null>,
  requestLeave: () => void,
) {
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    const active = document.activeElement;
    if (!active || active === document.body) {
      formRef.current?.querySelector<HTMLElement>("input")?.focus();
    }
  }, []);
  useEffect(() => {
    leaveRef.current = requestLeave;
    return () => {
      leaveRef.current = null;
    };
  });
  return formRef;
}

type ContentProps = Omit<Props, "loading"> & {
  leaveRef: React.MutableRefObject<(() => void) | null>;
};

function RecipeFormContent({
  initial,
  onSubmit,
  onCancel,
  isLoading,
  leaveRef,
}: ContentProps) {
  const { t, i18n } = useTranslation(["recipes", "common"]);
  const lang = resolveLang(i18n.language);
  const lookupDefault = useDebouncedIngredientLookup(lang);

  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [instructions, setInstructions] = useState(initial?.instructions ?? "");
  const [servings, setServings] = useState<string>(
    String(initial?.servings ?? 1),
  );
  const baseServingsRef = { current: initial?.servings ?? 1 };

  function scaleIngredients(fromServings: number, toServings: number) {
    if (!fromServings || !toServings || fromServings === toServings) return;
    const ratio = toServings / fromServings;
    setIngredients((prev) =>
      prev.map((ing) => {
        const qty = parseFloat(ing.quantity);
        if (isNaN(qty)) return ing;
        const scaled = parseFloat((qty * ratio).toFixed(4));
        return { ...ing, quantity: String(parseFloat(scaled.toFixed(3))) };
      }),
    );
    baseServingsRef.current = toServings;
  }

  const [prepTime, setPrepTime] = useState<string>(
    initial?.prep_time_minutes != null ? String(initial.prep_time_minutes) : "",
  );
  const [tagsRaw, setTagsRaw] = useState((initial?.tags ?? []).join(", "));
  const [isFavorite, setIsFavorite] = useState(initial?.is_favorite ?? false);

  // photo — edit mode uploads straight to the existing recipe;
  // create mode keeps the picked file locally until the recipe exists.
  const recipeId = initial?.id ?? null;
  const uploadImageMutation = useUploadRecipeImage();
  const deleteImageMutation = useDeleteRecipeImage();
  const [imageFile, setImageFile] = useState<File | null>(null);
  const [imagePreview, setImagePreview] = useState<string | null>(null);
  const isUploading = uploadImageMutation.isPending;

  const handleImageChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (recipeId) {
      uploadImageMutation.mutate({ id: recipeId, file });
    } else {
      setImageFile(file);
      setImagePreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return URL.createObjectURL(file);
      });
    }
    e.target.value = "";
  };

  const handleDeleteImage = () => {
    if (recipeId) {
      deleteImageMutation.mutate(recipeId);
    } else {
      setImageFile(null);
      setImagePreview((prev) => {
        if (prev) URL.revokeObjectURL(prev);
        return null;
      });
    }
  };

  const [ingredients, setIngredients] = useState<IngredientDraft[]>(() => {
    if (initial?.ingredients?.length) {
      return initial.ingredients.map(draftRow);
    }
    return [emptyIngredient(0)];
  });
  const [nextKey, setNextKey] = useState(ingredients.length);

  // Auto-fill kcal and inferred allergens for the ingredients of a recipe
  // loaded for editing — each loaded ingredient is looked up at most once per
  // form. The StrictMode-safe loop lives in the hook.
  useIngredientDefaultsAutofill(
    initial?.ingredients,
    recipeId,
    lang,
    setIngredients,
  );

  const [errors, setErrors] = useState<Record<string, string>>({});
  const [discardConfirmOpen, setDiscardConfirmOpen] = useState(false);

  // The form as it stood when it opened — the yardstick for "is there
  // anything to lose". The longest form in the module used to be thrown away
  // by Escape, the cross, or a click on the backdrop, without a word and
  // without a draft.
  const written = useMemo(
    () =>
      JSON.stringify({
        name,
        description,
        instructions,
        servings,
        prepTime,
        tagsRaw,
        isFavorite,
        hasPhoto: imageFile !== null,
        ingredients: ingredients.map(wireRow),
      }),
    [
      name,
      description,
      instructions,
      servings,
      prepTime,
      tagsRaw,
      isFavorite,
      imageFile,
      ingredients,
    ],
  );
  const pristineRef = useRef(written);
  const isDirty = written !== pristineRef.current;

  // The palette walks the same gate over this sheet (measured live), so a
  // typed recipe registers — `requestLeave` below covers only this form's
  // own exits.
  useFormGuard(isDirty, t("recipes:form.guardName"));

  /**
   * Every way out of this form goes through here, so a recipe being typed is
   * never lost without a word: Escape, the cross in the header, the backdrop
   * and the Cancel button all ask the same question.
   */
  const requestLeave = () => {
    if (isDirty) {
      setDiscardConfirmOpen(true);
      return;
    }
    onCancel();
  };

  const formRef = useSheetHandover(leaveRef, requestLeave);

  const addIngredient = () => {
    setIngredients((prev) => [...prev, emptyIngredient(nextKey)]);
    setNextKey((k) => k + 1);
  };

  const removeIngredient = (key: number) => {
    setIngredients((prev) => prev.filter((i) => i._key !== key));
  };

  const updateIngredient = (
    key: number,
    field: keyof IngredientDraft,
    value: IngredientDraft[keyof IngredientDraft],
  ) => {
    setIngredients((prev) =>
      prev.map((i) => (i._key === key ? { ...i, [field]: value } : i)),
    );
  };

  const handleIngredientNameBlur = (ing: IngredientDraft) => {
    lookupDefault(ing.name, (result) => {
      if (result.found && result.calories_kcal != null) {
        updateIngredient(
          ing._key,
          "calories_kcal_per_100g",
          String(result.calories_kcal),
        );
      }
      // Fill inferred allergens unless the user already set some
      if (result.allergens?.length && !ing.allergens?.length) {
        updateIngredient(ing._key, "allergens", result.allergens);
      }
    });
  };

  const validate = (): boolean => {
    const errs: Record<string, string> = {};
    if (!name.trim()) errs["name"] = t("form.errors.name_required");
    if (!servings || Number(servings) < 1)
      errs["servings"] = t("form.errors.servings_min");
    // prep time must be non-negative (HTML min=0 only blocks the spinner).
    if (prepTime !== "" && Number(prepTime) < 0)
      errs["prep_time_minutes"] = t("form.errors.prep_time_min");
    Object.assign(errs, ingredientErrors(ingredients, t));
    setErrors(errs);
    return Object.keys(errs).length === 0;
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!validate()) return;

    const tags = tagsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);

    onSubmit(
      {
        name: name.trim(),
        // Explicit null, never undefined: the sheet always submits every
        // field, and an absent one would leave the old value on the
        // server (exclude_unset) — the cleared description that always
        // came back.
        description: description.trim() || null,
        instructions: instructions.trim() || null,
        servings: Number(servings) || 1,
        prep_time_minutes: prepTime === "" ? null : Number(prepTime),
        tags: tags.length ? tags : null,
        is_favorite: isFavorite,
        ingredients: ingredients
          .filter((i) => i.name.trim())
          .map(
            (
              { _key, quantity, calories_kcal_per_100g, price, ...rest },
              idx,
            ) => ({
              ...rest,
              quantity: Number(quantity) || 0,
              sort_order: rest.sort_order ?? idx,
              calories_kcal_per_100g:
                calories_kcal_per_100g !== ""
                  ? Number(calories_kcal_per_100g) || null
                  : null,
              price: price !== "" ? Number(price) || null : null,
            }),
          ),
      },
      imageFile,
    );
  };

  return (
    <>
      <form
        ref={formRef}
        onSubmit={handleSubmit}
        className="flex flex-col flex-1 min-h-0"
      >
        <SheetHeader
          title={initial ? t("form.edit_title") : t("form.create_title")}
          onClose={requestLeave}
          closeLabel={t("common:actions.close")}
          className="px-5 py-4 shrink-0"
        />

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <Input
            label={t("form.name")}
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("form.name_placeholder")}
            error={errors["name"]}
          />

          {/* One label variant across the form — the one the field components
 write themselves. This field used to opt out of it. */}
          <Textarea
            label={t("form.description")}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder={t("form.description_placeholder")}
            rows={2}
            className="resize-none"
          />

          {/* the essence of a recipe first — ingredients and
              instructions come before photo, tags and the favorite flag. */}
          <RecipeIngredientsSection
            ingredients={ingredients}
            errors={errors}
            onUpdate={updateIngredient}
            onRemove={removeIngredient}
            onAdd={addIngredient}
            onNameBlur={handleIngredientNameBlur}
          />

          <RecipeMarkdownEditor
            value={instructions}
            onChange={setInstructions}
          />

          {/* Photo — local file in create mode, direct upload in edit */}
          <div className="space-y-1.5">
            <p className={FIELD_LABEL_CLASS}>{t("form.photo")}</p>
            {imagePreview || initial?.image_url ? (
              <img
                src={imagePreview ?? initial?.image_url ?? ""}
                alt={t("form.photo")}
                className="w-full h-40 object-cover rounded-xl border border-border"
              />
            ) : (
              <div className="w-full h-40 rounded-xl border border-dashed border-border flex items-center justify-center text-on-muted text-sm">
                {t("form.photo_empty")}
              </div>
            )}
            <div className="flex items-center gap-2 mt-2">
              <label
                htmlFor="recipe-form-image"
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-on-secondary hover:text-on cursor-pointer"
              >
                {t("image.upload")}
                <input
                  id="recipe-form-image"
                  type="file"
                  accept="image/*"
                  className="hidden"
                  onChange={handleImageChange}
                  disabled={isUploading}
                />
              </label>
              {(imageFile || initial?.image_url) && (
                <Button
                  type="button"
                  variant="ghostDanger"
                  size="contentSm"
                  onClick={handleDeleteImage}
                  className="px-2 py-1 text-xs"
                >
                  {t("image.delete")}
                </Button>
              )}
            </div>
          </div>

          {/* Servings + PrepTime */}
          <div className="grid grid-cols-2 gap-3 items-end">
            <div className="flex items-end gap-2">
              <Input
                label={t("form.servings")}
                type="number"
                min={1}
                value={servings}
                onChange={(e) => setServings(e.target.value)}
                error={errors["servings"]}
              />
              {Number(servings) > 0 &&
                Number(servings) !== baseServingsRef.current && (
                  <Button
                    type="button"
                    onClick={() =>
                      scaleIngredients(
                        baseServingsRef.current,
                        Number(servings),
                      )
                    }
                    variant="ghost"
                    size="contentSm"
                    className="shrink-0 px-3 py-2 text-xs bg-primary-50 text-on hover:bg-primary-50 whitespace-nowrap"
                  >
                    {t("form.scale_ingredients")}
                  </Button>
                )}
            </div>
            <Input
              label={t("form.prep_time")}
              type="number"
              min={0}
              value={prepTime}
              onChange={(e) => setPrepTime(e.target.value)}
              placeholder="—"
              error={errors["prep_time_minutes"]}
            />
          </div>

          <Input
            label={t("form.tags")}
            value={tagsRaw}
            onChange={(e) => setTagsRaw(e.target.value)}
            placeholder={t("form.tags_placeholder")}
          />

          {/* Favorite */}
          <Checkbox
            checked={isFavorite}
            onChange={(e) => setIsFavorite(e.target.checked)}
            label={t("form.is_favorite")}
          />
        </div>

        <SheetFooter>
          <SheetActions>
            <Button
              type="button"
              variant="outline"
              onClick={requestLeave}
              disabled={isLoading}
            >
              {t("common:form.cancel")}
            </Button>
            <Button type="submit" isLoading={isLoading}>
              {isLoading ? t("form.creating") : t("common:form.save")}
            </Button>
          </SheetActions>
        </SheetFooter>
      </form>

      <ConfirmDialog
        open={discardConfirmOpen}
        title={t("form.discard_title")}
        message={t("form.discard_message")}
        variant="danger"
        confirmLabel={t("form.discard_confirm")}
        cancelLabel={t("form.discard_cancel")}
        onConfirm={() => {
          setDiscardConfirmOpen(false);
          onCancel();
        }}
        onCancel={() => setDiscardConfirmOpen(false)}
      />
    </>
  );
}
