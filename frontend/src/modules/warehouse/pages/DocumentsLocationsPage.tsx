import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  keepPreviousData,
  useInfiniteQuery,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { Printer } from "lucide-react";
import { toast } from "sonner";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { EmptyState } from "@/components/ui/EmptyState";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { SelectionToolbar } from "@/components/ui/SelectionToolbar";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useConfirm } from "@/hooks/useConfirm";
import { useScannerInput } from "@/hooks/useScannerInput";
import { useScanResolver } from "@/hooks/useScanResolver";
import { queryKeys } from "@/hooks/queries/keys";
import { api, getEveryPage } from "@/lib/api/client";
import { invalidation } from "@/lib/api/invalidation";
import { storagesApi } from "@/lib/api/storages";
import { cn } from "@/lib/utils";
import { extractApiError } from "@/lib/errors";
import { formatQuantityLocale } from "@/utils/formatters";
import { unitLabel } from "@/lib/i18nHelpers";
import { LocationCombobox, useDebounce, useLocationsById } from "@/module-sdk";
import {
  putawayCapacityApi,
  type PutawayCapacityEntry,
  type PutawayOccupancy,
} from "@/modules/warehouse/api/putaway";
import {
  ShelfSettingsSheet,
  type ShelfSettingsTarget,
} from "@/modules/warehouse/components/ShelfSettingsSheet";
import type { TranslateFn } from "@/types/i18n";
import type { StorageLocationSummary } from "@/types";
import {
  LocationCodesCard,
  numberBranches,
  useShelfLabelSheet,
} from "../components/LocationCodesCard";

/** Number the selected locations 10, 20, 30… in the order the table shows. */
async function numberWalkOrder({
  walk,
  selected,
  confirm,
  queryClient,
  t,
  onDone,
}: {
  /** Reads the warehouse's places in walk order — the ticked ones may stand
   *  outside the page the table shows, so the order is not the table's. */
  walk: () => Promise<FlatLocation[]>;
  selected: Set<string>;
  confirm: ReturnType<typeof useConfirm>["confirm"];
  queryClient: QueryClient;
  t: TranslateFn;
  onDone: () => void;
}) {
  if (selected.size === 0) return;
  if (
    !(await confirm({
      title: t("putaway.locations.bulk.confirmTitle"),
      message: t("putaway.locations.bulk.confirm"),
      confirmLabel: t("putaway.locations.bulk.number"),
    }))
  ) {
    return;
  }
  const ordered = (await walk()).filter((storage) => selected.has(storage.id));
  const results = await Promise.allSettled(
    ordered.map((storage, index) =>
      storagesApi.update(storage.id, { sequence: (index + 1) * 10 }),
    ),
  );
  const failures = results.filter(
    (result): result is PromiseRejectedResult => result.status === "rejected",
  );
  // The writes land one at a time, so a refusal cannot take back the ones
  // before it. Refresh whenever anything landed: the table reads a page of
  // the `storages` list, and leaving the old order on screen while the server
  // holds the new one is the same defect whether the batch fully succeeded or half did.
  if (failures.length < results.length) {
    invalidation.storages(queryClient);
  }
  if (failures.length === 0) {
    toast.success(t("putaway.locations.bulk.done", { count: ordered.length }));
    onDone();
    return;
  }
  if (failures.length === results.length) {
    toast.error(
      extractApiError(failures[0].reason, t("putaway.locations.bulk.error")),
    );
    return;
  }
  toast.error(
    t("putaway.locations.bulk.partial", {
      count: results.length - failures.length,
    }),
  );
}

/** One location of the warehouse, as the table draws it. */
interface FlatLocation {
  id: string;
  name: string;
  shortCode: string | null;
  sequence: number | null;
  path: string;
}

const flatLocation = (row: StorageLocationSummary): FlatLocation => ({
  id: row.id,
  name: row.name,
  shortCode: row.short_code ?? null,
  sequence: row.sequence ?? null,
  path: row.full_path ?? row.name,
});

/** Rows the table asks for at a time; "Show more" asks for the next ones. */
const ROWS_PAGE = 100;
const SEARCH_DEBOUNCE_MS = 300;

