import { useEffect, useRef, useState } from "react";
import {
  ChefHat,
  Clock,
  Flame,
  Camera,
  Trash2,
  Loader2,
  Edit2,
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Input } from "@/components/ui/Input";
import type { Recipe } from "@/modules/recipes/types/core";
import { formatMoney, formatNumberLocale } from "@/utils/formatters";

interface RecipeHeroCardProps {
  recipe: Recipe;
  nutritionCalories?: number;
  estimatedCost?: number;
  currency?: string;
  uploadImageMutation: { isPending: boolean };
  deleteImageMutation: { isPending: boolean };
  onImageUpload: (e: React.ChangeEvent<HTMLInputElement>) => void;
  onDeleteImage: () => void;
  onEditRequest: () => void;
  tagInput: string;
  onTagInputChange: (v: string) => void;
  onAddTag: (tag: string) => void;
  /** Whether to offer the cover photo controls and the tag field. */
  canWrite?: boolean;
  t: (key: string, options?: Record<string, unknown>) => string;
}

export function RecipeHeroCard({
  recipe,
  nutritionCalories,
  estimatedCost,
  currency,
  uploadImageMutation,
  deleteImageMutation,
  onImageUpload,
  onDeleteImage,
  onEditRequest,
  tagInput,
  onTagInputChange,
  onAddTag,
  canWrite = true,
  t,
}: RecipeHeroCardProps) {
  const imageInputRef = useRef<HTMLInputElement>(null);
  // A cover that will not load leaves a frame with nothing in it and no
  // reason given. Covers are the app's own files now, so this is rare — but
  // a file can still be missing, and an empty frame explains nothing.
  const [coverBroken, setCoverBroken] = useState(false);
  useEffect(() => setCoverBroken(false), [recipe.image_url]);
  const hasCover = Boolean(recipe.image_url) && !coverBroken;

  return (
    <Card className="p-0 overflow-hidden shadow-sm">
      <div className="relative">
        {hasCover ? (
          <img
            src={recipe.image_url ?? ""}
            alt={recipe.name}
            loading="lazy"
            onError={() => setCoverBroken(true)}
            // A photo's shape, not a strip. A fixed 176px band on a wide card
            // is nearer 3:1 than anything a camera produces, so every cover
            // was shown as a slice through its middle — which is how one
            // picture came to look like two side by side.
            className="w-full aspect-[16/9] max-h-72 object-cover"
          />
        ) : (
          <div className="w-full">
            {coverBroken && (
              <p className="flex items-center justify-center gap-1.5 px-3 pt-3 text-xs text-on-muted">
                <AlertTriangle size={12} className="shrink-0" />
                {t("recipes:image.unavailable")}
              </p>
            )}
            {canWrite && (
              <Button
                size="content"
                type="button"
                variant="secondary"
                onClick={() => imageInputRef.current?.click()}
                disabled={uploadImageMutation.isPending}
                className="w-full h-24 bg-surface-inset/60 hover:bg-surface-inset text-on-secondary hover:text-on text-sm font-medium"
              >
                {uploadImageMutation.isPending ? (
                  <Loader2 size={16} className="animate-spin" />
                ) : (
                  <Camera size={16} />
                )}
                {t("recipes:image.upload")}
              </Button>
            )}
          </div>
        )}
        {hasCover && canWrite && (
          <div className="absolute top-2 right-2 flex gap-1">
            <Button
              size="icon"
              variant="ghost"
              onClick={() => imageInputRef.current?.click()}
              disabled={uploadImageMutation.isPending}
              className="bg-surface-card/80 backdrop-blur-sm"
              title={t("recipes:image.upload")}
              aria-label={t("recipes:image.upload")}
            >
              {uploadImageMutation.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Camera size={16} />
              )}
            </Button>
            <Button
              size="icon"
              variant="ghostDanger"
              onClick={onDeleteImage}
              disabled={deleteImageMutation.isPending}
              className="bg-surface-card/80 backdrop-blur-sm"
              title={t("recipes:image.delete")}
              aria-label={t("recipes:image.delete")}
            >
              {deleteImageMutation.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Trash2 size={16} />
              )}
            </Button>
          </div>
        )}
        <input
          ref={imageInputRef}
          type="file"
          accept="image/*"
          className="hidden"
          onChange={onImageUpload}
        />
      </div>
      <div className="p-5">
        <div className="flex items-center gap-3 text-xs text-on-secondary">
          {nutritionCalories != null && nutritionCalories > 0 && (
            <span className="flex items-center gap-1">
              <Flame size={12} className="text-amber-500" />
              <span className="font-medium text-on-secondary">
                {/* A batch's calories run to seven digits; `Math.round`
                    printed them without a separator in any language. */}
                {formatNumberLocale(nutritionCalories, 0)}
              </span>
              kcal {t("recipes:recipe.per_serving")}
            </span>
          )}
          {estimatedCost != null && (
            <span className="flex items-center gap-1 text-on-secondary">
              <span className="font-medium text-on-secondary">
                {/* No "PLN" fallback: an organization on USD was shown
                    zlotys on this card. formatMoney renders "0.00 ?" when
                    the currency is unknown, which is honest. */}
                {formatMoney(estimatedCost, currency)}
              </span>
            </span>
          )}
        </div>

        <div className="flex flex-wrap gap-2 mt-3">
          <div className="flex items-center gap-1 text-sm text-on-secondary">
            <ChefHat size={14} className="text-on-muted" />
            {t("recipes:recipe.servings", { count: recipe.servings })}
          </div>
          {recipe.prep_time_minutes && (
            <div className="flex items-center gap-1 text-sm text-on-secondary">
              <Clock size={14} className="text-on-muted" />
              {t("recipes:recipe.prep_time", {
                minutes: recipe.prep_time_minutes,
              })}
            </div>
          )}
        </div>

        {/* Allergens (EU 1169/2011) — union of ingredient allergens */}
        {recipe.allergens && recipe.allergens.length > 0 ? (
          <div className="flex flex-wrap items-center gap-1.5 mt-3">
            <span className="inline-flex items-center gap-1 text-xs font-medium text-amber-800 uppercase tracking-wide shrink-0">
              <AlertTriangle size={11} className="text-amber-600" />
              {t("recipes:allergens.title")}:
            </span>
            {recipe.allergens.map((key) => (
              <Badge key={key} variant="warning">
                {t(`recipes:allergens.${key}`)}
              </Badge>
            ))}
            <p className="basis-full text-xs text-on-muted">
              {t("recipes:allergens.note")}
            </p>
          </div>
        ) : (
          <p className="mt-3 text-xs text-on-muted">
            {t("recipes:allergens.none_marked")}
          </p>
        )}

        {recipe.tags?.length ? (
          <div className="flex flex-wrap gap-1.5 items-center mt-3">
            {recipe.tags.map((tag) => (
              <Badge key={tag} variant="outline">
                {tag}
              </Badge>
            ))}
            {canWrite && (
              <Button
                size="iconSm"
                variant="ghost"
                onClick={onEditRequest}
                aria-label={t("recipes:a11y.editTags")}
                title={t("recipes:a11y.editTags")}
                className="rounded-full"
              >
                <Edit2 size={16} />
              </Button>
            )}
            {canWrite && (
              <form
                onSubmit={(e) => {
                  e.preventDefault();
                  onAddTag(tagInput);
                }}
                className="inline-flex flex-1 min-w-40"
              >
                <Input
                  type="text"
                  aria-label={t("recipes:tags_manager.add_placeholder", {
                    defaultValue: "+",
                  })}
                  value={tagInput}
                  onChange={(e) => onTagInputChange(e.target.value)}
                  placeholder={t("recipes:tags_manager.add_placeholder", {
                    defaultValue: "+",
                  })}
                  className="w-full text-xs border-dashed rounded-full px-2.5 py-0.5 h-auto bg-transparent focus:border-primary-300 placeholder:text-on-muted"
                />
              </form>
            )}
          </div>
        ) : canWrite ? (
          <div className="mt-3">
            <form
              onSubmit={(e) => {
                e.preventDefault();
                onAddTag(tagInput);
              }}
              className="inline-flex"
            >
              <Input
                // `focus-within`, not `focus`: the box is a div and never
                // takes focus itself, so the field widens when the input
                // inside it does.
                wrapperClassName="w-32 focus-within:w-44 transition-[width]"
                type="text"
                value={tagInput}
                onChange={(e) => onTagInputChange(e.target.value)}
                aria-label={t("recipes:tags_manager.add_placeholder")}
                placeholder={t("recipes:tags_manager.add_placeholder")}
                className="text-xs border-dashed rounded-full px-2.5 py-1 h-auto bg-transparent focus:border-primary-300 placeholder:text-on-muted"
              />
            </form>
          </div>
        ) : null}
      </div>
    </Card>
  );
}
