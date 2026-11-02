import { useEffect, useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ClipboardCheck, EyeOff, MapPin, ScanLine, Search } from "lucide-react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { Checkbox } from "@/components/ui/Checkbox";
import { EmptyState } from "@/components/ui/EmptyState";
import { Input } from "@/components/ui/Input";
import { QueryError } from "@/components/ui/QueryResult";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useReturnTarget } from "@/hooks/useReturnTarget";
import { useScanResolver } from "@/hooks/useScanResolver";
import { extractApiError } from "@/lib/errors";
import { useLocationSearch, useLocationsById } from "@/module-sdk";
import { useDebounce } from "@/module-sdk";
import {
  CountLocationList,
  type CountablePlace,
} from "@/modules/stock_takes/components/CountLocationList";
import StockTakeScanCamera from "@/modules/stock_takes/components/StockTakeScanCamera";
import {
  useCreateStockTake,
  useLocationCountStates,
} from "@/modules/stock_takes/hooks/useStockTakes";
import { formatDate } from "@/utils/formatters";
import { getStorageLocationPath } from "@/utils/helpers";

/** Places one lookup returns; the search narrows the rest. */
const PLACES_PAGE_SIZE = 30;
const SEARCH_DEBOUNCE_MS = 300;

/**
 * The places to offer, the longest without a count first.
 *
 * A page the server answers for what was typed — never the organization's
 * locations — with the place already chosen (a scanned label, a due task's
 * link) added when it is not on that page.
 */
function usePlaces(
  query: string,
  selectedId: string | null,
): {
  places: CountablePlace[] | undefined;
  /** The place chosen, whether or not the page on screen holds it. */
  chosen: CountablePlace | undefined;
  isError: boolean;
  isSearching: boolean;
  hasNoPlaces: boolean;
  refetch: () => void;
} {
  const typed = query.trim();
  const debounced = useDebounce(typed, SEARCH_DEBOUNCE_MS);
  // The locations a general screen may offer: the organization's policy
  // decides whether module-owned ones are among them.
  const list = useLocationSearch({}, debounced, { limit: PLACES_PAGE_SIZE });
  const states = useLocationCountStates();
  const listed = list.data?.items;
  const onPage = listed?.some((storage) => storage.id === selectedId) ?? false;
  const named = useLocationsById(!selectedId || onPage ? [] : [selectedId]);
  const { places, chosen } = useMemo(() => {
    if (!listed || !states.data)
      return { places: undefined, chosen: undefined };
    const byId = new Map(
      states.data.map((state) => [state.location_id, state]),
    );
    const place = (storage: (typeof listed)[number]): CountablePlace => ({
      id: storage.id,
      path: getStorageLocationPath(storage),
      lastCountedAt: byId.get(storage.id)?.last_counted_at ?? null,
      stockTakeId: byId.get(storage.id)?.stock_take_id ?? null,
    });
    const offStage = named.byId.get(selectedId ?? "");
    const rows =
      !onPage && offStage && !debounced ? [offStage, ...listed] : listed;
    const found = onPage ? listed.find((s) => s.id === selectedId) : offStage;
    return {
      places: rows
        .map(place)
        .sort(
          (a, b) =>
            (a.lastCountedAt ?? "").localeCompare(b.lastCountedAt ?? "") ||
            a.path.localeCompare(b.path),
        ),
      chosen: found ? place(found) : undefined,
    };
  }, [listed, states.data, named.byId, selectedId, onPage, debounced]);
  return {
    places,
    chosen,
    isError: list.isError || states.isError,
    // Typed text the server has not been asked about yet: the rows on screen
    // answer the previous query.
    isSearching: typed !== debounced,
    hasNoPlaces: !debounced && list.data?.total === 0,
    refetch: () => {
      void list.refetch();
      void states.refetch();
    },
  };
}

/**
 * Count a location: choose it or scan its label, then count what is on it.
 *
 * The screen is the start of the count and nothing else — the counting
 * itself is the counting screen every stock take uses, on the phone or at a
 * desk. Each place says when it was last counted, so the one counted longest
 * ago is at the top. A blind count hides what the system expects. Closing
 * the count posts its differences as one stock adjustment.
 */
