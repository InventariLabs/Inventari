import { useTranslation } from "react-i18next";
import { isFromOpenFoodFacts } from "../productNutrition";

/**
 * One line under nutrition figures that came from Open Food Facts: a
 * community database, so the values are an estimate to check against the label.
 */
export default function CommunityDataNote({
  metadata,
}: {
  metadata: Record<string, unknown> | null | undefined;
}) {
  const { t } = useTranslation("nutrition");
  if (!isFromOpenFoodFacts(metadata)) return null;
  return (
    <p className="text-[10px] text-on-muted" data-testid="community-data-note">
      {t("source.communityNote")}
    </p>
  );
}
