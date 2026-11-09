import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { queryKeys } from "@/hooks/queries/keys";
import { cn } from "@/lib/utils";
import { putawayCapacityApi } from "@/modules/warehouse/api/putaway";
import {
  ShelfSettingsSheet,
  type ShelfSettingsTarget,
} from "@/modules/warehouse/components/ShelfSettingsSheet";
import { OccupancyMap } from "@/modules/warehouse/components/occupancy/OccupancyMap";
import { OccupancyTree } from "@/modules/warehouse/components/occupancy/OccupancyTree";
import {
  SEARCH_LIMIT,
  useOccupancyHits,
  useShelfEntries,
} from "@/modules/warehouse/hooks/useOccupancyLookups";
import {
  OCCUPANCY_FILTERS,
  pathOf,
  visibleNodeIds,
  visibleNodes,
  type OccupancyFilter,
} from "@/modules/warehouse/components/occupancy/occupancyModel";

type View = "list" | "grid";

const NO_FOLDS: Set<string> = new Set();

/**
 * Every warehouse and shelf on one screen: a tree with a fill bar per
 * location, and a heat map of the same data, with a "where is…" search that
 * works in both.
 *
 * The server answers with the whole floor in walk order and the roll-ups
 * already added, so this screen filters and folds a list it was given and
 * never adds up shelves itself. The floor's answer carries each shelf's fill,
 * not every product on it: the products of a shelf the reader opens are read
 * then, and a search asks the server where the products it names lie. The
 * map is for a desktop; a phone gets the tree, whose rows stack.
 */
