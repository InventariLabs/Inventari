import { Settings } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

moduleRegistry.register({
  name: "settings",
  launcher: {
    displayName: "common:navigation.settings",
    description: "common:navigation.settingsDescription",
    icon: Settings,
    color: "bg-gray-500",
    category: "system",
    order: 900,
    required: true,
    linkTo: "/settings",
  },
  // Routes are handled by SettingsShell in App.tsx.
  routes: [],
});
