import { lazy } from "react";
import {
  CalendarCheck,
  Camera,
  Columns3,
  FileCheck,
  Gauge,
  History,
  LayoutDashboard,
  Settings2,
  Tags,
} from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import { ApprovalsQueueBadge } from "./components/ApprovalsQueueBadge";
import { useDocumentsStatusBadge } from "./hooks/useDocumentsStatusBadge";

const DocumentsPage = lazy(() => import("./pages/DocumentsPage"));
const DocumentDetailPage = lazy(() => import("./pages/DocumentDetailPage"));
const DocumentsTodoPage = lazy(() => import("./pages/DocumentsTodoPage"));
const DocumentApprovalsPage = lazy(
  () => import("./pages/DocumentApprovalsPage"),
);
const DocumentHistoryPage = lazy(() => import("./pages/DocumentHistoryPage"));
const DocumentRegisterPage = lazy(() => import("./pages/DocumentRegisterPage"));
const DocumentProfileSettingsPage = lazy(
  () => import("./pages/DocumentProfileSettingsPage"),
);
const DocumentsLegacyRedirect = lazy(
  () => import("./pages/DocumentsLegacyRedirect"),
);
const DocumentsBoardPage = lazy(() => import("./pages/DocumentsBoardPage"));
const DocumentScanPage = lazy(() => import("./pages/DocumentScanPage"));
const ReceiveGoodsPage = lazy(() => import("./pages/ReceiveGoodsPage"));
const IssueGoodsPage = lazy(() => import("./pages/IssueGoodsPage"));
const MoveGoodsPage = lazy(() => import("./pages/MoveGoodsPage"));
const DocumentsTemplatesPage = lazy(
  () => import("./pages/DocumentsTemplatesPage"),
);
const InventoryPeriodPanel = lazy(
  () => import("./components/InventoryPeriodPanel"),
);
const PutawayRulesPage = lazy(() => import("./pages/PutawayRulesPage"));
const DocumentsLocationsPage = lazy(
  () => import("./pages/DocumentsLocationsPage"),
);
const OccupancyPage = lazy(() => import("./pages/OccupancyPage"));
const StorageTreeOccupancySlot = lazy(
  () => import("./components/slots/StorageTreeOccupancySlot"),
);
const PutawayCapacityOnItemSlot = lazy(
  () => import("./components/slots/PutawayCapacityOnItemSlot"),
);
const ProductTaxRateSlot = lazy(
  () => import("./components/slots/ProductTaxRateSlot"),
);
const StorageWarehouseStripSlot = lazy(
  () => import("./components/slots/StorageWarehouseStripSlot"),
);

