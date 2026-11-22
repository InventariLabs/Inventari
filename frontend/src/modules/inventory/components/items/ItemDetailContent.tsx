import { isVirtualUsage } from "@/modules/shared/lib/storageUsage";
import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useLocationsById } from "@/module-sdk";
import { TypedSlot } from "@/components/Slot";
import ItemDetailOverview from "@/modules/inventory/components/items/ItemDetailOverview";
import ItemHistoryTimeline from "@/modules/inventory/components/items/ItemHistoryTimeline";
import { RecentStockMoves } from "@/modules/inventory/components/moves/RecentStockMoves";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import ItemEditModal from "@/modules/inventory/components/ItemEditModal";
import { ItemDetailActions } from "@/modules/inventory/components/items/ItemDetailActions";
import type { Item } from "@/types";

type Tab = "overview" | "history" | "moves";

/**
 * The record, once it is known to exist.
 *
 * Split off the page so the header's actions can be given an item: they need
 * one, and a hook cannot wait for one to load.
 *
 * Three tabs, the third being the movement ledger. "Stock movements have no
 * source of their own" would hold only if the sole history were this
 * record's own audit trail; the ledger is readable, and a run that consumed
 * this product picks whichever rows cover the amount, a receipt lands on
 * the row it decides to top up, and neither writes the story of the *place*
 * into the row you happen to be looking at. The two history tabs answer different
 * questions — "what was done to this record" and "what moved here" — and
 * the second one is the one an audit asks.
 */
export default function ItemDetailContent({ item }: { item: Item }) {
  const { t } = useTranslation(["items", "common", "inventory"]);
  const { setHeader } = useModulePageHeader();
  // The header's Edit is the fourth door into `ItemEditModal`, and the one
  // that was missing the question: the list, the sheet and the scanner all
  // ask before opening it. Without this a read-only account filled in the
  // whole form and learned the answer from the 403.
  const canWrite = useCanWrite("items");
  const navigate = useNavigate();
  const [tab, setTab] = useState<Tab>("overview");
  const [editing, setEditing] = useState(false);

  // Naming reads the record's own place by id, whatever the pickers are
  // scoped to: a record the reader consumed to zero sits in the system's
  // virtual location, and the overview row that says where it is must
  // resolve.
  const { byId: places } = useLocationsById([item.location_id]);
  const storages = useMemo(() => [...places.values()], [places]);
  const { data: categories } = useAllCategories();

  // An organization with no module that consumes StockQuant never writes a
  // movement (ADR-004), and a product with no catalogue entry behind it has
  // nothing for a movement to name — either way the tab would be an empty
  // promise, so it is not offered.
  const enabledModules = useEnabledModulesOptional();
  const showMoves =
    Boolean(item.template_id) && recordsMovements(enabledModules);
  const locationName = places.get(item.location_id)?.name;
  const inVirtualPlace = isVirtualUsage(places.get(item.location_id)?.usage);
  // An asset is returned and disposed of, a product topped up and deleted:
  // the header's words switch with the category, and the note says why —
  // to an account offered the actions at all.
  const vocabularyNote =
    canWrite && item.category?.context_tag === "equipment"
      ? t("items:quickActions.equipmentNote")
      : null;

  // Every action writes, so an account that cannot write is offered none.
  useEffect(() => {
    setHeader({
      title: item.name,
      backTo: "/inventory/items",
      actions: canWrite ? (
        <ItemDetailActions
          item={item}
          inVirtualPlace={inVirtualPlace}
          onEdit={() => setEditing(true)}
          // The address stops resolving the moment the record goes.
          onDeleted={() => navigate("/inventory/items")}
        />
      ) : undefined,
    });
    return () => setHeader({});
  }, [item, setHeader, canWrite, inVirtualPlace, navigate]);

  return (
    <div className="space-y-6">
      <Tabs
        defaultValue="overview"
        value={tab}
        onValueChange={(value) => setTab(value as Tab)}
        panels={false}
      >
        <TabsList>
          <TabsTrigger value="overview">
            {t("items:detail.overviewTab")}
          </TabsTrigger>
          <TabsTrigger value="history">{t("items:history.title")}</TabsTrigger>
          {showMoves && (
            <TabsTrigger value="moves">{t("inventory:moves.tab")}</TabsTrigger>
          )}
        </TabsList>
      </Tabs>

      {tab === "overview" ? (
        <>
          <ItemDetailOverview
            item={item}
            storages={storages}
            categories={categories}
          />
          {vocabularyNote && (
            <p className="text-sm text-on-muted">{vocabularyNote}</p>
          )}
        </>
      ) : tab === "history" ? (
        <ItemHistoryTimeline itemId={item.id} unit={item.uom} />
      ) : (
        <RecentStockMoves
          showProduct={false}
          filters={{
            product_template_id: item.template_id ?? undefined,
            location_id: item.location_id,
          }}
          caption={t("inventory:moves.itemCaption", {
            location: locationName ?? t("inventory:moves.thisLocation"),
          })}
          seeAll={{
            to: `/inventory/moves?template=${item.template_id ?? ""}`,
            label: t("inventory:moves.seeProductEverywhere"),
          }}
          emptyTitle={t("inventory:moves.empty.productTitle")}
          emptyDescription={t("inventory:moves.empty.productDescription")}
        />
      )}

      {/* Module-contributed content for this product: a module that owns a
          fact about the (product, shelf) pair — putaway capacity — speaks
          here rather than the inventory page importing it. */}
      <TypedSlot name="item_detail_extra" data={{ item }} />

      {editing && (
        <ItemEditModal itemId={item.id} onClose={() => setEditing(false)} />
      )}
    </div>
  );
}
