import { lazy } from "react";
import { ShoppingCart } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";

// Lazy load pages for better performance
const ShoppingListsPage = lazy(() => import("./pages/ShoppingListsPage"));
const ShoppingListDetailPage = lazy(
  () => import("./pages/ShoppingListDetailPage"),
);

// Written for the item quick-action sheet — it already takes the `{ item }`
// that slot hands out — and never registered, so the only way to put an item
// on a list was to leave the item and go looking for one.
const AddToShoppingListButton = lazy(
  () => import("./components/AddToShoppingListButton"),
);
// What the inventory dashboard offers when lists are on: the replenish door
// and the modal behind it, and the active list beside the recent moves.
const ReplenishActionSlot = lazy(
  () => import("./components/slots/ReplenishActionSlot"),
);
const ReplenishSuggestionsModalSlot = lazy(
  () => import("./components/slots/ReplenishSuggestionsModalSlot"),
);
const DashboardShoppingListSlot = lazy(
  () => import("./components/slots/DashboardShoppingListSlot"),
);
const AddItemModalSlot = lazy(
  () => import("./components/slots/AddItemModalSlot"),
);

moduleRegistry.register({
  name: "shopping_lists",
  backgroundFeatures: {
    active_list: lazy(() => import("./components/BackgroundShoppingPanel")),
  },
  // Purchases can be received into the kept pantry without another module.
  standalone: {
    coreSections: {
      labels: "adopt",
      scan: "adopt",
      stats: "renounce",
      stock_takes: "renounce",
      archive: "adopt",
    },
    keepCoreNav: ["items", "storages", "categories"],
  },
  launcher: {
    displayName: "navigation.shopping",
    description: "shopping_lists:launcher.description",
    icon: ShoppingCart,
    color: "bg-pink-500",
    category: "business",
    order: 40,
  },
  moduleNav: {
    basePath: "/shopping-lists",
    items: [
      {
        path: "/shopping-lists",
        icon: ShoppingCart,
        labelKey: "navigation.shopping",
        titleKey: "shopping_lists:title",
        subtitleKey: "shopping_lists:subtitle",
        order: 10,
      },
    ],
  },
  slots: [
    {
      slot: "quick_action_extra",
      component: slotComponent(AddToShoppingListButton),
      priority: 20,
    },
    {
      slot: "dashboard_replenish_action",
      component: slotComponent(ReplenishActionSlot),
    },
    {
      slot: "dashboard_replenish_modal",
      component: slotComponent(ReplenishSuggestionsModalSlot),
    },
    {
      slot: "dashboard_activity_aside",
      component: slotComponent(DashboardShoppingListSlot),
    },
    {
      slot: "shopping_list_add_item",
      component: slotComponent(AddItemModalSlot),
    },
  ],
  routes: [
    {
      path: "/shopping-lists",
      component: ShoppingListsPage,
    },
    {
      path: "/shopping-lists/:id",
      component: ShoppingListDetailPage,
    },
  ],
});
