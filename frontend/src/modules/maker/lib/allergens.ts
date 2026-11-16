import { useTranslation } from "react-i18next";

/** The 14 allergens of EU Regulation 1169/2011, in the order every list
 *  shows them — the backend's keys. */
export const ALLERGEN_KEYS = [
  "gluten",
  "crustaceans",
  "eggs",
  "fish",
  "peanuts",
  "soy",
  "milk",
  "nuts",
  "celery",
  "mustard",
  "sesame",
  "sulphites",
  "lupin",
  "molluscs",
] as const;

export type AllergenKey = (typeof ALLERGEN_KEYS)[number];

const isAllergenKey = (key: string): key is AllergenKey =>
  (ALLERGEN_KEYS as readonly string[]).includes(key);

/** An allergen's name in the reader's language; an unknown key as it is.
 *  The keys are spelled out: the i18n gate reads the keys a file names. */
export function useAllergenName(): (key: string) => string {
  const { t } = useTranslation("maker");
  const names: Record<AllergenKey, string> = {
    gluten: t("labelling.allergens.gluten"),
    crustaceans: t("labelling.allergens.crustaceans"),
    eggs: t("labelling.allergens.eggs"),
    fish: t("labelling.allergens.fish"),
    peanuts: t("labelling.allergens.peanuts"),
    soy: t("labelling.allergens.soy"),
    milk: t("labelling.allergens.milk"),
    nuts: t("labelling.allergens.nuts"),
    celery: t("labelling.allergens.celery"),
    mustard: t("labelling.allergens.mustard"),
    sesame: t("labelling.allergens.sesame"),
    sulphites: t("labelling.allergens.sulphites"),
    lupin: t("labelling.allergens.lupin"),
    molluscs: t("labelling.allergens.molluscs"),
  };
  return (key) => (isAllergenKey(key) ? names[key] : key);
}
