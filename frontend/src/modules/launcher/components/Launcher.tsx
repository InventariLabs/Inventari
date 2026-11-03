import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  Clock,
  LayoutGrid,
  Star,
  Briefcase,
  BarChart3,
  Plug,
  Settings,
  type LucideIcon,
} from "lucide-react";
import { DndContext, closestCenter, type DragEndEvent } from "@dnd-kit/core";
import {
  SortableContext,
  rectSortingStrategy,
  useSortable,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { useModules } from "@/contexts/ModulesContext";
import { useAuthStore } from "@/store/authStore";
import { useHasPermission } from "@/hooks/useHasPermission";
import { moduleRegistry, type FrontendModule } from "@/lib/moduleRegistry";
import { getRecentItems } from "@/lib/recentItems";
import { ModuleTile } from "./ModuleTile";
import { ActionItemsFeed } from "./ActionItemsFeed";
import { ActiveProfilePill } from "./ActiveProfilePill";
import { useLauncherGreeting } from "../hooks/useLauncherGreeting";
import { useTileOrder, useSavedTileOrder } from "../hooks/useTileOrder";
import { resolveProfileCategories } from "../hooks/useProfileCategories";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { useProfiles } from "@/modules/onboarding/moduleApi";
import type { LauncherCategory } from "@/types";
import { cn } from "@/lib/utils";
import { DND_LABEL, useDndA11y, useDndSensors } from "@/lib/dndA11y";
import { makeTDynamic } from "@/lib/i18nHelpers";

const SECTION_ORDER: LauncherCategory[] = [
  "core",
  "business",
  "analytics",
  "integrations",
  "system",
];

const SECTION_ICONS: Record<LauncherCategory, LucideIcon> = {
  core: Star,
  business: Briefcase,
  analytics: BarChart3,
  integrations: Plug,
  system: Settings,
};

/**
 * Headings earn their place only when the sections they head actually group
 * something. A fresh organization has four tiles spread over three headings,
 * one of them covering a single tile — the headings then outnumber what they
 * organize, and the grid reads as fragments instead of as one screen.
 */
const MIN_TILES_PER_SECTION = 2;

/** Storage key for the single grid shown when the launcher is not grouped. */
const UNGROUPED_KEY = "all";

function isLauncherCategory(value: unknown): value is LauncherCategory {
  return (
    value === "core" ||
    value === "business" ||
    value === "analytics" ||
    value === "integrations" ||
    value === "system"
  );
}

/**
 * SortableTile — wraps a module tile with @dnd-kit sortable behaviour.
 * Calls useStatusBadge as a proper hook boundary if present.
 */
function SortableTile({ module }: { module: FrontendModule }) {
  // The tile's own visible words name the drag, not the module's machine
  // name: the announcement reads this label, so "shopping_lists" becomes
  // what the tile actually says in the reader's language.
  const tDyn = makeTDynamic(useTranslation("common").t);
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({
    id: module.name,
    data: { [DND_LABEL]: tDyn(module.launcher!.displayName) },
    // The handle is the tile's link, and it stays one: the default
    // `role="button"` would make a link announce itself as a button.
    attributes: { role: "link" },
  });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
    zIndex: isDragging ? 10 : undefined,
  };

  const badge = module.useStatusBadge ? module.useStatusBadge() : null;

  // The attributes and the listeners share one node on purpose — the link.
  // Split across two nodes, the node that announces "sortable, press the
  // space bar" is a node the space bar does nothing on, and the reader has to
  // tab once more onto an undeclared handle. Measured on the running app.
  // The `<li>` only moves: it stays a list item, which is all a list holds.
  return (
    <li ref={setNodeRef} style={style}>
      <ModuleTile
        module={module}
        statusBadge={badge}
        sortable
        {...attributes}
        {...listeners}
      />
    </li>
  );
}

/**
 * StaticTile — the same tile without the sortable wiring.
 *
 * The mobile grid has no drag context, so a tile there cannot be moved, and it
 * must not claim otherwise: `useSortable` outside a `DndContext` still stamps
 * the item with `aria-roledescription="sortable"` and an `aria-describedby`
 * pointing at an element that is never rendered.
 */
function StaticTile({ module }: { module: FrontendModule }) {
  const badge = module.useStatusBadge ? module.useStatusBadge() : null;

  return (
    <li>
      <ModuleTile module={module} statusBadge={badge} />
    </li>
  );
}

/**
 * SectionHeader — category label with icon, hidden on mobile.
 */
function SectionHeader({
  icon: Icon,
  label,
}: {
  icon: LucideIcon;
  label: string;
}) {
  return (
    <h2 className="hidden md:flex items-center gap-2 text-xs font-medium uppercase tracking-wider text-on-muted mb-3 mt-6 first:mt-0">
      <Icon size={14} strokeWidth={2} />
      {label}
    </h2>
  );
}

