import { useTranslation } from "react-i18next";
import { Leaf } from "lucide-react";
import { Card } from "@/module-sdk";
import type { Item } from "@/types";
import { NutritionValuesGrid } from "./NutritionValuesGrid";
import { productNutrition } from "../productNutrition";
import CommunityDataNote from "./CommunityDataNote";

/**
 * What is in the product, on the product's own page.
 *
 * The figures used to be reachable only through Edit → Food & Health Info,
 * so the page a person opens to see what a product is never said what it
 * contains. Nothing renders when the product carries no figures: an empty
 * nutrition card on a drill or a screwdriver would be noise.
 */
export default function ProductNutritionOnItemSlot({
  data,
}: {
  data: { item: Item };
}) {
  const { t } = useTranslation("nutrition");
  const values = productNutrition(data.item);
  if (!values) return null;

  return (
    <Card className="my-4 p-6 space-y-3">
      <h2 className="flex items-center gap-2 text-sm font-semibold text-on">
        <Leaf size={14} className="text-accent-600" aria-hidden />
        {t("productPage.title")}
      </h2>
      <NutritionValuesGrid values={values} />
      <CommunityDataNote metadata={data.item.metadata} />
    </Card>
  );
}
