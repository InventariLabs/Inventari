import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { itemsApi } from "@/lib/api/items";
import { productTemplatesApi } from "@/lib/api/productTemplates";
import { queryKeys } from "@/hooks/queries/keys";
import { categoryLabel, unitLabel } from "@/lib/i18nHelpers";
import { productCode } from "@/types/inventory";
import { formatQuantityLocale } from "@/utils/formatters";
import { moduleRegistry } from "@/lib/moduleRegistry";
import type { Item } from "@/types";
import type { SearchResult } from "@/lib/moduleRegistry";
import type { TranslateFn } from "@/types/i18n";

/**
 * Where the typed string hit the record, best field first.
 *
 * Mirrors the backend matcher's field set — name, brand, the codes, the
 * serial — because the reader is owed the same story the server matched on.
 * The codes include the product code a scan-created record carries on its
 * template: it rides the wire beside the record, and a reader who typed it
 * gets the code rank and its name. A hit on a field nothing on the wire
 * holds ranks last rather than inventing a reason for itself.
 */
type MatchField = "name" | "brand" | "code" | "serial" | "unattributed";

interface ItemMatch {
  rank: number;
  field: MatchField;
}

/** A name typed from its beginning is the hit the reader meant; a name
 *  carrying the string somewhere in the middle is the runner-up. */
const NAME_PREFIX_RANK = 0;
const NAME_CONTAINS_RANK = 1;
const BRAND_RANK = 2;
const CODE_RANK = 3;
const SERIAL_RANK = 4;
const UNATTRIBUTED_RANK = 5;

export function matchOf(item: Item, query: string): ItemMatch {
  const q = query.trim().toLowerCase();
  const contains = (value: string | null | undefined) =>
    !!value && value.toLowerCase().includes(q);
  if (contains(item.name)) {
    return {
      rank: item.name.toLowerCase().startsWith(q)
        ? NAME_PREFIX_RANK
        : NAME_CONTAINS_RANK,
      field: "name",
    };
  }
  if (contains(item.brand)) return { rank: BRAND_RANK, field: "brand" };
  if (
    contains(item.barcode) ||
    contains(item.label_code) ||
    contains(item.template?.barcode)
  ) {
    return { rank: CODE_RANK, field: "code" };
  }
  if (contains(item.serial_number)) {
    return { rank: SERIAL_RANK, field: "serial" };
  }
  return { rank: UNATTRIBUTED_RANK, field: "unattributed" };
}

/**
 * Name hits before brand hits, brand before codes, codes before serials —
 * the order a reader would have typed them in. The server's own order is
 * kept inside a rank (the sort is stable), so this decides only which field
 * won, not how the server ordered its own answer.
 */
export function rankItemsByRelevance(items: Item[], query: string): Item[] {
  return items
    .map((item) => ({ item, match: matchOf(item, query) }))
    .sort((a, b) => a.match.rank - b.match.rank)
    .map((entry) => entry.item);
}

/** Exported for the palette's tests: the row is where the ranking and the
 *  honesty about the hit become visible to the reader. */
/** The row says what the record hit on when it hit on anything but the
 * name — a brand match left standing next to a name the query barely
 * touches reads like the search engine's mistake, and the reader stops
 * trusting the answers. */
function matchReason(
  field: MatchField,
  item: Item,
  query: string,
  t: TranslateFn,
): string | undefined {
  const q = query.trim().toLowerCase();
  const said = (value: string | null | undefined) =>
    !!value && value.toLowerCase().includes(q);
  if (field === "brand" && item.brand) {
    return t("commandPalette.matchedByBrand", { value: item.brand });
  }
  if (field === "code") {
    // A record can carry several codes (its own barcode, a label, the
    // product code on the template); the reason names the one the reader's
    // string actually hit, not the first that happens to be filled.
    const value = [item.barcode, item.label_code, item.template?.barcode].find(
      said,
    );
    if (value) return t("commandPalette.matchedByCode", { value });
  }
  if (field === "serial" && item.serial_number) {
    return t("commandPalette.matchedBySerial", { value: item.serial_number });
  }
  return undefined;
}

/** Exported for the palette's tests: the row is where the ranking and the
 * honesty about the hit become visible to the reader. */
export function itemToResult(
  item: Item,
  t: TranslateFn,
  query: string,
): SearchResult {
  const { field } = matchOf(item, query);
  const reason = matchReason(field, item, query, t);

  return {
    id: `item-${item.id}`,
    title: item.name,
    subtitle:
      reason ?? (usedUp(item) ? t("usedUpRecord") : identityLine(item, t)),
    path: `/inventory/items/${item.id}`,
    module: "inventory",
  };
}

