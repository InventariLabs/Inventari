import { lazy } from "react";
import { Home } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const LauncherPage = lazy(() => import("./components/Launcher"));

moduleRegistry.register({
  name: "launcher",
  launcher: {
    displayName: "launcher:launcher.title",
    icon: Home,
    hidden: true, // not shown as a tile — it IS the tile grid
  },
  routes: [{ path: "/", component: LauncherPage, index: true }],
});
