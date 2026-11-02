import { lazy } from "react";
import { BarChart3 } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const StatsModuleSettingsPage = lazy(
  () => import("./pages/StatsModuleSettingsPage"),
);
const StatsPage = lazy(() => import("./pages/StatsPage"));

moduleRegistry.register({
  name: "stats",
  // The analytics toggles live on the generic settings screen; the sidebar
  // builds its entries from this list — without a declaration here, the
  // screen was reachable only by typing its address.
  settingsSections: [
    {
      title: "stats:navigation.settings",
      path: "modules/stats",
      icon: BarChart3,
      component: StatsModuleSettingsPage,
    },
  ],
  routes: [
    { path: "/inventory/stats", component: StatsPage, shell: "inventory" },
    {
      path: "/inventory/stats/analytics",
      component: StatsPage,
      shell: "inventory",
    },
    {
      path: "/inventory/stats/reconciliation",
      component: StatsPage,
      shell: "inventory",
    },
  ],
});
