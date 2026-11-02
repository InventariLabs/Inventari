import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Edit2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useAllCategories } from "@/modules/shared/hooks/useCategories";
import { useLocationsById } from "@/module-sdk";
import { DeleteReasonDialog } from "@/modules/inventory/components/DeleteReasonDialog";
import { MoveItemModal } from "@/modules/inventory/components/MoveItemModal";
import { QuickActionGrid } from "@/modules/inventory/components/QuickActionGrid";
import { TypedSlot } from "@/components/Slot";
import ItemDetailOverview from "@/modules/inventory/components/items/ItemDetailOverview";
import ItemHistoryTimeline from "@/modules/inventory/components/items/ItemHistoryTimeline";
import { RecentStockMoves } from "@/modules/inventory/components/moves/RecentStockMoves";
import { recordsMovements } from "@/modules/inventory/constants/movementModules";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import ItemEditModal from "@/modules/inventory/components/ItemEditModal";
import { useItemQuickActions } from "@/modules/inventory/hooks/useItemQuickActions";
import type { Item } from "@/types";

type Tab = "overview" | "history" | "moves";

/**
 * The record, once it is known to exist.
 *
 * Split off the page so the quick actions can be a hook: they need an item,
 * and a hook cannot wait for one to load.
 *
 * Three tabs where there used to be two. The third was refused on the
 * grounds that "stock movements have no source of their own" — true when
 * the only history in the application was this record's own audit trail,
 * and false now that the movement ledger is readable: a run that consumed
 * this product picked whichever rows covered the amount, a receipt lands on
 * the row it decided to top up, and neither writes the story of the *place*
 * into the row you happen to be looking at. The two tabs answer different
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
  const [moving, setMoving] = useState(false);

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

  const { actions, vocabularyNote, deleteDialog } = useItemQuickActions(item, {
    onDone: () => {},
    onMove: () => setMoving(true),
    // The address stops resolving the moment the record goes.
    onDeleted: () => navigate("/inventory/items"),
  });

  useEffect(() => {
    setHeader({
      title: item.name,
      backTo: "/inventory/items",
      actions: canWrite ? (
        <Button
          variant="outline"
          onClick={() => setEditing(true)}
          leftIcon={<Edit2 size={16} />}
        >
          {t("common:actions.edit")}
        </Button>
      ) : undefined,
    });
    return () => setHeader({});
  }, [item, setHeader, t, canWrite]);

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
          {/* The same actions the sheet over the list offers. Without these
              the shortcut could do more to the record than the record's own
              address could, and the page's only verb was "Edit". */}
          {vocabularyNote && (
            <p className="text-sm text-on-muted">{vocabularyNote}</p>
          )}
          <QuickActionGrid actions={actions} layout="inline" />
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

      {moving && (
        <MoveItemModal
          item={item}
          onClose={() => setMoving(false)}
          onSuccess={() => setMoving(false)}
        />
      )}

      <DeleteReasonDialog
        key={String(deleteDialog.open)}
        open={deleteDialog.open}
        itemName={item.name}
        onConfirm={deleteDialog.onConfirm}
        onCancel={deleteDialog.onCancel}
      />
    </div>
  );
}
