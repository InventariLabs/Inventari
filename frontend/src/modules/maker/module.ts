import { createElement, lazy } from "react";
import { Hammer, FlaskConical, SlidersHorizontal } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/lib/moduleRegistry";
import { useBomSummaryForTemplates } from "@/modules/maker/hooks/useBom";
import { queryKeys } from "@/hooks/queries/keys";
import { bomApi } from "./api/bom";
import { HasBoMBadge } from "./components/HasBoMBadge";

const RecipeCatalogPage = lazy(() => import("./pages/RecipeCatalogPage"));
const RecipeDetailPage = lazy(() => import("./pages/RecipeDetailPage"));
const ProductionListPage = lazy(() => import("./pages/ProductionListPage"));
const ProductionDetailPage = lazy(() => import("./pages/ProductionDetailPage"));
const MakerSettingsPage = lazy(() => import("./pages/MakerSettingsPage"));
const BomLegacyRedirect = lazy(() => import("./pages/BomLegacyRedirect"));
const BoMEntrySlot = lazy(() => import("./components/BoMEntrySlot"));
const WhereUsedSlot = lazy(() => import("./components/WhereUsedSlot"));
const CookForStockSlot = lazy(() => import("./components/CookForStockModal"));

moduleRegistry.register({
  name: "maker",
  // Production keeps the product catalogue, locations and stock journal it changes.
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
    displayName: "maker:launcher.title",
    description: "maker:launcher.description",
    icon: Hammer,
    color: "bg-amber-500",
    category: "business",
    order: 60,
  },
  moduleNav: {
    basePath: "/maker",
    items: [
      {
        path: "/maker",
        icon: FlaskConical,
        labelKey: "maker:navigation.catalog",
        titleKey: "maker:catalog.title",
        subtitleKey: "maker:catalog.subtitle",
        order: 10,
        mobileBar: true,
      },
      {
        path: "/maker/production",
        icon: Hammer,
        labelKey: "maker:navigation.production",
        titleKey: "maker:productionList.title",
        subtitleKey: "maker:productionList.subtitle",
        order: 20,
        // On a phone the module bar was the catalog alone, so a production
        // run had no way back to production except the browser's back.
        mobileBar: true,
      },
      {
        // Settings sit last in the module bar, always (UI_GUIDELINES §2.14).
        path: "/maker/settings",
        icon: SlidersHorizontal,
        labelKey: "maker:navigation.settings",
        titleKey: "maker:settings.title",
        subtitleKey: "maker:settings.subtitle",
        order: 90,
      },
    ],
  },
  routes: [
    { path: "/maker", component: RecipeCatalogPage },
    { path: "/maker/recipes/:recipeId", component: RecipeDetailPage },
    { path: "/maker/production", component: ProductionListPage },
    { path: "/maker/production/:orderId", component: ProductionDetailPage },
    { path: "/maker/settings", component: MakerSettingsPage },
    // Removed screen, kept as a redirect for saved links.
    { path: "/maker/bom", component: BomLegacyRedirect },
  ],
  slots: [
    {
      slot: "item_edit_extra",
      component: slotComponent(BoMEntrySlot),
      priority: 20,
    },
    {
      slot: "item_edit_extra",
      component: slotComponent(WhereUsedSlot),
      priority: 30,
    },
    {
      slot: "recipe_cook_for_stock",
      component: slotComponent(CookForStockSlot),
    },
  ],
  // "Has a formula" as a filter, not only as a badge: the flag was passive,
  // and a flat list of every product with no way to narrow by it is what made
  // finished goods, sub-assemblies and raw materials look mixed together.
  listFilterContributors: [
    {
      key: "maker-has-bom",
      label: "maker:bomEntry.columnHeader",
      requiredModule: "maker",
      queryKey: queryKeys.maker.bomTemplateIds(),
      fetchTemplateIds: async () =>
        (await bomApi.templateIdsWithBom()).template_ids,
    },
  ],
  columnContributors: [
    {
      key: "maker-has-bom",
      // The header names the property, the cell carries the value. With the
      // same word in both, the column read as "this row is a formula" rather
      // than "this product has one".
      label: "maker:bomEntry.columnHeader",
      requiredModule: "maker",
      position: "after-name",
      width: "120px",
      // Not "does this product have a template" — every product does — but
      // "does anything on this page actually have a formula".
      useHasValues: (items) => {
        const templateIds = [
          ...new Set(
            items
              .map((item) => item.template_id)
              .filter((id): id is string => Boolean(id)),
          ),
        ];
        const { data } = useBomSummaryForTemplates(templateIds);
        if (templateIds.length === 0) return false;
        return data ? data.items.length > 0 : undefined;
      },
      render: (item) =>
        item.template_id
          ? createElement(HasBoMBadge, { templateId: item.template_id })
          : null,
    },
  ],
  // No settingsSections: the module's own settings page owns these options.
  // The global settings shell lists module sections under "Module settings",
  // which is not where the screens these options change live.
  settingsSections: [],
});
