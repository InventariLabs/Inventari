import { lazy } from "react";
import { KeyRound } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const ApiKeysPage = lazy(() => import("./pages/ApiKeysPage"));

moduleRegistry.register({
  name: "api_keys",
  launcher: {
    displayName: "api_keys:title",
    icon: KeyRound,
    category: "integrations",
    order: 210,
    hidden: true,
  },
  // Route handled through settingsSections (renders inside SettingsShell).
  routes: [],
  settingsSections: [
    {
      title: "api_keys:title",
      path: "api-keys",
      icon: KeyRound,
      component: ApiKeysPage,
      // The router asks for it on every route, listing included.
      permission: "org:settings:write",
    },
  ],
});