/** What is known about a product's whole stock: the backend's own sum over
 *  every record of it, not the part of it the search window happened to hold. */
export interface ProductTotal {
  quantity: string;
  uom: string | null;
}

/** One product with every record of it that the search found. */
interface ProductHit {
  /** The best-ranked record: the one the hit opens. */
  item: Item;
  records: Item[];
}

/** A product is one hit, however many records it has: a tin held on three
 *  shelves and in two batches answered as five identical rows, and the
 *  reader could not tell which to open. Records of one catalogue card are one
 *  product; a record with no card is its own. Ranking order is kept — a
 *  product sits where its best record did. */
function groupByProduct(items: Item[]): ProductHit[] {
  const hits = new Map<string, ProductHit>();
  for (const item of items) {
    const key = item.template_id ?? item.id;
    const hit = hits.get(key);
    if (hit) hit.records.push(item);
    else hits.set(key, { item, records: [item] });
  }
  return [...hits.values()];
}

/** How much of the product there is. The backend's sum when it was fetched,
 *  else what the found records add up to. */
function productAmount(
  hit: ProductHit,
  t: TranslateFn,
  totals: ReadonlyMap<string, ProductTotal>,
): string | undefined {
  const known = hit.item.template_id
    ? totals.get(hit.item.template_id)
    : undefined;
  if (known) {
    const amount = formatQuantityLocale(known.quantity, 3);
    const unit = unitLabel(t, known.uom);
    return unit ? `${amount} ${unit}` : amount;
  }
  const sum = hit.records.reduce((acc, r) => acc + Number(r.quantity ?? 0), 0);
  const amount = formatQuantityLocale(String(sum), 3);
  const unit = unitLabel(t, hit.item.uom?.symbol);
  return unit ? `${amount} ${unit}` : amount;
}

/** One hit per product, with its total; the list reads its own ties: two
 *  products drawing the same characters — one name, one brand line,
 *  whatever the reason — are two answers the reader cannot choose between,
 *  and the quantity they disagree about sat unused beside them. Where rows
 *  collide, each says how much it holds, and a row standing alone keeps the
 *  clean line it earned. */
export function itemsToResults(
  items: Item[],
  t: TranslateFn,
  query: string,
  totals: ReadonlyMap<string, ProductTotal> = new Map(),
): SearchResult[] {
  const rows = groupByProduct(items).map((hit) => {
    const result = itemToResult(hit.item, t, query);
    if (hit.records.length < 2) return { hit, result };
    const total = t("commandPalette.productTotal", {
      amount: productAmount(hit, t, totals),
      count: hit.records.length,
    });
    return {
      hit,
      result: {
        ...result,
        subtitle: matchReason(
          matchOf(hit.item, query).field,
          hit.item,
          query,
          t,
        )
          ? `${result.subtitle} · ${total}`
          : total,
      },
    };
  });
  const ties = new Map<string, number>();
  for (const { result } of rows) {
    const key = `${result.title}\u0000${result.subtitle ?? ""}`;
    ties.set(key, (ties.get(key) ?? 0) + 1);
  }
  return rows.map(({ hit, result }) => {
    const key = `${result.title}\u0000${result.subtitle ?? ""}`;
    if ((ties.get(key) ?? 1) < 2 || hit.records.length > 1) return result;
    const amount = quantityLine(hit.item, t);
    if (amount === undefined) return result;
    return {
      ...result,
      subtitle: result.subtitle ? `${result.subtitle} · ${amount}` : amount,
    };
  });
}

/** Whatever tells this record apart from the one below it. Four hits
 * reading "Oliwa z oliwek extra virgin" over the same category name are
 * four hits nobody can choose between, while the serial numbers, brands
 * and quantities that would have separated them sat unused in the data.
 * The category comes last — two different records can share one, so it is
 * the answer only when nothing on the record says more. */
function identityLine(item: Item, t: TranslateFn): string | undefined {
  if (item.serial_number) return item.serial_number;
  if (item.label_code) return item.label_code;
  const code = productCode(item);
  if (code) return code;
  if (item.brand) return item.brand;
  const amount = quantityLine(item, t);
  if (amount) return amount;
  if (item.category) {
    return categoryLabel(t, item.category.code, item.category.name);
  }
  return undefined;
}

/** A record the reader consumed to zero: it left the products list (the
 *  internal-usage default hides its virtual location), so the palette says
 *  so instead of presenting it like stock on a shelf. */
