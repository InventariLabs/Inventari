import { useTranslation } from "react-i18next";
import { Card } from "@/components/ui/Card";
import { ModuleSettingsScreen } from "@/modules/shared/components/ModuleSettingsScreen";
import { RecipesAiSettings } from "@/modules/recipes/components/RecipesAiSettings";

/**
 * Recipes settings, inside the module they configure.
 *
 * The module's own "settings" nav entry leads here, so the one entry named
 * settings opens the screen that is settings.
 */
export default function RecipesModuleSettingsPage() {
  const { t } = useTranslation("recipes");
  return (
    <div className="animate-in fade-in duration-300 motion-reduce:animate-none">
      <ModuleSettingsScreen
        moduleName="recipes"
        title={t("settings.module_title")}
        subtitle={t("settings.module_subtitle")}
      >
        <Card>
          <RecipesAiSettings />
        </Card>
      </ModuleSettingsScreen>
    </div>
  );
}