/**
 * Launcher — home page module selector.
 *
 * Mobile: compact icon grid (app-drawer style) — single flat grid.
 * Desktop: grouped by category with section headers and independent
 *          drag-and-drop within each section, or one grid when there are too
 *          few tiles for the grouping to organize anything.
 *
 * Both form factors show the tiles in the same arrangement — the one the
 * desktop grid persists.
 */
export default function Launcher() {
  const { t } = useTranslation(["launcher", "common"]);
  const { enabledModules, hiddenModules } = useModules();
  const { user } = useAuthStore();
  const { data: org } = useOrganization();
  const { data: profiles } = useProfiles();

  // Focus mode hides every module except the focused one from the grid.
  const allModules = moduleRegistry.getVisibleModules(
    enabledModules,
    hiddenModules,
  );

  // Resolve the active profile (matches org.active_profile_id, or null when
  // no profile is set yet — falls back to module-default categories).
  const activeProfile =
    profiles?.find((p) => p.id === org?.active_profile_id) ?? null;

  // Group modules by category — profile override wins when present.
  const categoryMap = resolveProfileCategories(allModules, activeProfile);
  const grouped: Record<string, FrontendModule[]> = {};
  for (const mod of allModules) {
    const cat = isLauncherCategory(categoryMap[mod.name])
      ? categoryMap[mod.name]
      : "business";
    if (!grouped[cat]) grouped[cat] = [];
    grouped[cat].push(mod);
  }

  const sections = SECTION_ORDER.filter((cat) => grouped[cat]?.length);
  const isGrouped =
    sections.length >= 2 &&
    allModules.length >= sections.length * MIN_TILES_PER_SECTION;

  // Section order is the spine of both layouts: grouped, it orders the
  // headings; ungrouped, it orders the single grid.
  const inSectionOrder = sections.flatMap((cat) => grouped[cat]);

  const readOrder = useSavedTileOrder();
  const byName = new Map(allModules.map((mod) => [mod.name, mod]));
  const resolve = (names: string[]) =>
    names
      .map((name) => byName.get(name))
      .filter((mod): mod is FrontendModule => mod !== undefined);

  const mobileModules = isGrouped
    ? sections.flatMap((cat) =>
        resolve(
          readOrder(
            grouped[cat].map((mod) => mod.name),
            cat,
          ),
        ),
      )
    : resolve(
        readOrder(
          inSectionOrder.map((mod) => mod.name),
          UNGROUPED_KEY,
        ),
      );

  const userId = user?.id ? String(user.id) : null;
  // The segment has read "default" since the key was invented: the user
  // record has never carried an organization id, so the old conditional was
  // the fallback branch and nothing else.
  const orgId = "default";
  const recentItems = userId ? getRecentItems(userId, orgId) : [];

  const isAdmin = useHasPermission("admin:access");
  const greeting = useLauncherGreeting();

  return (
    <div className="max-w-screen-2xl mx-auto space-y-6 pb-32 pt-2">
      {/* ── Header ─────────────────────────────────────────────── */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-on tracking-tight">
            {greeting.title}
          </h1>
          <p className="text-sm text-on-muted mt-0.5">{greeting.subtitle}</p>
        </div>
        <ActiveProfilePill />
      </div>

      {/* ── Main content: modules + sidebar ────────────────────── */}
      <div className="flex flex-col md:flex-row gap-6">
        {/* Module sections */}
        <section
          aria-labelledby="launcher-modules-heading"
          className="flex-[3] min-w-0"
        >
          <h2 id="launcher-modules-heading" className="sr-only">
            {t("common:navigation.modules", "Modules")}
          </h2>

          {/* Mobile: flat grid, in the arrangement the desktop grid persists */}
          <div className="md:hidden">
            <ul role="list" className="grid grid-cols-4 sm:grid-cols-5 gap-1">
              {mobileModules.map((mod) => (
                <StaticTile key={mod.name} module={mod} />
              ))}
              {isAdmin && (
                <li>
                  <BrowseAppsTile />
                </li>
              )}
            </ul>
          </div>

          {/* Desktop: grouped by category with per-section D&D */}
          <div className="hidden md:block">
            {isGrouped ? (
              sections.map((cat) => (
                <CategorySection
                  key={cat}
                  category={cat}
                  modules={grouped[cat]}
                  header={
                    <SectionHeader
                      icon={SECTION_ICONS[cat]}
                      label={t(`launcher:sections.${cat}`, cat)}
                    />
                  }
                  renderBrowseAtEnd={
                    isAdmin && cat === sections[sections.length - 1]
                  }
                />
              ))
            ) : (
              <CategorySection
                category={UNGROUPED_KEY}
                modules={inSectionOrder}
                header={null}
                renderBrowseAtEnd={isAdmin}
              />
            )}
          </div>
        </section>

        {/* Sidebar: action items + recent items.
            `empty:hidden` is the point of the fixed width: with nothing to
            feed it, the column contributes no DOM node and gives its space
            back to the grid instead of holding a quarter of the screen open
            for a card that never comes. */}
        <aside
          data-testid="launcher-sidebar"
          className="md:w-80 lg:w-96 shrink-0 space-y-4 empty:hidden"
        >
          <ActionItemsFeed />
          {recentItems.length > 0 && (
            <section aria-labelledby="launcher-recent-heading">
              <h2
                id="launcher-recent-heading"
                className="flex items-center gap-2 text-sm font-semibold text-on-secondary mb-3"
              >
                <Clock size={15} />
                {t("launcher:launcher.recentItems", "Recently visited")}
              </h2>
              <ul className="space-y-1">
                {recentItems.slice(0, 5).map((item) => (
                  <li key={item.id}>
                    <Link
                      to={item.path}
                      className="flex items-center gap-3 px-3 py-2.5 rounded-xl hover:bg-surface-raised transition-colors text-sm text-on"
                    >
                      <span className="w-6 h-6 rounded-lg bg-surface-raised flex items-center justify-center shrink-0">
                        <span className="text-[10px] font-medium text-on-muted uppercase">
                          {item.module[0]}
                        </span>
                      </span>
                      <span className="flex-1 truncate">{item.title}</span>
                      <span className="text-[10px] text-on-muted capitalize shrink-0">
                        {item.module}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </div>
  );
}

/**
 * CategorySection — a single category group with its own DnD sorting context.
 * Modules only sort within their own category.
 */
function CategorySection({
  category,
  modules,
  header,
  renderBrowseAtEnd,
}: {
  category: string;
  modules: FrontendModule[];
  header: React.ReactNode;
  renderBrowseAtEnd: boolean;
}) {
  const moduleNames = modules.map((m) => m.name);
  const { order, reorder } = useTileOrder(moduleNames, category);

  const ordered = order
    .map((name) => modules.find((m) => m.name === name))
    .filter((m): m is FrontendModule => m !== undefined);

  const sensors = useDndSensors(8, true);
  const dndA11y = useDndA11y();

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;
    const fromIdx = order.indexOf(String(active.id));
    const toIdx = order.indexOf(String(over.id));
    if (fromIdx !== -1 && toIdx !== -1) {
      reorder(fromIdx, toIdx);
    }
  }

  return (
    <>
      {header}
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
        accessibility={dndA11y}
      >
        <SortableContext items={order} strategy={rectSortingStrategy}>
          <ul
            role="list"
            className="grid grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4"
          >
            {ordered.map((mod) => (
              <SortableTile key={mod.name} module={mod} />
            ))}
            {renderBrowseAtEnd && (
              <li>
                <BrowseAppsTile />
              </li>
            )}
          </ul>
        </SortableContext>
      </DndContext>
    </>
  );
}

/**
 * BrowseAppsTile — non-sortable tile that sits at the end of the module grid.
 * Uses a dashed border to visually signal "this is different".
 */
function BrowseAppsTile() {
  const { t } = useTranslation("launcher");
  return (
    <Link
      to="/apps"
      className={cn(
        "relative block rounded-2xl md:rounded-xl",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary-500 focus-visible:ring-offset-2",
      )}
    >
      {/* Mobile */}
      <div
        className={cn(
          "md:hidden flex flex-col items-center gap-1.5 px-1 pt-3 pb-2.5 rounded-2xl",
          "border border-dashed border-border hover:bg-surface-raised active:scale-95 transition-all duration-150",
        )}
      >
        <div className="w-14 h-14 rounded-[18px] flex items-center justify-center">
          <LayoutGrid size={26} strokeWidth={1.75} className="text-on-muted" />
        </div>
        <span className="text-xs font-medium text-center leading-tight line-clamp-2 w-full px-0.5 hyphens-auto break-words text-on-muted">
          {t("launcher:launcher.browseApps")}
        </span>
      </div>

      {/* Desktop */}
      <div
        className={cn(
          "hidden md:flex flex-col items-center text-center p-5 rounded-xl min-h-[180px] justify-center gap-3",
          "bg-surface-card border border-dashed border-border",
          "hover:bg-surface-raised hover:border-primary-300",
          "active:scale-[0.98] transition-all duration-200",
        )}
      >
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center bg-surface-raised border border-dashed border-border">
          <LayoutGrid size={28} strokeWidth={1.75} className="text-on-muted" />
        </div>
        <span className="text-sm font-semibold text-on leading-tight">
          {t("launcher:launcher.browseApps")}
        </span>
      </div>
    </Link>
  );
}
