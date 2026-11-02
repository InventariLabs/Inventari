import { lazy } from "react";
import { Apple } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";

const NutritionExtra = lazy(() => import("./components/FoodAndHealthExtra"));

const ProductInfoDisplay = lazy(
  () => import("./components/ProductInfoDisplay"),
);

const NutritionSummary = lazy(() => import("./components/NutritionSummary"));

const ProductNutritionOnItem = lazy(
  () => import("./components/ProductNutritionOnItemSlot"),
);

moduleRegistry.register({
  name: "nutrition",
  launcher: {
    displayName: "",
    icon: Apple,
    hidden: true,
  },
  routes: [],
  navOverrides: [],
  slots: [
    {
      slot: "item_edit_extra",
      component: slotComponent(NutritionExtra),
      priority: 10,
    },
    {
      slot: "quick_add_product_info",
      component: slotComponent(ProductInfoDisplay),
      priority: 10,
    },
    {
      slot: "stock_action_extra",
      component: slotComponent(NutritionSummary),
      priority: 10,
    },
    {
      slot: "item_detail_extra",
      component: slotComponent(ProductNutritionOnItem),
    },
  ],
});
