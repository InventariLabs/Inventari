import { Fragment } from "react";
import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";
import { formatQuantityLocale } from "@/utils/formatters";
import { DerivedAllergens } from "@/modules/maker/components/LabelFactsSlot";
import { useRecipeLabel } from "@/modules/maker/hooks/useLabelling";
import { useAllergenName } from "@/modules/maker/lib/allergens";
import type {
  LabelIngredient,
  LabelNutrition,
  MakerRecipe,
  RecipeLabel,
} from "@/modules/maker/types/maker";

const HEADING =
  "text-xs uppercase tracking-widest text-on-muted font-medium mb-2";

/** The list as a label writes it: allergens emphasised, a made
 *  ingredient's own list in brackets after it. */
function IngredientList({ ingredients }: { ingredients: LabelIngredient[] }) {
  return (
    <>
      {ingredients.map((ingredient, index) => (
        <Fragment key={ingredient.template_id}>
          {index > 0 && ", "}
          {ingredient.emphasised ? (
            <strong className="font-semibold text-on">{ingredient.name}</strong>
          ) : (
            ingredient.name
          )}
          {(ingredient.children?.length ?? 0) > 0 && (
            <>
              {" ("}
              <IngredientList ingredients={ingredient.children ?? []} />
              {")"}
            </>
          )}
        </Fragment>
      ))}
    </>
  );
}

/** What the list could not settle: unchecked allergens, unweighed lines. */
function Doubts({ label }: { label: RecipeLabel }) {
  const { t } = useTranslation("maker");
  const name = useAllergenName();
  if (label.unchecked.length === 0 && label.unweighed.length === 0) return null;
  return (
    <div
      className="text-sm text-on-warning bg-amber-100 rounded-lg px-3 py-2 space-y-1"
      data-testid="maker-label-doubts"
    >
      {label.unchecked.length > 0 && (
        <p>
          {t("labelling.tab.unchecked")}{" "}
          {label.unchecked
            .map((each) =>
              each.suggested_allergens.length > 0
                ? t("labelling.tab.uncheckedSuggests", {
                    name: each.name,
                    allergens: each.suggested_allergens.map(name).join(", "),
                  })
                : each.name,
            )
            .join("; ")}
        </p>
      )}
      {label.unweighed.length > 0 && (
        <p>
          {t("labelling.tab.unweighed", {
            names: label.unweighed.map((each) => each.name).join(", "),
          })}
        </p>
      )}
    </div>
  );
}

/** The declaration's names for its figures, in the regulation's order. */
function useNutrientNames(): Record<string, string> {
  const { t } = useTranslation("maker");
  return {
    energy_kcal: t("labelling.nutrients.energy"),
    fat: t("labelling.nutrients.fat"),
    saturates: t("labelling.nutrients.saturates"),
    carbohydrate: t("labelling.nutrients.carbohydrate"),
    sugars: t("labelling.nutrients.sugars"),
    protein: t("labelling.nutrients.protein"),
    salt: t("labelling.nutrients.salt"),
  };
}

const GRAMS: Array<{ key: keyof LabelNutrition; sub?: boolean }> = [
  { key: "fat" },
  { key: "saturates", sub: true },
  { key: "carbohydrate" },
  { key: "sugars", sub: true },
  { key: "protein" },
  { key: "salt" },
];

function NutritionRows({ nutrition }: { nutrition: LabelNutrition }) {
  const { t } = useTranslation("maker");
  const names = useNutrientNames();
  const amount = (value: string | null | undefined, unit: string) =>
    value === null || value === undefined
      ? null
      : `${formatQuantityLocale(value, 2)} ${unit}`;
  const energy =
    nutrition.energy_kj != null && nutrition.energy_kcal != null
      ? `${amount(nutrition.energy_kj, "kJ")} / ${amount(nutrition.energy_kcal, "kcal")}`
      : null;
  const rows = [
    { key: "energy_kcal", label: names.energy_kcal, sub: false, value: energy },
    ...GRAMS.map(({ key, sub }) => ({
      key,
      label: names[key],
      sub: Boolean(sub),
      value: amount(nutrition[key] as string | null | undefined, "g"),
    })),
  ];
  return (
    <tbody>
      {rows.map((row) => (
        <tr key={row.key} className="border-b border-border last:border-0">
          <th
            scope="row"
            className={`py-1 text-left font-normal text-on-secondary ${row.sub ? "pl-4" : ""}`}
          >
            {row.label}
          </th>
          <td className="py-1 text-right tabular-nums text-on">
            {row.value ?? t("labelling.tab.notKnown")}
          </td>
        </tr>
      ))}
    </tbody>
  );
}

