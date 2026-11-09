import { lazy } from "react";
import {
  Monitor,
  ClipboardList,
  LayoutDashboard,
  MapPin,
  Tag,
  FileText,
  User,
  Settings,
} from "lucide-react";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { SearchResult } from "@/lib/moduleRegistry";
import { equipmentApi } from "@/modules/equipment/api/equipment";
import { useEquipmentStatusBadge } from "./hooks/useEquipmentStatusBadge";

const EquipmentDashboardPage = lazy(
  () => import("./pages/EquipmentDashboardPage"),
);

const AddEquipmentPage = lazy(() => import("./pages/AddEquipmentPage"));
const EquipmentSettingsPage = lazy(
  () => import("./pages/EquipmentSettingsPage"),
);
const AssetListPage = lazy(() => import("./pages/AssetListPage"));
const AssetDetailPage = lazy(() => import("./pages/AssetDetailPage"));
const EquipmentCategoriesPage = lazy(
  () => import("./pages/EquipmentCategoriesPage"),
);
const TemplatesPage = lazy(() => import("./pages/TemplatesPage"));
const EquipmentLocationsPage = lazy(
  () => import("./pages/EquipmentLocationsPage"),
);

const AuditCampaignsPage = lazy(() => import("./pages/AuditCampaignsPage"));
const CampaignDetailPage = lazy(() => import("./pages/CampaignDetailPage"));
const MyAssetsPage = lazy(() => import("./pages/MyAssetsPage"));