moduleRegistry.register({
  name: "warehouse",
  // Warehouse documents keep the catalogue, locations and stock journal they change.
  standalone: {
    coreSections: {
      labels: "adopt",
      scan: "adopt",
      stats: "adopt",
      stock_takes: "renounce",
      archive: "adopt",
    },
    keepCoreNav: ["items", "storages", "categories", "stock", "moves"],
  },
  launcher: {
    displayName: "warehouse:launcher.title",
    description: "warehouse:launcher.description",
    icon: FileCheck,
    color: "bg-cyan-600",
    category: "business",
    order: 70,
    // The module opens on the work of the floor, not on the register of documents
    // the office edits. The document list is the next item in the module bar.
    linkTo: "/warehouse/todo",
  },
  useStatusBadge: useDocumentsStatusBadge,
  statusBadgePermission: "warehouse:read",
  routes: [
    // The list this module used to open on now lives in History; the old
    // address keeps working for bookmarks, query string included.
    { path: "/warehouse", component: DocumentsLegacyRedirect },
    // The former document list stays reachable from the office panel in History:
    // it is where the type, status and date filters and the opening-stock
    // import live.
    { path: "/warehouse/all", component: DocumentsPage },
    { path: "/warehouse/todo", component: DocumentsTodoPage },
    { path: "/warehouse/board", component: DocumentsBoardPage },
    { path: "/warehouse/approvals", component: DocumentApprovalsPage },
    { path: "/warehouse/history", component: DocumentHistoryPage },
    { path: "/warehouse/register", component: DocumentRegisterPage },
    { path: "/warehouse/scan", component: DocumentScanPage },
    { path: "/warehouse/receive", component: ReceiveGoodsPage },
    { path: "/warehouse/issue", component: IssueGoodsPage },
    { path: "/warehouse/move", component: MoveGoodsPage },
    { path: "/warehouse/templates", component: DocumentsTemplatesPage },
    { path: "/warehouse/putaway-rules", component: PutawayRulesPage },
    { path: "/warehouse/location-settings", component: DocumentsLocationsPage },
    { path: "/warehouse/occupancy", component: OccupancyPage },
    // Configuration keeps the address the settings screen has always had:
    // the tab is renamed, the old bookmark keeps landing on it.
    { path: "/warehouse/settings", component: DocumentProfileSettingsPage },
    { path: "/warehouse/profile", component: DocumentsLegacyRedirect },
    { path: "/warehouse/periods", component: InventoryPeriodPanel },
    { path: "/warehouse/documents/:id", component: DocumentDetailPage },
  ],
  settingsSections: [],
  moduleNav: {
    basePath: "/warehouse",
    items: [
      {
        path: "/warehouse/todo",
        icon: LayoutDashboard,
        labelKey: "warehouse:navigation.start",
        titleKey: "warehouse:start.title",
        subtitleKey: "warehouse:start.subtitle",
        order: 10,
        mobileOrder: 10,
        mobileBar: true,
        showOnMobile: true,
        // Approvals are tasks on this screen; the count tells the reader
        // there is a decision waiting without a tab of its own.
        Badge: ApprovalsQueueBadge,
      },
      {
        path: "/warehouse/board",
        icon: Columns3,
        labelKey: "warehouse:navigation.board",
        order: 20,
        // The board is the view of the desk; a phone keeps Start,
        // Scan and History.
        showOnMobile: false,
      },
      {
        path: "/warehouse/history",
        icon: History,
        labelKey: "warehouse:navigation.history",
        titleKey: "warehouse:history.title",
        subtitleKey: "warehouse:history.subtitle",
        order: 30,
        mobileOrder: 30,
        mobileBar: true,
        showOnMobile: true,
      },
      {
        path: "/warehouse/scan",
        icon: Camera,
        labelKey: "warehouse:navigation.scan",
        order: 40,
        mobileOrder: 20,
        mobileBar: true,
        showOnMobile: true,
        // Scanning is the middle tab of a phone; on a desktop it opens from the
        // action a person is already in, and from the related screens on Start.
        showOnDesktop: false,
      },
      {
        path: "/warehouse/settings",
        icon: Settings2,
        labelKey: "warehouse:navigation.configuration",
        titleKey: "warehouse:settings.moduleTitle",
        subtitleKey: "warehouse:settings.moduleSubtitle",
        // Configuration sits last in the module bar (UI_GUIDELINES §2.14a).
        order: 90,
        mobileOrder: 90,
        // On a phone it is one entry in the module menu, after the three
        // working tabs.
        showOnMobile: true,
      },
      {
        // Not a tab: the former document list is reached from the office panel
        // in History, and this entry only names the page for the shell.
        path: "/warehouse/all",
        icon: FileCheck,
        labelKey: "warehouse:navigation.documents",
        titleKey: "warehouse:title",
        subtitleKey: "warehouse:subtitle",
        order: 80,
        showOnDesktop: false,
        showOnMobile: false,
      },
      {
        // Browsing the shelves with their codes and printing their labels is
        // daily work (a new shelf, a torn sticker), so it sits in the bar
        // rather than behind Configuration. A phone reaches it from the module
        // menu, after the three working tabs.
        path: "/warehouse/location-settings",
        icon: Tags,
        labelKey: "warehouse:navigation.codesAndLabels",
        titleKey: "warehouse:putaway.locations.title",
        subtitleKey: "warehouse:putaway.locations.subtitle",
        order: 50,
        mobileOrder: 50,
        showOnMobile: true,
      },

      {
        // Not a tab either: Configuration links here, and the entry names the
        // page for the shell.
        path: "/warehouse/occupancy",
        icon: Gauge,
        labelKey: "warehouse:occupancy.navLabel",
        titleKey: "warehouse:occupancy.title",
        subtitleKey: "warehouse:occupancy.subtitle",
        order: 83,
        showOnDesktop: false,
        showOnMobile: false,
      },
      {
        // The month close is reached from the office panel in History.
        path: "/warehouse/periods",
        icon: CalendarCheck,
        labelKey: "warehouse:periods.title",
        titleKey: "warehouse:periods.title",
        subtitleKey: "warehouse:periods.subtitle",
        order: 82,
        showOnDesktop: false,
        showOnMobile: false,
      },
    ],
  },
  slots: [
    {
      slot: "item_detail_extra",
      component: slotComponent(PutawayCapacityOnItemSlot),
    },
    {
      slot: "item_edit_extra",
      component: slotComponent(ProductTaxRateSlot),
    },
    {
      slot: "storage_tree_row_extra",
      component: slotComponent(StorageTreeOccupancySlot),
    },
    {
      slot: "storage_warehouse_strip",
      component: slotComponent(StorageWarehouseStripSlot),
    },
  ],
});
