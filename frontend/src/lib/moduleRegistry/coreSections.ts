import {
  Archive,
  BarChart3,
  Camera,
  ClipboardCheck,
  QrCode,
} from "lucide-react";

import type {
  AdoptableCoreSection,
  CoreNavSection,
  ModuleNavItem,
} from "./moduleInterfaces";

/**
 * Where each adoptable core section lives in the route tree. The shell reads
 * this to recognise a path as a core section a standalone focus module may
 * have adopted — the routes themselves stay mounted under the owning module
 * (`/inventory/*`, printing's flat `/labels/scan/:code`); only the shell
 * chrome (banner, tab bar, theme) follows the adoption.
 */
export const CORE_SECTION_PATH_PREFIXES: Record<
  AdoptableCoreSection,
  string[]
> = {
  labels: ["/inventory/labels"],
  // `/labels/scan/:code` is printing's flat route — the one entry a physical
  // QR sticker has, so adopting the scanner means adopting both.
  scan: ["/inventory/scan", "/labels/scan"],
  stats: ["/inventory/stats"],
  stock_takes: ["/inventory/stock-takes"],
  archive: ["/inventory/items/archived", "/inventory/locations/archived"],
};

/**
 * The nav entry an adopting module gets for each core section. Mirrors the
 * inventory module's own entries — same icons, same i18n keys, same orders —
 * so an adopted section looks and reads exactly as it did under inventory;
 * only the banner above it changes. The single source of truth for whether an
 * entry appears stays `standalone.coreSections` — modules must NOT duplicate
 * these as static `moduleNav` items (the shell dedupes by path if one ever
 * does).
 */
export const CORE_SECTION_NAV: Record<AdoptableCoreSection, ModuleNavItem> = {
  labels: {
    path: "/inventory/labels",
    icon: QrCode,
    labelKey: "inventory:nav.labels",
    titleKey: "labels:title",
    subtitleKey: "labels:subtitle",
    order: 40,
  },
  scan: {
    path: "/inventory/scan",
    icon: Camera,
    labelKey: "inventory:nav.scan",
    order: 60,
    mobileBar: true,
    showOnMobile: true,
  },
  stats: {
    path: "/inventory/stats",
    icon: BarChart3,
    labelKey: "stats:title",
    titleKey: "stats:title",
    subtitleKey: "stats:subtitle",
    order: 45,
    requiresModules: ["stats"],
  },
  stock_takes: {
    path: "/inventory/stock-takes",
    icon: ClipboardCheck,
    labelKey: "navigation.stockTakes",
    titleKey: "stock_takes:title",
    subtitleKey: "stock_takes:subtitle",
    order: 35,
  },
  // The archive has no inventory nav entry of its own today; the entry points
  // at the items archive, the storages archive sits next to it on that screen.
  archive: {
    path: "/inventory/items/archived",
    icon: Archive,
    labelKey: "common:archiveTabs.archived",
    order: 55,
  },
};

// Flattened once, longest prefix first, so a more specific path always wins
// over a shallower one that happens to prefix it.
const SECTION_PREFIXES_SORTED: Array<{
  prefix: string;
  section: AdoptableCoreSection;
}> = (
  Object.entries(CORE_SECTION_PATH_PREFIXES) as Array<
    [AdoptableCoreSection, string[]]
  >
)
  .flatMap(([section, prefixes]) =>
    prefixes.map((prefix) => ({ prefix, section })),
  )
  .sort((a, b) => b.prefix.length - a.prefix.length);

/**
 * The adoptable core section `pathname` belongs to, or null when the path is
 * not part of any adoptable section (the module's own screens, the plain
 * inventory lists). Prefix match, most specific first.
 */
export function getCoreSectionForPath(
  pathname: string,
): AdoptableCoreSection | null {
  for (const { prefix, section } of SECTION_PREFIXES_SORTED) {
    if (pathname.startsWith(prefix)) return section;
  }
  return null;
}

/**
 * Where each kept core nav section lives. `entry` is the path of the inventory
 * nav item the shell borrows (the inventory module stays the single source of
 * its icon, label and `requiresModules`); `prefixes` are the routes that render
 * under a focus module's banner when it keeps the section.
 */
export const CORE_NAV_SECTION_PATHS: Record<
  CoreNavSection,
  { entry: string; prefixes: string[] }
> = {
  items: { entry: "/inventory/items", prefixes: ["/inventory/items"] },
  storages: {
    entry: "/inventory/locations",
    prefixes: ["/inventory/locations"],
  },
  categories: {
    entry: "/inventory/categories",
    prefixes: ["/inventory/categories"],
  },
  stock: {
    entry: "/inventory/stock",
    prefixes: ["/inventory/stock", "/inventory/lots"],
  },
  moves: { entry: "/inventory/moves", prefixes: ["/inventory/moves"] },
};

// Segment-aware: `/inventory/stock` must not claim `/inventory/stock-takes`.
function hasPathPrefix(pathname: string, prefix: string): boolean {
  if (!pathname.startsWith(prefix)) return false;
  const next = pathname.charAt(prefix.length);
  return next === "" || next === "/" || next === "?" || next === "#";
}

/**
 * The kept core nav section `pathname` belongs to, or null. Callers resolve
 * adoptable sections first (`getCoreSectionForPath`): the archive paths hang
 * under the items and storages prefixes and belong to the archive.
 */
export function getCoreNavSectionForPath(
  pathname: string,
): CoreNavSection | null {
  for (const [section, { prefixes }] of Object.entries(
    CORE_NAV_SECTION_PATHS,
  ) as Array<[CoreNavSection, { prefixes: string[] }]>) {
    if (prefixes.some((prefix) => hasPathPrefix(pathname, prefix))) {
      return section;
    }
  }
  return null;
}