/**
 * The places of one warehouse, a page at a time.
 *
 * The warehouse itself comes by id and what stands below it from the
 * locations list (`under`), in the order the walk goes, with the search
 * answered by the server — so the table costs the rows it shows, not the
 * organization's tree. Record counts are not asked for: the occupancy beside
 * each row is its own read.
 */
function useWarehouseRows(warehouseId: string | null, search: string) {
  const needle = useDebounce(search.trim(), SEARCH_DEBOUNCE_MS).toLowerCase();
  const root = useLocationsById(warehouseId ? [warehouseId] : []);
  const below = useInfiniteQuery({
    queryKey: [
      ...queryKeys.storages.all,
      "shelf-settings",
      warehouseId,
      needle,
    ],
    queryFn: ({ pageParam }) =>
      storagesApi.getPage({
        under: warehouseId ?? undefined,
        q: needle || undefined,
        exclude_module_contexts: true,
        counts: false,
        limit: ROWS_PAGE,
        offset: pageParam,
      }),
    initialPageParam: 0,
    getNextPageParam: (last) =>
      last.has_more ? last.offset + last.items.length : undefined,
    enabled: warehouseId !== null,
    placeholderData: keepPreviousData,
  });
  const rootRow = warehouseId ? root.byId.get(warehouseId) : undefined;
  const head = useMemo(() => {
    const row = rootRow ? flatLocation(rootRow) : undefined;
    const matches =
      !needle ||
      row?.name.toLowerCase().includes(needle) ||
      (row?.shortCode ?? "").toLowerCase().includes(needle);
    return { row, matches };
  }, [rootRow, needle]);
  const rows = useMemo(() => {
    return [
      ...(head.row && head.matches ? [head.row] : []),
      ...(below.data?.pages.flatMap((page) => page.items) ?? []).map(
        flatLocation,
      ),
    ];
  }, [head, below.data]);
  return {
    rows,
    warehouse: head.row,
    isLoading: root.isLoading || below.isLoading,
    error: root.error ?? below.error,
    retry: () => {
      if (root.isError) void root.refetch();
      if (below.isError) void below.refetch();
    },
    /** Every place the search names (every place when `matching` is false),
     *  past the pages shown, in walk order: a printed sheet of "the list" and
     *  a numbering of the ticked ones must not stop where the table does. */
    every: async (matching: boolean) => {
      const all = await getEveryPage<StorageLocationSummary>("/locations", {
        under: warehouseId,
        q: matching ? needle || undefined : undefined,
        exclude_module_contexts: true,
        counts: false,
      });
      return [
        ...(head.row && (!matching || head.matches) ? [head.row] : []),
        ...all.map(flatLocation),
      ];
    },
    hasMore: Boolean(below.hasNextPage),
    loadingMore: below.isFetchingNextPage,
    loadMore: () => void below.fetchNextPage(),
  };
}

/**
 * The ticked rows, and the "all of them" box above the column.
 *
 * A tick outlives the search that showed it, so the rows are kept with their
 * ids: an action on the selection needs the path of a row the table no
 * longer holds.
 */
function useRowSelection(rows: FlatLocation[]) {
  const [ticked, setTicked] = useState<Map<string, FlatLocation>>(new Map());
  const selected = useMemo(() => new Set(ticked.keys()), [ticked]);
  const toggleSelected = (id: string) => {
    setTicked((current) => {
      const next = new Map(current);
      const row = rows.find((storage) => storage.id === id);
      if (next.has(id)) next.delete(id);
      else if (row) next.set(id, row);
      return next;
    });
  };
  const allVisibleSelected =
    rows.length > 0 && rows.every((storage) => selected.has(storage.id));
  const someVisibleSelected =
    !allVisibleSelected && rows.some((storage) => selected.has(storage.id));
  const toggleAllVisible = () => {
    setTicked((current) => {
      const next = new Map(current);
      for (const storage of rows) {
        if (allVisibleSelected) next.delete(storage.id);
        else next.set(storage.id, storage);
      }
      return next;
    });
  };
  return {
    selected,
    selectedRows: [...ticked.values()],
    clearSelected: () => setTicked(new Map()),
    toggleSelected,
    toggleAllVisible,
    allVisibleSelected,
    someVisibleSelected,
  };
}