function usedUp(item: Item): boolean {
  return Number(item.quantity) <= 0;
}

/** How much of it there is, in the record's own unit — the plainest thing
 *  two records of one name can disagree about. A record that names no
 *  quantity says nothing here rather than printing the word "undefined". */
function quantityLine(item: Item, t: TranslateFn): string | undefined {
  const raw = item.quantity;
  if (raw === null || raw === undefined) return undefined;
  const amount = formatQuantityLocale(String(raw), 3);
  const unit = unitLabel(t, item.uom?.symbol);
  return unit ? `${amount} ${unit}` : amount;
}

/**
 * The records stay records in the cache: the subtitle is in the reader's
 * language, and a language switch should re-word it, not wait for a refetch.
 */
interface SearchHits {
  items: Item[];
  /** Whole-product sums for the products found as several records. */
  totals: ReadonlyMap<string, ProductTotal>;
  others: SearchResult[];
  /** A source that threw is not a source with nothing to say. */
  failed: boolean;
}

const NO_HITS: SearchHits = {
  items: [],
  totals: new Map(),
  others: [],
  failed: false,
};

/** The window the ranking chooses from: five is what fits the list, but a
 *  five-row window cut on the server's own order is exactly what hid the
 *  obvious name hits behind a pile of brand matches. */
const RANKING_WINDOW = 20;
const DISPLAY_LIMIT = 5;

async function searchAll(
  query: string,
  enabledModules: string[],
): Promise<SearchHits> {
  const trimmed = query.trim();
  if (trimmed.length < 2) return NO_HITS;

  let failed = false;
  const items = enabledModules.includes("inventory")
    ? itemsApi
        .search(trimmed, RANKING_WINDOW)
        .then((found) => topProducts(rankItemsByRelevance(found, trimmed)))
        .catch((): Item[] => {
          failed = true;
          return [];
        })
    : Promise.resolve<Item[]>([]);

  const providers = moduleRegistry.getSearchProviders(enabledModules);
  const others = Promise.all(
    providers.map((provider) =>
      provider(trimmed).catch((): SearchResult[] => {
        failed = true;
        return [];
      }),
    ),
  );

  const [foundItems, groups] = await Promise.all([items, others]);
  return {
    items: foundItems,
    totals: await totalsOfProducts(foundItems),
    others: groups.flat(),
    failed,
  };
}

/** The records of the best-ranked products: five products, not five records
 *  — a product held in several places must not use up the window by itself. */
function topProducts(ranked: Item[]): Item[] {
  const keep = new Set<string>();
  for (const item of ranked) {
    if (keep.size >= DISPLAY_LIMIT) break;
    keep.add(item.template_id ?? item.id);
  }
  return ranked.filter((item) => keep.has(item.template_id ?? item.id));
}

/** The backend's sum for every product the search found as several records,
 *  because the window holds only some of a product's records and a total
 *  built from them would understate the stock. A product whose sum cannot be
 *  fetched falls back to what the found records add up to. */
async function totalsOfProducts(
  items: Item[],
): Promise<ReadonlyMap<string, ProductTotal>> {
  const records = new Map<string, number>();
  for (const item of items) {
    if (item.template_id) {
      records.set(item.template_id, (records.get(item.template_id) ?? 0) + 1);
    }
  }
  const several = [...records].filter(([, n]) => n > 1).map(([id]) => id);
  const totals = new Map<string, ProductTotal>();
  await Promise.all(
    several.map((templateId) =>
      productTemplatesApi
        .getStock(templateId)
        .then((stock) =>
          totals.set(templateId, {
            quantity: stock.total_quantity,
            uom: stock.uom_symbol,
          }),
        )
        .catch(() => undefined),
    ),
  );
  return totals;
}

export function useCommandPaletteSearch(
  query: string,
  enabledModules: string[],
): { results: SearchResult[]; isLoading: boolean; failed: boolean } {
  const { t } = useTranslation();
  const { data = NO_HITS, isFetching } = useQuery({
    queryKey: queryKeys.commandPalette.search(query, enabledModules),
    queryFn: () => searchAll(query, enabledModules),
    enabled: query.trim().length >= 2,
    // A failed search is not an answer worth keeping: retyping the phrase
    // must ask again rather than replay the failure for 30 s.
    staleTime: (q) => (q.state.data?.failed ? 0 : 30_000),
  });

  const results = useMemo(
    () => [
      ...itemsToResults(data.items, t, query, data.totals),
      ...data.others,
    ],
    [data, t, query],
  );

  return { results, isLoading: isFetching, failed: data.failed };
}
