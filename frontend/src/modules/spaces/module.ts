import { lazy } from "react";
import { Database } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const StoragesPage = lazy(() => import("./pages/StoragesPage"));
const ArchivedStoragesPage = lazy(() => import("./pages/ArchivedStoragesPage"));

// The locations screens live here and render in the inventory shell, which
// links to them from its nav without importing them.
moduleRegistry.register({
  name: "spaces",
  launcher: {
    displayName: "",
    icon: Database,
    hidden: true,
  },
  routes: [
    {
      path: "/inventory/locations",
      component: StoragesPage,
      shell: "inventory",
    },
    {
      path: "/inventory/locations/zone/:zoneId",
      component: StoragesPage,
      shell: "inventory",
    },
    {
      path: "/inventory/locations/archived",
      component: ArchivedStoragesPage,
      shell: "inventory",
    },
    {
      path: "/inventory/locations/:id",
      component: StoragesPage,
      shell: "inventory",
    },
  ],
});
