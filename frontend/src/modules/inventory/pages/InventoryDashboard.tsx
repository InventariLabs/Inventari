import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";
import type { StorageLocationNode } from "@/types";
import { TypedSlot } from "@/components/Slot";
import { AttentionCard } from "@/components/ui/AttentionCard";
import { Button } from "@/components/ui/Button";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { cn } from "@/lib/utils";
import { useStoragesTree } from "@/modules/shared/hooks/useStorages";
import { useModules } from "@/contexts/ModulesContext";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { useItems } from "@/modules/inventory/hooks/useItems";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import DashboardStorages from "@/modules/inventory/components/DashboardStorages";
import { DashboardRecentMoves } from "@/modules/inventory/components/dashboard/DashboardRecentMoves";
import { toAttentionItems } from "@/modules/inventory/components/dashboard/attentionItems";
import { usePartialPackage } from "@/modules/shared/hooks/usePartialPackage";
import { useDashboardAttention } from "@/modules/inventory/hooks/useDashboardAttention";

/**
 * The cards the inventory dashboard opens on: the children of every top-level
 * location, plus the top-level location itself whenever it holds anything a
 * card would otherwise hide.
 */
function computeZones(storageTree: StorageLocationNode[]) {
  return storageTree.flatMap((site) =>
    site.children.length === 0 || site.items_count > 0
      ? [site, ...site.children]
      : site.children,
  );
}

/**
 * InventoryDashboard — the overview at /inventory.
 *
 * One skeleton, top to bottom: what needs attention (or one line saying
 * nothing does), what each storage place is made of, then what happened
 * lately beside what other modules keep going (the active shopping list).
 * Every number comes from a list the module's own screens already ask for —
 * there is no dashboard endpoint. What belongs to another module reaches the
 * screen through a slot: the replenish door and its modal, and the card
 * beside the recent moves.
 */
export default function InventoryDashboard() {
  const { t } = useTranslation(["common", "items"]);
  const { enabledModules } = useModules();
  const partialOf = usePartialPackage();
  // The recent moves share their row with the aside only when something
  // fills it; alone they take the whole width.
  const hasAside =
    moduleRegistry.getSlotComponents("dashboard_activity_aside", enabledModules)
      .length > 0;
  useAddProductHeader();

  // The products count has to count the rows the products list will show.
  // The list hides what a vertical module owns, and so does this.
  const excludeModuleContexts = !useShowModuleData();
  // "Storage places" answers the same question as the Storages tab, so it
  // has to answer it with the same locations.
  const {
    data: storageTree,
    isError: isTreeError,
    refetch: refetchTree,
  } = useStoragesTree(undefined, {
    excludeModuleContexts,
    // The cards are the places directly under each top-level place, so two
    // levels; the rest of the tree is not this screen's business.
    depth: 2,
  });
  const { data: productPage } = useItems({
    exclude_module_contexts: excludeModuleContexts,
    limit: 1,
    offset: 0,
  });
  // The same one level the storages list shows as cards, shared with it so
  // the two screens cannot disagree about what a card is.
  const storageZones: StorageLocationNode[] = useMemo(
    () => (storageTree ? computeZones(storageTree) : []),
    [storageTree],
  );
  const attention = useDashboardAttention({
    excludeModuleContexts,
    zones: storageZones,
  });
  const [isReplenishOpen, setIsReplenishOpen] = useState(false);

  // A count that did not arrive is left out of the sentence, never read as
  // zero: "0 products" over a failed request is the screen lying.
  // A large organization's list stops counting; the sentence says so.
  const products = productPage
    ? productPage.total_capped
      ? t("common:dashboard.recordCountMore", { count: productPage.total })
      : t("common:dashboard.recordCount", { count: productPage.total })
    : null;
  const places = !storageTree
    ? null
    : products
      ? t("common:dashboard.inPlaces", { count: storageZones.length })
      : t("common:dashboard.placeCount", { count: storageZones.length });
  const holdings = [products, places].filter(Boolean).join(" ");
  // Beside "17 records need attention" a bare "592 records" read as part of
  // the same number, so it says it is about everything.
  const summary = holdings
    ? t("common:dashboard.attention.summaryInAll", { summary: holdings })
    : undefined;

  return (
    <div className="space-y-6">
      <AttentionCard
        items={toAttentionItems(
          attention.groups,
          attention.locations,
          attention.lowProducts,
          t,
          partialOf,
        )}
        attentionLabel={t("common:dashboard.attention.heading", {
          count: attention.count,
        })}
        summary={summary}
        linkLabel={t("common:dashboard.viewAll")}
        // Every record the heading counts, not every record there is.
        linkHref="/inventory/items?filter=needs-attention"
        quiet={{
          okText: t("common:dashboard.attention.quiet"),
          linkLabel: t("common:dashboard.products"),
          linkHref: "/inventory/items",
        }}
        loading={attention.isLoading}
        unavailable={
          attention.isError
            ? {
                message: t("common:dashboard.attention.unavailable"),
                retryLabel: t("common:actions.retry"),
                onRetry: attention.refetch,
                partialLabel: t("common:dashboard.attention.partial"),
              }
            : undefined
        }
        actions={
          // The suggestions become a shopping list, so the door is the
          // shopping lists' to draw. `contents` keeps the slot's wrapper out
          // of the row: an empty one would still take a gap.
          <TypedSlot
            name="dashboard_replenish_action"
            data={{ onOpen: () => setIsReplenishOpen(true) }}
            className="contents"
          />
        }
      />

      {/* The widget contract wants the org id; the user record has never
          carried one, so this slot has always received the empty string. */}
      <TypedSlot name="dashboard_widgets" data={{ organizationId: "" }} />

      <DashboardStorages
        storageZones={storageZones}
        composition={attention.composition}
        loadFailed={isTreeError}
        onRetry={() => void refetchTree()}
      />

      <div className={cn("grid gap-6", hasAside && "lg:grid-cols-[7fr_5fr]")}>
        <DashboardRecentMoves />
        <TypedSlot
          name="dashboard_activity_aside"
          data={{}}
          className="contents"
        />
      </div>

      {/* Looking at a proposal is not agreeing to one: the preview opens
          without creating a list, and a list is made when somebody decides
          to buy something. */}
      <TypedSlot
        name="dashboard_replenish_modal"
        data={{
          isOpen: isReplenishOpen,
          onClose: () => setIsReplenishOpen(false),
        }}
      />
    </div>
  );
}

/** "Add product" in the module header, for those who may write. */
function useAddProductHeader() {
  const { t } = useTranslation("items");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("items");
  const navigate = useNavigate();
  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto">
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => navigate("/inventory/items/add")}
          >
            {t("items:addProduct")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite, navigate]);
}
