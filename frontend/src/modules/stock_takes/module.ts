import { lazy } from "react";
import { ClipboardCheck } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const StockTakesPage = lazy(() => import("./pages/StockTakesPage"));
const CountLocationPage = lazy(() => import("./pages/CountLocationPage"));
const StockTakeCountingPage = lazy(
  () => import("./pages/StockTakeCountingPage"),
);
const StockTakeReportPage = lazy(() => import("./pages/StockTakeReportPage"));

moduleRegistry.register({
  name: "stock_takes",
  // The counting screens live here and render in the inventory shell
  // (`shell: "inventory"`), which links to them from its nav without
  // importing them; mounted only while this module is on. Keep this module's
  // own scope at /stock-takes: a nested /inventory/stock-takes/* scope would
  // shadow those screens with its 404. The canonical entry opens the counting
  // list, adopted in focus.
  launcher: {
    displayName: "modules:modules.stock_takes.name",
    icon: ClipboardCheck,
    hidden: true,
    linkTo: "/inventory/stock-takes",
  },
  moduleNav: { basePath: "/stock-takes", items: [] },
  routes: [
    {
      path: "/inventory/stock-takes",
      component: StockTakesPage,
      shell: "inventory",
    },
    {
      path: "/inventory/stock-takes/count",
      component: CountLocationPage,
      shell: "inventory",
    },
    {
      path: "/inventory/stock-takes/:id/counting",
      component: StockTakeCountingPage,
      shell: "inventory",
    },
    {
      path: "/inventory/stock-takes/:id/report",
      component: StockTakeReportPage,
      shell: "inventory",
    },
  ],
});
