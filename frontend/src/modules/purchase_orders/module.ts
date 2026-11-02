import { lazy } from "react";
import { Receipt, FileText, Settings, Coins, RefreshCw } from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";

const PurchaseOrdersPage = lazy(() => import("./pages/PurchaseOrdersPage"));
const PurchaseOrderDetailPage = lazy(
  () => import("./pages/PurchaseOrderDetailPage"),
);
const LinkedReceiptsPage = lazy(() => import("./pages/LinkedReceiptsPage"));
const PurchaseOrdersTemplatesPage = lazy(
  () => import("./pages/PurchaseOrdersTemplatesPage"),
);
const POSettingsPage = lazy(() => import("./pages/POSettingsPage"));
const PricelistPage = lazy(() => import("./pages/PricelistPage"));
const ReorderRulesPage = lazy(() => import("./pages/ReorderRulesPage"));

moduleRegistry.register({
  name: "purchase_orders",
  launcher: {
    displayName: "purchase_orders:launcher.title",
    description: "purchase_orders:launcher.description",
    icon: Receipt,
    color: "bg-violet-500",
    category: "business",
    order: 60,
  },
  moduleNav: {
    basePath: "/purchase-orders",
    items: [
      {
        path: "/purchase-orders",
        icon: Receipt,
        labelKey: "purchase_orders:navigation.purchaseOrders",
        subtitleKey: "purchase_orders:subtitle",
        order: 10,
        // A phone shows the working screens in the bar and the rest under
        // More. With no bar flag the module had one item left and no
        // navigation at all (the bar needs more than one).
        mobileBar: true,
      },
      {
        path: "/purchase-orders/templates",
        icon: FileText,
        labelKey: "purchase_orders:navigation.templates",
        titleKey: "purchase_orders:templates.title",
        subtitleKey: "purchase_orders:templates.subtitle",
        order: 20,
      },
      {
        path: "/purchase-orders/settings",
        icon: Settings,
        labelKey: "purchase_orders:navigation.settings",
        titleKey: "purchase_orders:settings.pageTitle",
        subtitleKey: "purchase_orders:settings.pageSubtitle",
        // Settings sit last in the module bar, always (UI_GUIDELINES §2.14).
        order: 90,
      },
      {
        path: "/purchase-orders/pricelist",
        icon: Coins,
        labelKey: "purchase_orders:navigation.pricelist",
        titleKey: "purchase_orders:pricelist.pageTitle",
        subtitleKey: "purchase_orders:pricelist.pageSubtitle",
        order: 40,
        mobileBar: true,
      },
      {
        path: "/purchase-orders/reorder-rules",
        icon: RefreshCw,
        labelKey: "purchase_orders:navigation.reorderRules",
        titleKey: "purchase_orders:reorderRules.pageTitle",
        subtitleKey: "purchase_orders:reorderRules.pageSubtitle",
        order: 50,
        mobileBar: true,
      },
    ],
  },
  routes: [
    {
      path: "/purchase-orders",
      component: PurchaseOrdersPage,
    },
    {
      path: "/purchase-orders/templates",
      component: PurchaseOrdersTemplatesPage,
    },
    {
      path: "/purchase-orders/settings",
      component: POSettingsPage,
    },
    {
      path: "/purchase-orders/pricelist",
      component: PricelistPage,
    },
    {
      path: "/purchase-orders/reorder-rules",
      component: ReorderRulesPage,
    },
    {
      path: "/purchase-orders/:id",
      component: PurchaseOrderDetailPage,
    },
    {
      path: "/purchase-orders/:id/linked-receipts",
      component: LinkedReceiptsPage,
    },
  ],
});