/**
 * What a scanned shelf label does here: find the shelf by id, move the
 * filter to the warehouse it stands in unless the table already holds it, and
 * open its settings.
 */
function useShelfScan({
  warehouse,
  onWarehouse,
  onSearch,
  onOpen,
}: {
  warehouse: FlatLocation | undefined;
  onWarehouse: (id: string) => void;
  onSearch: (search: string) => void;
  onOpen: (target: ShelfSettingsTarget) => void;
}) {
  const { t } = useTranslation("warehouse");
  return useScanResolver({
    handle: async (result) => {
      const location = result.location;
      if (!location) return false;
      const page = await storagesApi.getPage({
        ids: [location.id],
        exclude_module_contexts: true,
        counts: false,
        limit: 1,
      });
      const summary = page.items[0];
      if (!summary) {
        toast.error(t("putaway.locations.scan.notFound"));
        return true;
      }
      const path = summary.full_path ?? summary.name;
      const inside =
        warehouse &&
        (path === warehouse.path || path.startsWith(`${warehouse.path} → `));
      if (!inside) {
        const [top] = await storagesApi.getBreadcrumb(location.id);
        if (top) onWarehouse(top.id);
      }
      onSearch("");
      onOpen({
        id: summary.id,
        name: summary.name,
        sequence: summary.sequence,
        full_path: path,
      });
      return true;
    },
  });
}

/**
 * The shelf-settings tab: the locations of one warehouse, with the walk
 * order, product mixing and per-product limits that used to be spread over
 * three screens — the location's Edit dialog and two cards at the very
 * bottom of its detail page, thousands of pixels under the contents.
 *
 * Reading is open to the module's readers; the panel only offers its
 * controls to accounts that may write.
 */
