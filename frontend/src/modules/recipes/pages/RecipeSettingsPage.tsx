import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Database, Scale, Home } from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/Tabs";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import IngredientDefaultsPage from "./IngredientDefaultsPage";
import UnitConversionsPage from "./UnitConversionsPage";
import AlwaysAtHomePage from "./AlwaysAtHomePage";

type RecipeSettingsTab = "nutrition" | "conversions" | "exclusions";

export default function RecipeSettingsPage() {
  const { t } = useTranslation("recipes");
  const { setHeader } = useModulePageHeader();
  const [activeTab, setActiveTab] = useState<RecipeSettingsTab>("nutrition");

  useEffect(() => {
    // The module bar carries a settings entry of its own now, so this screen
    // no longer needs to link out of itself to reach the real settings.
    setHeader({ title: t("settings.page_title") });
  }, [t, setHeader]);

  const tabs = [
    {
      id: "nutrition" as RecipeSettingsTab,
      label: t("settings.tab_nutrition"),
      icon: <Database size={15} />,
    },
    {
      id: "conversions" as RecipeSettingsTab,
      label: t("settings.tab_conversions"),
      icon: <Scale size={15} />,
    },
    {
      id: "exclusions" as RecipeSettingsTab,
      label: t("settings.tab_exclusions"),
      icon: <Home size={15} />,
    },
  ];

  return (
    <div className="space-y-6 animate-in fade-in duration-300 motion-reduce:animate-none">
      <Tabs
        defaultValue="nutrition"
        value={activeTab}
        onValueChange={(v) => setActiveTab(v as RecipeSettingsTab)}
      >
        <TabsList>
          {tabs.map((tab) => (
            <TabsTrigger key={tab.id} value={tab.id} icon={tab.icon}>
              {tab.label}
            </TabsTrigger>
          ))}
        </TabsList>

        <div className="mt-6">
          <TabsContent value="nutrition">
            <IngredientDefaultsPage />
          </TabsContent>

          <TabsContent value="conversions">
            <UnitConversionsPage />
          </TabsContent>

          <TabsContent value="exclusions">
            <AlwaysAtHomePage />
          </TabsContent>
        </div>
      </Tabs>
    </div>
  );
}