moduleRegistry.register({
  name: "equipment",
  launcher: {
    displayName: "equipment:launcher.title",
    description: "equipment:launcher.description",
    icon: Monitor,
    category: "business",
    color: "bg-primary-500",
    order: 20,
  },
  moduleNav: {
    basePath: "/equipment",
    items: [
      {
        path: "/equipment",
        icon: LayoutDashboard,
        labelKey: "equipment:nav.overview",
        titleKey: "equipment:dashboard.title",
        order: 10,
        mobileBar: true,
      },
      {
        path: "/equipment/assets",
        icon: Monitor,
        labelKey: "equipment:nav.assets",
        titleKey: "equipment:list.title",
        order: 20,
        mobileBar: true,
      },
      {
        path: "/equipment/my",
        icon: User,
        labelKey: "equipment:nav.my_assets",
        titleKey: "equipment:my_assets.title",
        order: 25,
        mobileBar: true,
      },
      {
        path: "/equipment/locations",
        icon: MapPin,
        labelKey: "equipment:nav.locations",
        titleKey: "equipment:locationsPage.title",
        subtitleKey: "equipment:locationsPage.subtitle",
        order: 30,
        mobileBar: true,
      },
      {
        path: "/equipment/categories",
        icon: Tag,
        labelKey: "equipment:nav.categories",
        titleKey: "equipment:categories.title",
        subtitleKey: "equipment:categories.subtitle",
        order: 40,
      },
      {
        path: "/equipment/templates",
        icon: FileText,
        labelKey: "equipment:navigation.templates",
        titleKey: "equipment:templates.title",
        subtitleKey: "equipment:templates.subtitle",
        order: 45,
      },
      {
        path: "/equipment/campaigns",
        icon: ClipboardList,
        labelKey: "equipment:nav.campaigns",
        titleKey: "equipment:attestation.pageTitle",
        subtitleKey: "equipment:attestation.pageSubtitle",
        order: 50,
      },
      {
        path: "/equipment/settings",
        icon: Settings,
        labelKey: "equipment:nav.settings",
        titleKey: "equipment:settings.module_title",
        // Module settings are read and written by an admin-only endpoint.
        roles: ["admin"],
        // Settings sit last in the module bar, always (UI_GUIDELINES §2.14).
        order: 90,
      },
    ],
  },
  routes: [
    {
      path: "/equipment",
      component: EquipmentDashboardPage,
    },
    {
      path: "/equipment/add",
      component: AddEquipmentPage,
    },
    {
      path: "/equipment/assets",
      component: AssetListPage,
    },
    {
      path: "/equipment/my",
      component: MyAssetsPage,
    },
    {
      path: "/equipment/categories",
      component: EquipmentCategoriesPage,
    },
    {
      path: "/equipment/templates",
      component: TemplatesPage,
    },
    {
      path: "/equipment/locations",
      component: EquipmentLocationsPage,
    },
    {
      path: "/equipment/campaigns",
      component: AuditCampaignsPage,
    },
    {
      path: "/equipment/campaigns/:id",
      component: CampaignDetailPage,
    },
    {
      path: "/equipment/settings",
      component: EquipmentSettingsPage,
    },
    {
      path: "/equipment/:id",
      component: AssetDetailPage,
    },
    {
      path: "/equipment/:id/edit",
      component: AddEquipmentPage,
    },
  ],
  // Empty on purpose, and that is the rule, not an omission: a module may
  // hide a core nav entry only when its own screens cover the whole dataset
  // that entry led to. Equipment Locations lists the module scope and
  // Equipment Categories the module's context tag — subsets of what
  // /inventory/locations and /inventory/categories serve — so hiding either
  // stranded the organization's plain locations and categories behind a
  // link in the product form. The declaration stays here so the decision is
  // visible where the temptation lives; navOverridesCoverageGate.test.ts
  // holds it.
  navOverrides: [],
  // Equipment stands alone: its screens link to exactly one application route
  // (/equipment) and take everything else from the core's API. It adopts the
  // label pool and the scanner — a printed asset sticker has to keep scanning
  // once the inventory navigation is hidden — and renounces the sections that
  // only make sense over the pantry (stats, stock takes, the archive). An empty
  // keepCoreNav says it stands entirely alone, with no core section kept.
  // The shell honors the adoption: in focus mode an adopted section's pages
  // render under equipment's banner with the section's tab appended (see
  // registryQueries.getShellModule / coreSections.ts). The declaration itself
  // is the single-module-mode decision: only the module's author knows what
  // the module needs to stand alone, so every core section its workflow
  // touches is adopted or renounced here, explicitly — the organization just
  // flips one switch and never sees the detail.
  standalone: {
    coreSections: {
      labels: "adopt",
      scan: "adopt",
      stats: "renounce",
      stock_takes: "renounce",
      archive: "renounce",
    },
    keepCoreNav: [],
  },
  // No i18nOverrides, and that is the decision, not an omission.
  // The module used to rename two core navigation labels — "Assets" for
  // `inventory:nav.items` and "Locations" for `inventory:nav.storages` — and
  // stopped at the tab strip: the pages under those tabs stayed headed
  // "Products" and "Storages", and "Assets" already meant this module's own
  // fixed-asset list. A reader following the tab met a different word at the
  // destination, and one word carried two meanings in one application. The
  // module's own screens name their own things (`equipment:nav.*`); the core
  // list keeps the core word, which is also the word on its page.
  //
  // The override mechanism stays available for a module that renames a tab
  // AND the page it opens; lib/moduleRegistry/navLabelVocabulary.test.ts
  // holds both to one word.
  // A blank sticker has to say what it is for before it is stuck on
  // anything: the pool is shared, so without this every generated label
  // opened the product form and an asset could not be registered by scan
  // at all. The separate prefix keeps a printed sheet of asset labels
  // apart from a sheet of product labels by eye.
  labelPurpose: {
    contextTag: "equipment",
    icon: Monitor,
    labelKey: "equipment:labels.purpose",
    defaultPrefix: "EQP",
  },
  useStatusBadge: useEquipmentStatusBadge,
  statusBadgePermission: "equipment:read",
  // Someone holding a device types the number off its sticker. The core
  // item search reads the serial column, but its results lead to the
  // product screen — which is where assets are deliberately not shown.
  // This provider answers with the asset itself.
  searchProvider: async (query: string): Promise<SearchResult[]> => {
    const { items } = await equipmentApi.listAssets({
      search: query,
      limit: 5,
    });
    return items.map((asset) => ({
      id: `equipment-${asset.id}`,
      title: asset.name,
      subtitle: asset.serial_number ?? undefined,
      path: `/equipment/${asset.id}`,
      module: "equipment",
    }));
  },
});