export default function DocumentsLocationsPage() {
  const { t } = useTranslation(["warehouse", "common"]);
  const canWrite = useCanWrite("warehouse");
  // Walk order lives on the storage register, not in this module: PUT
  // /storages/{id} checks `locations:write`, while the limits and the mix flag
  // below are documents endpoints. Each control asks for the key its own
  // request will be checked against, so none of them offers a write the
  // server would refuse.
  const canWriteStorages = useCanWrite("locations");
  const queryClient = useQueryClient();
  const { confirm, confirmDialogProps } = useConfirm();

  // Where the table starts when the reader has not chosen: the first
  // top-level place, asked as a one-row page.
  const {
    data: firstTopLevel,
    isLoading: topLevelLoading,
    isError: topLevelError,
    error: topLevelFailure,
    refetch: refetchTopLevel,
  } = useQuery({
    queryKey: [...queryKeys.storages.all, "shelf-settings", "first"],
    queryFn: () =>
      storagesApi.getPage({
        top_level: true,
        exclude_module_contexts: true,
        counts: false,
        limit: 1,
      }),
  });

  const {
    data: capacity,
    isError: capacityError,
    error: capacityFailure,
    refetch: refetchCapacity,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacityAll,
    queryFn: () => putawayCapacityApi.list(),
  });

  const {
    data: settings,
    isError: settingsError,
    error: settingsFailure,
    refetch: refetchSettings,
  } = useQuery({
    queryKey: queryKeys.documents.putawayCapacitySettings,
    queryFn: () => putawayCapacityApi.listSettings(),
  });

  const [chosenId, setChosenId] = useState<string | null>(null);
  const warehouseId = chosenId ?? firstTopLevel?.items[0]?.id ?? null;
  const [search, setSearch] = useState("");
  const [panelTarget, setPanelTarget] = useState<ShelfSettingsTarget | null>(
    null,
  );
  // A selection's labels, or the stickers a renumbering left to replace.
  const labels = useShelfLabelSheet();

  const {
    data: occupancy,
    isError: occupancyError,
    error: occupancyFailure,
    refetch: refetchOccupancy,
  } = useQuery({
    queryKey: queryKeys.documents.putawayOccupancy(warehouseId ?? ""),
    enabled: Boolean(warehouseId),
    queryFn: async (): Promise<PutawayOccupancy> => {
      const response = await api.get<PutawayOccupancy>(
        `/warehouse/putaway/occupancy/${warehouseId}`,
      );
      return response.data;
    },
  });

  const capacityByLocation = useMemo(() => {
    const map = new Map<string, PutawayCapacityEntry[]>();
    for (const entry of capacity ?? []) {
      const list = map.get(entry.location_id) ?? [];
      list.push(entry);
      map.set(entry.location_id, list);
    }
    return map;
  }, [capacity]);

  const singleProductByLocation = useMemo(
    () =>
      new Map(
        (settings ?? []).map((setting) => [
          setting.location_id,
          setting.single_product,
        ]),
      ),
    [settings],
  );

  const occupancyByLocation = useMemo(
    () =>
      new Map(
        (occupancy?.locations ?? []).map((cell) => [cell.location_id, cell]),
      ),
    [occupancy],
  );

  // Every location of the warehouse, not only its leaves: a location that
  // holds others can hold stock itself, and its walk order and limits are the
  // same settings this table exists to edit.
  const {
    rows,
    warehouse,
    isLoading: rowsLoading,
    error: rowsFailure,
    retry: retryRows,
    hasMore,
    loadingMore,
    loadMore,
    every,
  } = useWarehouseRows(warehouseId, search);
  const {
    selected,
    selectedRows,
    clearSelected,
    toggleSelected,
    toggleAllVisible,
    allVisibleSelected,
    someVisibleSelected,
  } = useRowSelection(rows);
  const needle = search.trim().toLowerCase();

  const selectWarehouse = (id: string | null) => {
    setChosenId(id);
    clearSelected();
    setPanelTarget(null);
  };

  // A scanned shelf label opens that shelf's settings, wherever the filter
  // currently stands: the scan is the reader naming the row.
  const { resolve } = useShelfScan({
    warehouse,
    onWarehouse: setChosenId,
    onSearch: setSearch,
    onOpen: setPanelTarget,
  });
  useScannerInput((code) => void resolve(code), { enabled: !panelTarget });

  const numberSelected = () =>
    numberWalkOrder({
      walk: () => every(false),
      selected,
      confirm,
      queryClient,
      t,
      onDone: clearSelected,
    });

  if (topLevelError || capacityError || settingsError) {
    return (
      <div className="space-y-6">
        <QueryFailure
          error={topLevelFailure ?? capacityFailure ?? settingsFailure}
          message={t("errors.loadLocationsFailed")}
          onRetry={() => {
            void refetchTopLevel();
            void refetchCapacity();
            void refetchSettings();
          }}
        />
      </div>
    );
  }

  if (topLevelLoading || !firstTopLevel || !capacity || !settings) {
    return (
      <div className="space-y-6">
        <LoadingSpinner />
      </div>
    );
  }

  if (!warehouseId) {
    return (
      <div className="space-y-6">
        <EmptyState
          title={t("putaway.locations.empty.title")}
          description={t("putaway.locations.empty.description")}
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="warehouse" />
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("putaway.locations.searchPlaceholder"),
        }}
        resultCount={rows.length}
        primaryAction={
          <WarehouseAndPrint
            warehouseId={warehouseId}
            onSelect={selectWarehouse}
            onPrint={
              rows.length > 0
                ? () =>
                    void every(true).then((all) =>
                      labels.print(all.map((row) => row.id)),
                    )
                : undefined
            }
          />
        }
      />

      {warehouseId && (
        <LocationCodesCard
          locationId={warehouseId}
          canWrite={canWriteStorages}
          confirm={confirm}
          onPrint={labels.print}
        />
      )}

      {occupancyError && (
        <QueryFailure
          error={occupancyFailure}
          message={t("errors.loadOccupancyFailed")}
          onRetry={() => void refetchOccupancy()}
        />
      )}

      {rowsFailure ? (
        <QueryFailure
          error={rowsFailure}
          message={t("errors.loadLocationsFailed")}
          onRetry={retryRows}
        />
      ) : rowsLoading ? (
        <LoadingSpinner />
      ) : rows.length === 0 ? (
        <p className="rounded-xl border border-border px-4 py-6 text-center text-sm text-on-secondary">
          {needle
            ? t("putaway.locations.noMatch")
            : t("putaway.locations.emptyNoShelf")}
        </p>
      ) : (
        <LocationsTable
          locations={rows}
          selected={selected}
          canWrite={canWriteStorages}
          capacityByLocation={capacityByLocation}
          singleProductByLocation={singleProductByLocation}
          occupancyByLocation={occupancyByLocation}
          allVisibleSelected={allVisibleSelected}
          someVisibleSelected={someVisibleSelected}
          onToggleSelected={toggleSelected}
          onToggleAll={toggleAllVisible}
          onOpen={(storage) =>
            setPanelTarget({
              id: storage.id,
              name: storage.name,
              sequence: storage.sequence,
              full_path: storage.path,
            })
          }
        />
      )}
      {hasMore && (
        <div className="flex justify-center">
          <Button variant="outline" onClick={loadMore} disabled={loadingMore}>
            {t("putaway.locations.showMore")}
          </Button>
        </div>
      )}
      <SelectionActions
        selected={selected}
        rows={selectedRows}
        canWrite={canWriteStorages}
        onClear={clearSelected}
        onPrint={() => labels.print([...selected])}
        onNumberWalk={() => void numberSelected()}
      />
      {labels.sheet}

      {panelTarget && (
        <ShelfSettingsSheet
          location={panelTarget}
          canWrite={canWrite}
          canWriteStorages={canWriteStorages}
          onClose={() => setPanelTarget(null)}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}

/**
 * The warehouse picker and, beside it, the print button for the list as it
 * stands. Printing a sticker is not a write to the register, so the button is
 * open to every reader; the row checkboxes narrow it to a selection.
 */
function WarehouseAndPrint({
  warehouseId,
  onSelect,
  onPrint,
}: {
  warehouseId: string;
  onSelect: (id: string | null) => void;
  onPrint?: () => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <>
      <div className="w-56">
        <LocationCombobox
          label={t("putaway.locations.storage")}
          scope={{ purpose: "stock" }}
          value={warehouseId}
          onChange={(id) => onSelect(id || null)}
          title={t("putaway.locations.storage")}
        />
      </div>
      {onPrint && (
        <Button
          variant="outline"
          leftIcon={<Printer size={16} />}
          onClick={onPrint}
        >
          {t("putaway.locations.codes.printList")}
        </Button>
      )}
    </>
  );
}

/** What a selection of shelves can be given: labels, codes, a walk order. */
function SelectionActions({
  selected,
  rows,
  canWrite,
  onClear,
  onPrint,
  onNumberWalk,
}: {
  selected: Set<string>;
  rows: FlatLocation[];
  canWrite: boolean;
  onClear: () => void;
  onPrint: () => void;
  onNumberWalk: () => void;
}) {
  const { t } = useTranslation("warehouse");
  const queryClient = useQueryClient();
  const giveCodes = () =>
    numberBranches({
      ids: [...selected],
      paths: new Map(rows.map((row) => [row.id, row.path])),
      queryClient,
      t,
      onDone: onClear,
    });
  return (
    <SelectionToolbar count={selected.size} onClear={onClear} width="wide">
      <Button
        variant="outline"
        size="sm"
        leftIcon={<Printer size={16} />}
        onClick={onPrint}
      >
        {t("putaway.locations.codes.printLabels")}
      </Button>
      {canWrite && (
        <Button variant="outline" size="sm" onClick={() => void giveCodes()}>
          {t("putaway.locations.codes.giveCodes")}
        </Button>
      )}
      {canWrite && (
        <Button variant="outline" size="sm" onClick={onNumberWalk}>
          {t("putaway.locations.bulk.number")}
        </Button>
      )}
    </SelectionToolbar>
  );
}

interface LocationsTableProps {
  locations: FlatLocation[];
  selected: Set<string>;
  canWrite: boolean;
  capacityByLocation: Map<string, PutawayCapacityEntry[]>;
  singleProductByLocation: Map<string, boolean>;
  occupancyByLocation: Map<string, PutawayOccupancy["locations"][number]>;
  allVisibleSelected: boolean;
  someVisibleSelected: boolean;
  onToggleSelected: (id: string) => void;
  onToggleAll: () => void;
  onOpen: (location: FlatLocation) => void;
}

/** The tick of one place, in the table row and on the phone card alike. */
function RowCheckbox({
  name,
  checked,
  onToggle,
}: {
  name: string;
  checked: boolean;
  onToggle: () => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <Checkbox
      aria-label={t("putaway.locations.selectAria", { name })}
      checked={checked}
      onChange={onToggle}
    />
  );
}

/** The table of one storage's locations, with its bulk selection. */
function LocationsTable({
  locations,
  selected,
  canWrite,
  capacityByLocation,
  singleProductByLocation,
  occupancyByLocation,
  allVisibleSelected,
  someVisibleSelected,
  onToggleSelected,
  onToggleAll,
  onOpen,
}: LocationsTableProps) {
  const { t } = useTranslation("warehouse");
  // Five columns do not fit a phone: the table scrolled sideways inside its
  // card and cut the mixing column. A phone gets one card per place instead.
  const isPhone = useMediaQuery("(max-width: 639px)");
  if (isPhone) {
    return (
      <ul className="space-y-3">
        {locations.map((storage) => {
          const limits = capacityByLocation.get(storage.id) ?? [];
          const single = singleProductByLocation.get(storage.id) ?? false;
          return (
            <li
              key={storage.id}
              className="space-y-3 rounded-xl border border-border bg-surface-card p-3"
            >
              <div className="flex items-start gap-2">
                {canWrite && (
                  <RowCheckbox
                    name={storage.name}
                    checked={selected.has(storage.id)}
                    onToggle={() => onToggleSelected(storage.id)}
                  />
                )}
                <Button
                  variant="ghost"
                  size="content"
                  className="h-auto min-h-11 flex-1 justify-start px-1 py-0.5 text-left"
                  onClick={() => onOpen(storage)}
                >
                  <span className="block font-medium text-on">
                    {storage.name}
                  </span>
                  <span className="block text-xs text-on-secondary">
                    {storage.shortCode ?? storage.path}
                  </span>
                </Button>
              </div>
              <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
                <dt className="text-on-secondary">
                  {t("putaway.locations.columns.walkOrder")}
                </dt>
                <dd className="tabular-nums text-on">
                  {storage.sequence ?? "—"}
                </dd>
                <dt className="text-on-secondary">
                  {t("putaway.locations.columns.mixing")}
                </dt>
                <dd className="text-on">
                  {single
                    ? t("putaway.locations.mixing.single")
                    : t("putaway.locations.mixing.mixed")}
                </dd>
                <dt className="text-on-secondary">
                  {t("putaway.locations.columns.limits")}
                </dt>
                <dd className="text-on">
                  {limits.length === 0
                    ? t("putaway.locations.limits.none")
                    : t("putaway.locations.limits.count", {
                        count: limits.length,
                      })}
                </dd>
                <dt className="text-on-secondary">
                  {t("putaway.locations.columns.occupancy")}
                </dt>
                <dd>
                  <OccupancyCell cell={occupancyByLocation.get(storage.id)} />
                </dd>
              </dl>
            </li>
          );
        })}
      </ul>
    );
  }
  return (
    <div className="overflow-x-auto rounded-xl border border-border">
      <table className="w-full text-sm">
        <thead className="bg-surface-raised text-left text-on-secondary">
          <tr>
            <th scope="col" className="w-10 px-3 py-3">
              {canWrite && (
                <Checkbox
                  aria-label={t("putaway.locations.selectAll")}
                  checked={allVisibleSelected}
                  indeterminate={someVisibleSelected}
                  onChange={onToggleAll}
                />
              )}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {t("putaway.locations.columns.location")}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {t("putaway.locations.columns.walkOrder")}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {t("putaway.locations.columns.mixing")}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {t("putaway.locations.columns.limits")}
            </th>
            <th scope="col" className="px-4 py-3 font-medium">
              {t("putaway.locations.columns.occupancy")}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {locations.map((storage) => {
            const limits = capacityByLocation.get(storage.id) ?? [];
            const cell = occupancyByLocation.get(storage.id);
            const single = singleProductByLocation.get(storage.id) ?? false;
            return (
              <tr key={storage.id} className="hover:bg-surface-raised/50">
                <td className="px-3 py-3 align-middle">
                  {canWrite && (
                    <RowCheckbox
                      name={storage.name}
                      checked={selected.has(storage.id)}
                      onToggle={() => onToggleSelected(storage.id)}
                    />
                  )}
                </td>
                <td className="px-4 py-3">
                  <Button
                    variant="ghost"
                    size="content"
                    className="h-auto justify-start px-1 py-0.5 text-left"
                    onClick={() => onOpen(storage)}
                  >
                    <span className="block font-medium text-on">
                      {storage.name}
                    </span>
                    <span className="block text-xs text-on-secondary">
                      {storage.shortCode ?? storage.path}
                    </span>
                  </Button>
                </td>
                <td className="px-4 py-3 text-on-secondary tabular-nums">
                  {storage.sequence ?? "—"}
                </td>
                <td className="px-4 py-3 text-on-secondary">
                  {single
                    ? t("putaway.locations.mixing.single")
                    : t("putaway.locations.mixing.mixed")}
                </td>
                <td className="px-4 py-3 text-on-secondary">
                  {limits.length === 0
                    ? t("putaway.locations.limits.none")
                    : t("putaway.locations.limits.count", {
                        count: limits.length,
                      })}
                </td>
                <td className="px-4 py-3">
                  <OccupancyCell cell={cell} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * One shelf's occupancy as the shared fill response reads it: the bar is the
 * sum of every limited product's share, so a shelf several products share
 * shows that sum rather than one product's pair. One product's pair alone
 * would call a half-full shelf half empty, and the bar and the number would
 * disagree. Stock without a limit takes no share, and the cell says so rather
 * than letting the percentage pass for the whole shelf. An unlimited shelf's
 * fill is undefined, not zero, and this never draws one.
 */
function OccupancyCell({
  cell,
}: {
  cell: PutawayOccupancy["locations"][number] | undefined;
}) {
  const { t } = useTranslation(["warehouse", "items"]);
  const fill = cell?.fill ?? null;
  if (!cell || fill === null) {
    return (
      <span className="text-xs text-on-secondary">
        {t("putaway.locations.occupancy.noLimit", {
          count: cell?.items_count ?? 0,
        })}
      </span>
    );
  }
  const shared = cell.capped_products > 1;
  // The pair speaks the unit its limit was declared in, the one the settings
  // panel writes beside the limit; a product with no unit recorded gets the
  // dash and the reason, never a unit made up for it.
  const unitSymbol = cell.entries.find(
    (entry) => entry.share !== null,
  )?.product_unit_symbol;
  return (
    <div className="min-w-40 space-y-1">
      <p
        className="text-xs text-on-secondary tabular-nums"
        title={
          shared || unitSymbol ? undefined : t("items:stock.noUnitRecorded")
        }
      >
        {shared
          ? t("putaway.locations.occupancy.sharesSum", {
              fill,
              count: cell.capped_products,
            })
          : `${formatQuantityLocale(cell.capacity_used ?? "")}/${formatQuantityLocale(cell.capacity_max ?? "")} ${unitLabel(t, unitSymbol) || "—"}`}
      </p>
      {cell.unmeasured && (
        <p className="text-xs text-on-secondary">
          {t("putaway.locations.occupancy.unmeasured")}
        </p>
      )}
      <div
        className="h-2 w-full overflow-hidden rounded-full bg-surface-raised"
        role="meter"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={fill}
        aria-label={cell.location_name ?? undefined}
      >
        <div
          className={cn(
            "h-full rounded-full",
            cell.status === "over"
              ? "bg-red-500"
              : cell.status === "nearly_full"
                ? "bg-amber-500"
                : "bg-success-500",
          )}
          style={{ width: `${Math.min(fill, 100)}%` }}
        />
      </div>
      {shared && cell.capacity_product_name && (
        <p className="text-xs text-on-secondary">
          {t("putaway.locations.occupancy.fullest", {
            name: cell.capacity_product_name,
            count: cell.capped_products,
          })}
        </p>
      )}
    </div>
  );
}
