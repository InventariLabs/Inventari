import { lazy } from "react";
import { Users } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const PartnersPage = lazy(() => import("./pages/PartnersPage"));

moduleRegistry.register({
  name: "partners",
  launcher: {
    displayName: "partners:title",
    description: "partners:launcher.description",
    icon: Users,
    color: "bg-rose-500",
    category: "business",
    order: 80,
  },
  routes: [{ path: "/partners", component: PartnersPage }],
  moduleNav: {
    basePath: "/partners",
    items: [
      {
        path: "/partners",
        icon: Users,
        labelKey: "partners:title",
        titleKey: "partners:title",
        subtitleKey: "partners:subtitle",
        order: 10,
      },
    ],
  },
  slots: [],
});
