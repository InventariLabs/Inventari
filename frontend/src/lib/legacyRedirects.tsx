import {
  Navigate,
  useLocation,
  useParams,
  type Params,
} from "react-router-dom";

/**
 * An address the app used to answer and now forwards, kept so a bookmark, a
 * printed label or a mail link still lands.
 *
 * It is a row of data, not a `<Route>` per address: retiring one is deleting a
 * line, and adding one touches no JSX. `from` is a route path relative to the
 * parent it is mounted under. `to` is the new address; a function receives the
 * route's params (`:id`, and `*` for a splat). `keepSearch` carries the query
 * string and hash across, for an address that is a filter or a deep link.
 */
export interface LegacyRedirect {
  from: string;
  to: string | ((params: Params) => string);
  keepSearch?: boolean;
}

/** Top-level addresses from before the inventory tree and settings moved. */
export const LEGACY_REDIRECTS: LegacyRedirect[] = [
  // Webhooks lived on a flat route as well as in settings. The flat one had no
  // PageHeaderContext above it, so its header — carrying the only "Add
  // webhook" button once the list was non-empty — went nowhere. One screen,
  // one address: the settings one, where the sidebar has always pointed.
  { from: "webhooks", to: "/settings/webhooks" },
  // Inventory paths.
  { from: "items", to: "/inventory/items", keepSearch: true },
  { from: "items/add", to: "/inventory/items/add" },
  {
    from: "items/:id",
    to: ({ id }) =>
      id ? `/inventory/items/${encodeURIComponent(id)}` : "/inventory/items",
  },
  { from: "categories", to: "/inventory/categories" },
  { from: "scan", to: "/inventory/scan", keepSearch: true },
  // The address a printed QR opens (see backend scan_links): one letter,
  // because every byte of it is a module on the label. A catch-all rather than
  // `:code`, so a document number keeps its slashes (`/s/IN/2026/0001`).
  {
    from: "s/*",
    to: (params) => {
      const code = params["*"] ?? "";
      return code
        ? `/inventory/scan?code=${encodeURIComponent(code)}`
        : "/inventory/scan";
    },
  },
  // Storages now live under /inventory.
  { from: "storages", to: "/inventory/locations" },
  { from: "storages/:id", to: ({ id }) => `/inventory/locations/${id ?? ""}` },
  { from: "labels", to: "/inventory/labels" },
  // Stats now live under /inventory/stats.
  { from: "stats", to: "/inventory/stats" },
  { from: "stats/inventory", to: "/inventory/stats" },
  { from: "stats/analytics", to: "/inventory/stats/analytics" },
  // Stock takes now live under /inventory/stock-takes.
  { from: "stock-takes", to: "/inventory/stock-takes" },
  {
    from: "stock-takes/:id/counting",
    to: ({ id }) => `/inventory/stock-takes/${id ?? ""}/counting`,
  },
];

/** Settings addresses that were renamed or folded into another screen. */
export const LEGACY_SETTINGS_REDIRECTS: LegacyRedirect[] = [
  // "My modules" is one screen for the module set and the single-module
  // toggles; the two addresses that used to hold one half each survive so a
  // bookmark still lands on the whole.
  { from: "workspace", to: "/settings/my-modules" },
  { from: "focus", to: "/settings/my-modules" },
  // The whole content of this page was a sentence and a button pointing at
  // /apps — which is also where the sidebar has always linked.
  { from: "modules", to: "/apps" },
  // "Developer" held the mail server and the AI connections under a name that
  // described neither.
  { from: "developer", to: "/settings/ai" },
];

/** Forwards to a legacy address's replacement, replacing the history entry. */
export function LegacyRedirectTo({
  to,
  keepSearch,
}: Pick<LegacyRedirect, "to" | "keepSearch">) {
  const params = useParams();
  const { search, hash } = useLocation();
  const target = typeof to === "function" ? to(params) : to;
  return (
    <Navigate to={keepSearch ? `${target}${search}${hash}` : target} replace />
  );
}
