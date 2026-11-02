import {
  useEffect,
  useState,
  useCallback,
  useDeferredValue,
  useRef,
} from "react";
import { createPortal } from "react-dom";
import { useNavigate, useLocation } from "react-router-dom";
import { Command } from "cmdk";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import { Search, ArrowRight, Package, Clock, Loader2 } from "lucide-react";
import { useModules } from "@/contexts/ModulesContext";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { moduleRegistry } from "@/lib/moduleRegistry";
import { resolveModuleTarget } from "@/lib/moduleRegistry/resolveModuleTarget";
import { getRecentItems } from "@/lib/recentItems";
import { useAuthStore } from "@/store/authStore";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { useCommandPaletteSearch } from "@/lib/useCommandPaletteSearch";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";

interface CommandPaletteProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Relevance gate for navigation items (module switcher, recent items,
 * quick actions). cmdk's built-in fuzzy matcher is too loose — it returns
 * a "best" match even for completely unrelated queries (e.g. "milk" →
 * "Shopping lists"). We filter those sections ourselves and only render
 * what actually matches.
 *
 * Every word of the query has to be the start of a word of the value: a
 * scattered in-order subsequence matched "tuna" to "equipment tracking"
 * (t-u-n-a, letter by letter), and Enter then opened that module instead of
 * the product the reader had typed.
 */
function matchesQuery(value: string, query: string): boolean {
  const words = value.toLowerCase().split(/[^\p{L}\p{N}]+/u);
  return query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((part) => words.some((word) => word.startsWith(part)));
}

function SearchFailedNotice({
  failed,
  searching,
  query,
}: {
  failed: boolean;
  searching: boolean;
  query: string;
}) {
  const { t } = useTranslation();
  if (!failed || searching || query.length < 2) return null;
  return (
    <div
      role="alert"
      className="py-4 text-center text-sm text-red-600 dark:text-red-400"
    >
      {t(
        "commandPalette.searchFailed",
        "The search failed, so this list may be incomplete. Try again.",
      )}
    </div>
  );
}

interface QuickAction {
  value: string;
  path: string;
  label: string;
  Icon: typeof Search;
}

function quickActionsFor(
  enabledModules: string[],
  query: string,
  t: TFunction,
): QuickAction[] {
  const actions: (QuickAction & { module: string })[] = [
    {
      module: "inventory",
      value: "add-item add new item inventory",
      path: "/inventory/items/add",
      label: t("commandPalette.addItem", "Add new item"),
      Icon: Package,
    },
    {
      module: "inventory",
      value: "scan barcode qr inventory",
      path: "/inventory/scan",
      label: t("commandPalette.scanBarcode", "Scan barcode"),
      Icon: Search,
    },
    {
      module: "warehouse",
      value: "scan document barcode qr warehouse",
      path: "/warehouse/scan",
      label: t("commandPalette.scanDocument", "Scan document"),
      Icon: Search,
    },
  ];
  return actions.filter(
    (a) => enabledModules.includes(a.module) && matchesQuery(a.value, query),
  );
}

function QuickActionsGroup({
  actions,
  onSelect,
}: {
  actions: QuickAction[];
  onSelect: (path: string) => void;
}) {
  const { t } = useTranslation("common");
  if (actions.length === 0) return null;
  return (
    <Command.Group
      heading={t("commandPalette.quickActions", "Quick actions")}
      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-on-muted mt-1"
    >
      {actions.map(({ value, path, label, Icon }) => (
        <Command.Item
          key={path}
          value={value}
          onSelect={() => onSelect(path)}
          className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-on cursor-pointer aria-selected:bg-primary-50 aria-selected:text-primary-700 transition-colors"
        >
          <Icon size={15} className="text-on-muted shrink-0" />
          <span>{label}</span>
        </Command.Item>
      ))}
    </Command.Group>
  );
}