export default function OccupancyPage() {
  const { t } = useTranslation(["warehouse", "common"]);
  const canWrite = useCanWrite("warehouse");
  const canWriteStorages = useCanWrite("locations");
  const wide = useMediaQuery("(min-width: 768px)");

  const [view, setView] = useState<View>("list");
  const [filter, setFilter] = useState<OccupancyFilter>("all");
  const [search, setSearch] = useState("");
  const [folded, setFolded] = useState<Set<string>>(new Set());
  const [opened, setOpened] = useState<Set<string>>(new Set());
  const [pickedId, setPickedId] = useState<string | null>(null);
  const [target, setTarget] = useState<ShelfSettingsTarget | null>(null);

  const {
    data: overview,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: queryKeys.documents.putawayOccupancyOverview,
    queryFn: () => putawayCapacityApi.occupancyOverview(),
  });

  const nodes = useMemo(() => overview?.nodes ?? [], [overview]);
  const byId = useMemo(
    () => new Map(nodes.map((node) => [node.location_id, node])),
    [nodes],
  );
  const needle = search.trim().toLowerCase();
  const {
    byLocation: hits,
    truncated,
    failure: searchFailure,
  } = useOccupancyHits(needle);
  const shelves = useShelfEntries(
    pickedId ? [...opened, pickedId] : [...opened],
  );
  const visible = useMemo(
    () => visibleNodeIds(nodes, filter, hits),
    [nodes, filter, hits],
  );
  // A search lays out the way to every shelf it found: a fold must not hide
  // the answer. `visible` already holds only those shelves and their parents.
  // Until the server has answered there is no answer to lay out, and the
  // folds stay as the reader left them.
  const shownFolds = hits ? NO_FOLDS : folded;
  const treeRows = useMemo(
    () => visibleNodes(nodes, visible, shownFolds),
    [nodes, visible, shownFolds],
  );
  const filteredNodes = useMemo(
    () => (visible ? nodes.filter((n) => visible.has(n.location_id)) : nodes),
    [nodes, visible],
  );
  const shownShelves = filteredNodes.filter((n) => n.cell !== null).length;

  const toggle = (set: Set<string>, id: string) => {
    const next = new Set(set);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  };

  const openSettings = (node: {
    location_id: string;
    name: string;
    sequence: number | null;
  }) =>
    setTarget({
      id: node.location_id,
      name: node.name,
      sequence: node.sequence,
      full_path: pathOf(byId, byId.get(node.location_id)!),
    });

  if (isError) {
    return (
      <QueryFailure
        error={error}
        message={t("warehouse:errors.loadOccupancyFailed")}
        onRetry={() => void refetch()}
      />
    );
  }
  if (!overview) return <LoadingSpinner />;
  if (nodes.length === 0) {
    return (
      <EmptyState
        title={t("warehouse:occupancy.empty_state.title")}
        description={t("warehouse:occupancy.empty_state.description")}
      />
    );
  }

  const { totals } = overview;
  const counters = [
    {
      key: "shelves",
      label: t("warehouse:occupancy.counters.shelves"),
      value: totals.shelves,
      tone: "text-on",
    },
    {
      key: "withLimit",
      label: t("warehouse:occupancy.counters.withLimit"),
      value: totals.with_limit,
      tone: "text-on",
    },
    {
      key: "full",
      label: t("warehouse:occupancy.counters.full"),
      value: totals.full,
      tone: "text-on-warning",
    },
    {
      key: "over",
      label: t("warehouse:occupancy.counters.over"),
      value: totals.over,
      tone: "text-on-danger",
    },
    {
      key: "empty",
      label: t("warehouse:occupancy.counters.empty"),
      value: totals.empty,
      tone: "text-on",
    },
  ];
  const filterLabels: Record<OccupancyFilter, string> = {
    all: t("warehouse:occupancy.filters.all"),
    full: t("warehouse:occupancy.filters.full"),
    over: t("warehouse:occupancy.filters.over"),
    empty: t("warehouse:occupancy.filters.empty"),
    noLimit: t("warehouse:occupancy.filters.noLimit"),
  };
  const effectiveView: View = wide ? view : "list";

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      <p className="max-w-3xl text-sm text-on-secondary">
        {t("warehouse:occupancy.intro")}{" "}
        <Link
          to="/warehouse/location-settings"
          className="font-medium text-on-primary hover:underline"
        >
          {t("warehouse:occupancy.settingsLink")}
        </Link>
      </p>

      <dl className="flex flex-wrap gap-x-8 gap-y-3 rounded-xl border border-border bg-surface-card px-4 py-3">
        {counters.map((counter) => (
          <div key={counter.key} className="flex flex-col gap-0.5">
            <dt className="text-xs text-on-secondary">{counter.label}</dt>
            <dd
              className={cn("text-lg font-medium tabular-nums", counter.tone)}
            >
              {counter.value}
            </dd>
          </div>
        ))}
      </dl>

      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("warehouse:occupancy.searchPlaceholder"),
        }}
        primaryTabs={{
          value: filter,
          onChange: (value) => setFilter(value as OccupancyFilter),
          label: t("warehouse:occupancy.filterLabel"),
          options: OCCUPANCY_FILTERS.map((value) => ({
            value,
            label: filterLabels[value],
          })),
        }}
        viewToggle={wide ? { mode: view, onChange: setView } : undefined}
        resultCount={searchFailure ? undefined : shownShelves}
        resultCountLabel={t("warehouse:occupancy.resultsLabel", {
          count: shownShelves,
        })}
      />

      <Legend />

      {truncated && (
        <p className="text-sm text-on-secondary" role="status">
          {t("warehouse:occupancy.searchTruncated", { count: SEARCH_LIMIT })}
        </p>
      )}

      {searchFailure ? (
        <InlineQueryError
          error={searchFailure.error}
          onRetry={searchFailure.retry}
          message={t("warehouse:errors.searchOccupancyFailed")}
          className="rounded-xl border border-border px-4 py-6"
        />
      ) : shownShelves === 0 ? (
        <p className="rounded-xl border border-border px-4 py-6 text-center text-sm text-on-secondary">
          {t("warehouse:occupancy.noMatch")}
        </p>
      ) : effectiveView === "list" ? (
        <OccupancyTree
          nodes={treeRows}
          folded={shownFolds}
          opened={opened}
          entries={shelves.entries}
          failures={shelves.failures}
          hits={hits}
          onToggleFold={(id) => setFolded((s) => toggle(s, id))}
          onToggleOpen={(id) => setOpened((s) => toggle(s, id))}
          onOpenSettings={openSettings}
        />
      ) : (
        <OccupancyMap
          nodes={filteredNodes}
          byId={byId}
          hits={hits}
          pickedId={pickedId}
          pickedEntries={pickedId ? shelves.entries.get(pickedId) : undefined}
          pickedFailure={pickedId ? shelves.failures.get(pickedId) : undefined}
          onPick={setPickedId}
          onOpenSettings={openSettings}
        />
      )}

      {target && (
        <ShelfSettingsSheet
          location={target}
          canWrite={canWrite}
          canWriteStorages={canWriteStorages}
          onClose={() => setTarget(null)}
        />
      )}
    </div>
  );
}

/** What the colours mean — and that the number is always printed too. */
function Legend() {
  const { t } = useTranslation("warehouse");
  const items = [
    { key: "ok", label: t("occupancy.legend.ok"), swatch: "bg-blue-600" },
    {
      key: "nearlyFull",
      label: t("occupancy.legend.nearlyFull"),
      swatch: "bg-amber-500",
    },
    { key: "over", label: t("occupancy.legend.over"), swatch: "bg-red-500" },
    {
      key: "noLimit",
      label: t("occupancy.legend.noLimit"),
      swatch: "border border-dashed border-gray-400",
    },
  ];
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-2 text-xs text-on-secondary">
      {items.map((item) => (
        <li key={item.key} className="flex items-center gap-1.5">
          <span
            aria-hidden="true"
            className={cn("h-2 w-3.5 rounded-sm", item.swatch)}
          />
          {item.label}
        </li>
      ))}
    </ul>
  );
}