/** The figures' names inside a sentence ("Seeds has no figure for salt"). */
function useFigureNames(): Record<string, string> {
  const { t } = useTranslation("maker");
  return {
    energy_kcal: t("labelling.figures.energy"),
    fat: t("labelling.figures.fat"),
    saturates: t("labelling.figures.saturates"),
    carbohydrate: t("labelling.figures.carbohydrate"),
    sugars: t("labelling.figures.sugars"),
    protein: t("labelling.figures.protein"),
    salt: t("labelling.figures.salt"),
  };
}

function NutritionTable({ label }: { label: RecipeLabel }) {
  const { t } = useTranslation("maker");
  const names = useFigureNames();
  const nutrition = label.nutrition;
  if (!nutrition) {
    return (
      <p
        className="text-sm text-on-muted"
        data-testid="maker-label-no-nutrition"
      >
        {t("labelling.tab.nutritionNone")}
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <p className="text-sm text-on-secondary">
        {label.yield_weight_g
          ? t("labelling.tab.perYield", {
              weight: formatQuantityLocale(label.yield_weight_g, 0),
            })
          : t("labelling.tab.yieldUnknown")}
      </p>
      <table
        className="w-full max-w-sm text-sm"
        data-testid="maker-label-nutrition"
      >
        <NutritionRows nutrition={nutrition} />
      </table>
      {nutrition.missing.length > 0 && (
        <p
          className="text-sm text-on-warning"
          data-testid="maker-label-missing"
        >
          {t("labelling.tab.missing")}{" "}
          {nutrition.missing
            .map((gap) =>
              t("labelling.tab.missingLine", {
                name: gap.name,
                nutrients: gap.nutrients
                  .map((key) => names[key] ?? key)
                  .join(", "),
              }),
            )
            .join("; ")}
        </p>
      )}
    </div>
  );
}

/**
 * The made product's label as this recipe computes it: the ingredient list
 * heaviest first, the allergens with the ingredients that bring them, what
 * it may contain, and the nutrition per 100 g. Every part is computed from
 * the recipe and its ingredients' cards, and the screen says it is the
 * producer's to check.
 */
export function LabelTab({ recipe }: { recipe: MakerRecipe }) {
  const { t } = useTranslation("maker");
  const {
    data: label,
    isLoading,
    isError,
    refetch,
  } = useRecipeLabel(recipe.id);

  if (isError) {
    return (
      <Card className="p-4">
        <QueryError onRetry={() => void refetch()} />
      </Card>
    );
  }
  if (isLoading || !label) {
    return (
      <Card className="p-4">
        <p className="text-center py-8 text-on-muted text-sm">
          {t("detail.loading")}
        </p>
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="maker-recipe-label">
      <p className="text-sm text-on-secondary">{t("labelling.computedNote")}</p>
      <Card className="p-4 space-y-3">
        <h2 className={HEADING}>{t("labelling.tab.ingredients")}</h2>
        {label.ingredients.length > 0 ? (
          <p
            className="text-sm text-on-secondary"
            data-testid="maker-label-list"
          >
            <IngredientList ingredients={label.ingredients} />
          </p>
        ) : (
          <p className="text-sm text-on-muted">
            {t("labelling.tab.noIngredients")}
          </p>
        )}
        <Doubts label={label} />
      </Card>
      <Card className="p-4 space-y-3">
        <h2 className={HEADING}>{t("labelling.contains")}</h2>
        {label.allergens.length > 0 ? (
          <DerivedAllergens
            entries={label.allergens}
            testId="maker-label-allergens"
          />
        ) : (
          <p className="text-sm text-on-muted">
            {t("labelling.tab.noAllergens")}
          </p>
        )}
        {label.may_contain.length > 0 && (
          <>
            <h3 className={HEADING}>{t("labelling.mayContain")}</h3>
            <DerivedAllergens
              entries={label.may_contain}
              testId="maker-label-may-contain-list"
            />
          </>
        )}
      </Card>
      <Card className="p-4 space-y-3">
        <h2 className={HEADING}>{t("labelling.tab.nutrition")}</h2>
        <NutritionTable label={label} />
      </Card>
    </div>
  );
}
