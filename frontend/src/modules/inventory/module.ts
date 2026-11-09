import { lazy } from "react";
import {
  LayoutDashboard,
  ShoppingBag,
  Package,
  QrCode,
  Tag,
  Camera,
  ClipboardCheck,
  BarChart3,
  ArrowLeftRight,
  Boxes,
} from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import { MOVEMENT_RECORDING_MODULES } from "./constants/movementModules";
import { useInventoryStatusBadge } from "./hooks/useInventoryStatusBadge";
import { useInventoryActionItems } from "./hooks/useInventoryActionItems";

const InventoryDashboard = lazy(() => import("./pages/InventoryDashboard"));
const ItemsPage = lazy(() => import("./pages/ItemsPage"));
const AddItemPage = lazy(() => import("./pages/AddItemPage"));
const ItemDetailPage = lazy(() => import("./pages/ItemDetailPage"));
const CategoriesPage = lazy(() => import("./pages/CategoriesPage"));
const ScanPage = lazy(() => import("./pages/ScanPage"));
const ArchivedItemsPage = lazy(() => import("./pages/ArchivedItemsPage"));
const StockMovesPage = lazy(() => import("./pages/StockMovesPage"));

const LabelPoolPage = lazy(() => import("./pages/LabelPoolPage"));

const ItemEditModalSlot = lazy(
  () => import("./components/slots/ItemEditModalSlot"),
);
const StorageMovesSlot = lazy(
  () => import("./components/slots/StorageMovesSlot"),
);
const DocumentMovesSlot = lazy(
  () => import("./components/slots/DocumentMovesSlot"),
);
const StockLotPage = lazy(() => import("./pages/StockLotPage"));
const StockLevelsPage = lazy(() => import("./pages/StockLevelsPage"));
const StockLotsPage = lazy(() => import("./pages/StockLotsPage"));
const StockAsOfPage = lazy(() => import("./pages/StockAsOfPage"));

moduleRegistry.register({
  name: "inventory",
  backgroundFeatures: {
    stock: lazy(() => import("./components/BackgroundStockPanel")),
  },
  launcher: {
    displayName: "inventory:launcher.title",
    description: "inventory:launcher.description",
    icon: Package,
    category: "core",
    color: "bg-accent-500",
    order: 10,
    required: true,
  },
  moduleNav: {
    basePath: "/inventory",
    items: [
      {
        path: "/inventory",
        icon: LayoutDashboard,
        labelKey: "inventory:nav.overview",
        order: 10,
        mobileBar: true,
      },
      {
        path: "/inventory/items",
        icon: ShoppingBag,
        labelKey: "inventory:nav.items",
        titleKey: "items:title",
        subtitleKey: "items:subtitle",
        order: 20,
      },
      {
        path: "/inventory/locations",
        icon: Package,
        labelKey: "inventory:nav.storages",
        titleKey: "locations:title",
        subtitleKey: "locations:subtitle",
        order: 30,
      },
      {
        // The shelves and the ledger are the same conditional: an
        // organization with none of these modules keeps no quants either,
        // and its product list is the whole truth (ADR-004).
        path: "/inventory/stock",
        icon: Boxes,
        labelKey: "inventory:nav.stock",
        titleKey: "inventory:stock.title",
        subtitleKey: "inventory:stock.subtitle",
        order: 32,
        requiresModules: [...MOVEMENT_RECORDING_MODULES],
      },
      {
        // Every organization records its movements (ADR-004); the entry
        // is offered where a module that reads them is on (see
        // `constants/movementModules.ts`). The household profile carries
        // stock_takes, so a home without documents still has this screen —
        // it is where "why did the number change" is answered there.
        path: "/inventory/moves",
        icon: ArrowLeftRight,
        labelKey: "inventory:nav.moves",
        titleKey: "inventory:moves.title",
        subtitleKey: "inventory:moves.subtitle",
        order: 33,
        requiresModules: [...MOVEMENT_RECORDING_MODULES],
      },
      {
        path: "/inventory/stock-takes",
        icon: ClipboardCheck,
        labelKey: "navigation.stockTakes",
        titleKey: "stock_takes:title",
        subtitleKey: "stock_takes:subtitle",
        order: 35,
        requiresModules: ["stock_takes"],
      },
      {
        path: "/inventory/labels",
        icon: QrCode,
        labelKey: "inventory:nav.labels",
        titleKey: "labels:title",
        subtitleKey: "labels:subtitle",
        order: 40,
      },
      {
        path: "/inventory/stats",
        icon: BarChart3,
        labelKey: "stats:title",
        titleKey: "stats:title",
        subtitleKey: "stats:subtitle",
        order: 45,
        requiresModules: ["stats"],
      },
      {
        path: "/inventory/categories",
        icon: Tag,
        labelKey: "inventory:nav.categories",
        titleKey: "categories:title",
        subtitleKey: "categories:subtitle",
        order: 50,
      },
      {
        path: "/inventory/scan",
        icon: Camera,
        labelKey: "inventory:nav.scan",
        order: 60,
        mobileBar: true,
        showOnMobile: true,
      },
    ],
  },
  routes: [
    { path: "/inventory", component: InventoryDashboard, index: true },
    { path: "/inventory/items", component: ItemsPage },
    { path: "/inventory/items/archived", component: ArchivedItemsPage },
    { path: "/inventory/items/add", component: AddItemPage },
    { path: "/inventory/items/:id", component: ItemDetailPage },
    { path: "/inventory/stock", component: StockLevelsPage },
    { path: "/inventory/lots", component: StockLotsPage },
    { path: "/inventory/stock/as-of", component: StockAsOfPage },
    { path: "/inventory/lots/:id", component: StockLotPage },
    { path: "/inventory/moves", component: StockMovesPage },
    { path: "/inventory/labels", component: LabelPoolPage },
    { path: "/inventory/categories", component: CategoriesPage },
    { path: "/inventory/scan", component: ScanPage },
  ],
  // /labels/scan/:code is registered by the printing module as a flat route
  // (physical QR labels reference this path directly).
  slots: [
    {
      slot: "storage_item_edit_modal",
      component: slotComponent(ItemEditModalSlot),
    },
    {
      slot: "storage_moves",
      component: slotComponent(StorageMovesSlot),
    },
    {
      slot: "document_detail_extra",
      component: slotComponent(DocumentMovesSlot),
    },
  ],
  useStatusBadge: useInventoryStatusBadge,
  statusBadgePermission: "items:read",
  useActionItems: useInventoryActionItems,
});