export function CommandPalette({ open, onClose }: CommandPaletteProps) {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);
  const navigate = useNavigate();
  const location = useLocation();
  const { enabledModules: allEnabledModules, hiddenModules } = useModules();
  // Focus mode hides a module's screens without turning the module off, and
  // the palette must not be the side door back into them: every source below
  // works from the modules the reader can see.
  const enabledModules = allEnabledModules.filter(
    (name) => !hiddenModules.includes(name),
  );
  const moduleLabels = useModuleLabels();
  const { user } = useAuthStore();
  const [searchValue, setSearchValue] = useState("");
  const deferredSearch = useDeferredValue(searchValue);
  const {
    results: searchResults,
    isLoading: isSearching,
    failed: searchFailed,
  } = useCommandPaletteSearch(deferredSearch, enabledModules);
  const inputRef = useRef<HTMLInputElement | null>(null);

  // The highlighted option. cmdk picks the first one when the text changes,
  // and at that moment only the navigation entries exist — the hits arrive
  // from the server a moment later, rendered above them, and the highlight
  // stays on whatever was first before. Enter then opened a module instead of
  // the product the reader had just typed. So the highlight moves to the
  // first hit when the hits arrive.
  const [highlighted, setHighlighted] = useState("");
  const firstHit =
    !isSearching && searchResults.length > 0 ? searchResults[0] : undefined;
  const firstHitValue = firstHit && `search-${firstHit.id}-${firstHit.title}`;
  useEffect(() => {
    if (firstHitValue) setHighlighted(firstHitValue);
  }, [firstHitValue, isSearching, deferredSearch]);

  // Reset search on open + autofocus the input
  useEffect(() => {
    if (open) {
      setSearchValue("");
      // Defer to next tick so the conditionally-mounted input is in the DOM
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // Close on Escape — global listener so cmdk can't swallow the event
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      }
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [open, onClose]);

  // Close on route change — only react to pathname changes, not onClose identity
  const previousPathRef = useRef(location.pathname);
  useEffect(() => {
    if (previousPathRef.current !== location.pathname) {
      previousPathRef.current = location.pathname;
      onClose();
    }
  }, [location.pathname, onClose]);

  // Jumping somewhere from the palette walks the same gate as clicking a
  // module tab: a dirty form asks, and one address gives one answer no
  // matter which control carried the request.
  const { guardNavigate, confirmDialogProps } = useNavLeaveGuard();

  const handleSelect = useCallback(
    (path: string) => {
      // The question, if there is one, hands the focus back to whatever held
      // it when it opened. A clicked option leaves it on the list, which is
      // no place to type from; the input is.
      inputRef.current?.focus();
      guardNavigate(() => {
        navigate(path);
        onClose();
      });
    },
    [guardNavigate, navigate, onClose],
  );

  const modulesWithLauncher =
    moduleRegistry.getModulesWithLauncher(enabledModules);

  /**
   * The module a result came from, named the way the launcher names it.
   *
   * A result used to be tagged with the technical name run through
   * `capitalize` — "Inventory" beside a launcher tile and a navigation entry
   * that both read "Inwentarz". The launcher's own label comes first because
   * that is the string the reader has already seen; the module catalogue
   * name covers a module with no tile.
   */
  const moduleName = (technicalName: string): string => {
    const tile = modulesWithLauncher.find(
      (mod) => mod.name === technicalName,
    )?.launcher;
    if (tile) return tDyn(tile.displayName);
    return moduleLabels({
      name: technicalName,
      display_name: technicalName,
      description: "",
    }).name;
  };

  // The second argument has read "default" since it was written: the user
  // record has never carried an organization id, so the old conditional was
  // the fallback branch and nothing else.
  const recentItems = user?.id
    ? getRecentItems(String(user.id), "default")
    : [];

  const query = deferredSearch.trim();

  const visibleModules = modulesWithLauncher.filter((mod) => {
    const cfg = mod.launcher!;
    return matchesQuery(`${mod.name} ${tDyn(cfg.displayName)}`, query);
  });
  const visibleRecent = recentItems.filter(
    (item) =>
      !hiddenModules.includes(item.module) &&
      matchesQuery(`${item.title} ${item.module}`, query),
  );
  const quickActions = quickActionsFor(enabledModules, query, t);

  const showEmpty =
    query.length >= 2 &&
    !isSearching &&
    !searchFailed &&
    searchResults.length === 0 &&
    visibleModules.length === 0 &&
    visibleRecent.length === 0 &&
    quickActions.length === 0;

  // The palette opens from anywhere, over whatever is on screen — a sheet on
  // the confirm tier, a fullscreen wizard. On the modal tier it opened under
  // those: invisible and pointer-dead, while Enter still navigated the route
  // behind the form. So it takes the highest sheet tier and renders at the
  // end of `body`, where an equal tier paints in that order and the palette,
  // opened last, lands on top. Its own question about a dirty form stands on
  // the same tier, or it would open under the palette that raised it.
  return (
    <>
      {open &&
        createPortal(
          <div
            role="dialog"
            aria-label={t("commandPalette.title", "Command palette")}
            aria-modal="true"
            className="fixed inset-0 z-[var(--z-fullscreen)]"
          >
            <div
              className="absolute inset-0 bg-black/40 backdrop-blur-sm"
              onClick={onClose}
              aria-hidden="true"
            />

            <div className="fixed inset-x-4 top-[10vh] mx-auto max-w-xl">
              <Command
                shouldFilter={false}
                value={highlighted}
                onValueChange={setHighlighted}
                className="overflow-hidden rounded-2xl border border-border bg-surface-card shadow-2xl"
                onKeyDown={(e) => {
                  if (e.key === "Escape") onClose();
                }}
              >
                <div className="flex items-center gap-3 px-4 py-3 border-b border-border">
                  <Search size={18} className="text-on-muted shrink-0" />
                  <Command.Input
                    ref={inputRef}
                    value={searchValue}
                    onValueChange={setSearchValue}
                    placeholder={t(
                      "commandPalette.placeholder",
                      "Search or jump to...",
                    )}
                    className="flex-1 bg-transparent text-sm text-on placeholder:text-on-muted outline-none"
                    aria-label={t(
                      "commandPalette.placeholder",
                      "Search or jump to...",
                    )}
                  />
                  <kbd className="hidden sm:inline-flex px-1.5 py-0.5 rounded text-[10px] font-mono text-on-secondary border border-border bg-surface-raised">
                    ESC
                  </kbd>
                </div>

                <Command.List
                  className="max-h-[60vh] overflow-y-auto p-2"
                  aria-live="polite"
                >
                  <SearchFailedNotice
                    failed={searchFailed}
                    searching={isSearching}
                    query={query}
                  />
                  {showEmpty && (
                    <Command.Empty className="py-8 text-center text-sm text-on-muted">
                      {t("commandPalette.noResults", "No results")}
                    </Command.Empty>
                  )}

                  {/* API search results */}
                  {isSearching && deferredSearch.trim().length >= 2 && (
                    <div className="flex items-center justify-center py-4 gap-2 text-sm text-on-muted">
                      <Loader2 size={14} className="animate-spin" />
                      {t("commandPalette.searching", "Searching...")}
                    </div>
                  )}
                  {!isSearching && searchResults.length > 0 && (
                    <Command.Group
                      heading={t("commandPalette.results", "Results")}
                      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-on-muted"
                    >
                      {searchResults.map((result) => (
                        <Command.Item
                          key={result.id}
                          value={`search-${result.id}-${result.title}`}
                          onSelect={() => handleSelect(result.path)}
                          className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-on cursor-pointer aria-selected:bg-primary-50 aria-selected:text-primary-700 data-[selected=true]:bg-primary-50 data-[selected=true]:text-primary-700 transition-colors"
                        >
                          <Search
                            size={15}
                            className="text-on-muted shrink-0"
                          />
                          <span className="flex-1 truncate">
                            {result.title}
                          </span>
                          {result.subtitle && (
                            <span className="text-[10px] text-on-muted truncate max-w-[220px]">
                              {result.subtitle}
                            </span>
                          )}
                          <span className="text-[10px] text-on-muted opacity-60">
                            {moduleName(result.module)}
                          </span>
                        </Command.Item>
                      ))}
                    </Command.Group>
                  )}

                  {/* Module switching */}
                  {visibleModules.length > 0 && (
                    <Command.Group
                      heading={t("commandPalette.switchTo", "Switch to")}
                      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-on-muted"
                    >
                      {visibleModules.map((mod) => {
                        const cfg = mod.launcher!;
                        // Same target the launcher tile and the ModuleSwitcher
                        // compute — a module that routes nothing (Settings)
                        // still has a launcher.linkTo to land on.
                        const dest = resolveModuleTarget(mod);
                        const Icon = cfg.icon;
                        return (
                          <Command.Item
                            key={mod.name}
                            value={`module-${mod.name}-${tDyn(cfg.displayName)}`}
                            onSelect={() => handleSelect(dest)}
                            className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-on cursor-pointer aria-selected:bg-primary-50 aria-selected:text-primary-700 data-[selected=true]:bg-primary-50 data-[selected=true]:text-primary-700 transition-colors"
                          >
                            <div
                              className={`w-7 h-7 rounded-lg flex items-center justify-center ${cfg.color ?? "bg-surface-raised"}`}
                            >
                              <Icon size={15} className="text-white" />
                            </div>
                            <span className="flex-1">
                              {tDyn(cfg.displayName)}
                            </span>
                            <ArrowRight size={14} className="text-on-muted" />
                          </Command.Item>
                        );
                      })}
                    </Command.Group>
                  )}

                  {/* Recent items */}
                  {visibleRecent.length > 0 && (
                    <Command.Group
                      heading={t(
                        "launcher:launcher.recentItems",
                        "Recently visited",
                      )}
                      className="[&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-1 [&_[cmdk-group-heading]]:text-[10px] [&_[cmdk-group-heading]]:font-medium [&_[cmdk-group-heading]]:uppercase [&_[cmdk-group-heading]]:tracking-widest [&_[cmdk-group-heading]]:text-on-muted mt-1"
                    >
                      {visibleRecent.slice(0, 5).map((item) => (
                        <Command.Item
                          key={item.id}
                          value={`recent-${item.id}-${item.title}`}
                          onSelect={() => handleSelect(item.path)}
                          className="flex items-center gap-3 px-3 py-2 rounded-xl text-sm text-on cursor-pointer aria-selected:bg-primary-50 aria-selected:text-primary-700 transition-colors"
                        >
                          <Clock size={15} className="text-on-muted shrink-0" />
                          <span className="flex-1 truncate">{item.title}</span>
                          <span className="text-[10px] text-on-muted">
                            {moduleName(item.module)}
                          </span>
                        </Command.Item>
                      ))}
                    </Command.Group>
                  )}

                  <QuickActionsGroup
                    actions={quickActions}
                    onSelect={handleSelect}
                  />
                </Command.List>
              </Command>
            </div>
          </div>,
          document.body,
        )}

      <ConfirmDialog {...confirmDialogProps} zIndex="fullscreen" />
    </>
  );
}