export default function CountLocationPage() {
  const { t } = useTranslation(["stock_takes", "common"]);
  const { setHeader } = useModulePageHeader();
  const backTo = useReturnTarget();
  const canWrite = useCanWrite("stock_takes");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [selectedId, setSelectedId] = useState<string | null>(
    searchParams.get("location"),
  );
  const [query, setQuery] = useState("");
  const [code, setCode] = useState("");
  const [blind, setBlind] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const { places, chosen, isError, isSearching, hasNoPlaces, refetch } =
    usePlaces(query, selectedId);
  const create = useCreateStockTake();

  useEffect(() => {
    setHeader({ title: t("count.title"), backTo });
  }, [t, setHeader, backTo]);

  const { resolve, isResolving } = useScanResolver({
    handle: (result) => {
      if (result.action !== "set_storage_context" || !result.location)
        return false;
      if ("vibrate" in navigator) navigator.vibrate(100);
      setCode("");
      setSelectedId(result.location.id);
      return true;
    },
  });

  if (isError) return <QueryError onRetry={refetch} />;
  if (!places) return <LoadingSpinner />;
  if (hasNoPlaces)
    return (
      <EmptyState
        icon={MapPin}
        title={t("count.noPlacesTitle")}
        description={t("count.noPlacesDescription")}
      />
    );

  const start = () => {
    if (!chosen) return;
    setError(null);
    create.mutate(
      {
        location_id: chosen.id,
        name: t("count.name", {
          location: chosen.path,
          date: formatDate(new Date().toISOString()),
        }),
        blind_mode: blind,
      },
      {
        onSuccess: (stockTake) =>
          navigate(`/inventory/stock-takes/${stockTake.id}/counting`),
        onError: (failure: unknown) =>
          setError(extractApiError(failure, t("errors.createFailed"))),
      },
    );
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="stock_takes" />
      <Card className="space-y-3 p-4">
        <p className="text-sm text-on-secondary">{t("count.intro")}</p>
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (code.trim()) void resolve(code.trim());
          }}
        >
          <Input
            label={t("count.scanLabel")}
            value={code}
            onChange={(event) => setCode(event.target.value)}
            leftIcon={<ScanLine size={16} />}
            disabled={isResolving}
            autoComplete="off"
          />
        </form>
        <StockTakeScanCamera onCode={(scanned) => void resolve(scanned)} />
      </Card>

      <div className="space-y-3">
        <Input
          aria-label={t("count.searchLabel")}
          placeholder={t("count.searchPlaceholder")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          leftIcon={<Search size={16} />}
        />
        {places.length === 0 && !isSearching ? (
          <EmptyState
            icon={Search}
            title={t("count.noMatchTitle")}
            description={t("count.noMatchDescription")}
          />
        ) : (
          <CountLocationList
            places={places}
            selectedId={selectedId}
            onSelect={setSelectedId}
            onResume={(id) => navigate(`/inventory/stock-takes/${id}/counting`)}
          />
        )}
      </div>

      {/* Pinned to the bottom: on a phone the place is chosen far down a
          long list, and the button that counts it stays in reach. One row
          from `sm` up -- two stacked ones covered the lower rows of a short
          window, and a click on the row's middle landed on the card. */}
      {canWrite && (
        <Card className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px)+0.5rem)] z-[var(--z-sticky)] flex flex-wrap items-center justify-between gap-x-4 gap-y-3 p-4 shadow-lg md:bottom-2">
          <label className="flex cursor-pointer items-center gap-2">
            <Checkbox
              checked={blind}
              onChange={(event) => setBlind(event.target.checked)}
            />
            <EyeOff size={18} className="text-on-muted" />
            <span className="text-sm text-on-secondary">
              {t("count.blind")}
            </span>
          </label>
          <Button
            className="w-full sm:w-auto"
            leftIcon={<ClipboardCheck size={16} />}
            disabled={!chosen || create.isPending}
            onClick={start}
          >
            {chosen
              ? t("count.start", { location: chosen.path })
              : t("count.chooseFirst")}
          </Button>
          {error && (
            <p role="alert" className="basis-full text-sm text-on-danger">
              {error}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
