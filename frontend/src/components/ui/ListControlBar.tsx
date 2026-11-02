import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { LayoutGrid, List, Search, X, SlidersHorizontal } from "lucide-react";
import { cn } from "@/lib/utils";
import { Input } from "@/components/ui/Input";
import { ScrollRow } from "@/components/ui/ScrollRow";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/Tabs";

export interface ListControlBarSearchProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}

export interface ListControlBarTabOption {
  value: string;
  label: string;
  icon?: ReactNode;
}

export interface ListControlBarPrimaryTabsProps {
  value: string;
  onChange: (value: string) => void;
  options: ListControlBarTabOption[];
  /**
   * What the row filters by ("Type", "Status", …). Two unlabelled rows that
   * both start with "All" read as one filter in two states — name them.
   */
  label?: string;
}

export interface ListControlBarSecondaryFilter {
  key: string;
  label: string;
  active: boolean;
  onToggle: () => void;
}

export interface ListControlBarViewToggleProps {
  mode: "grid" | "list";
  onChange: (mode: "grid" | "list") => void;
}

export interface ListControlBarFilterButtonProps {
  activeCount: number;
  onClick: () => void;
}

export interface ListControlBarProps {
  search?: ListControlBarSearchProps;
  primaryTabs?: ListControlBarPrimaryTabsProps;
  secondaryFilters?: ListControlBarSecondaryFilter[];
  /** What the chip row filters by — see `primaryTabs.label`. */
  secondaryFiltersLabel?: string;
  viewToggle?: ListControlBarViewToggleProps;
  filterButton?: ListControlBarFilterButtonProps;
  resultCount?: number;
  resultCountLabel?: string;
  /** The list stopped counting at `resultCount`: it says "more than". */
  resultCountCapped?: boolean;
  /**
   * Action(s) rendered at the end of the first row — "Add", "Import",
   * "Export" and friends.
   *
   * A single node rather than a typed action list: callers already build
   * their own buttons, and one of them (`NutritionToolbar`) needs a
   * `<label>` wrapping a hidden file input, which no button-shaped API
   * would express. Pass a fragment for several actions.
   */
  primaryAction?: ReactNode;
  className?: string;
}

/**
 * Small caption naming what a filter row filters by. Exported because a module
 * that builds its own phone-only filter row still has to label it the same way
 * — two rows that both open with "All" read as one filter otherwise.
 */
export function RowLabel({ children }: { children: ReactNode }) {
  return (
    <span className="shrink-0 text-xs font-medium text-on-muted">
      {children}
    </span>
  );
}

function SearchField({ search }: { search: ListControlBarSearchProps }) {
  const { t } = useTranslation("common");
  return (
    <Input
      // `flex-1` alone has a 0% basis: in an overfull row the field was left
      // with no width at all and collapsed to a square around its icon. The
      // field keeps a floor (~14 rem on desktop) and the row stacks below
      // `sm:`, where full width beats any floor.
      wrapperClassName="min-w-0 flex-1 sm:min-w-56 sm:basis-56"
      data-testid="list-search-input"
      // The bar has no room for a visible label, and the placeholder vanishes
      // on the first keystroke — so name the field for assistive technology
      // explicitly.
      aria-label={search.placeholder ?? t("common:actions.search")}
      value={search.value}
      onChange={(e) => search.onChange(e.target.value)}
      placeholder={search.placeholder}
      leftIcon={<Search size={15} />}
      rightIcon={
        search.value ? (
          <button
            type="button"
            onClick={() => search.onChange("")}
            // A bare 15px icon before: the target grows to 44px on a phone
            // without the icon growing with it.
            className="flex h-11 w-11 md:h-auto md:w-auto items-center justify-center text-on-muted hover:text-on transition-colors"
            aria-label={t("common:actions.clearSearch")}
          >
            <X size={15} />
          </button>
        ) : undefined
      }
    />
  );
}

function FilterButton({ button }: { button: ListControlBarFilterButtonProps }) {
  const { t } = useTranslation("common");
  const active = button.activeCount > 0;
  return (
    <button
      type="button"
      onClick={button.onClick}
      className={cn(
        "flex items-center gap-1.5 h-11 md:h-10 px-3 rounded-lg border text-sm font-medium transition-colors whitespace-nowrap",
        // Active state: brand tint + brand border carry the signal, the label
        // stays on the neutral text token. Brand-coloured text on a brand tint
        // is what broke in dark mode (1.55:1) and cannot be fixed centrally,
        // because product profiles repaint the `primary-*` ramp with their own
        // hues.
        active
          ? "border-primary-500 bg-primary-50 text-on font-semibold"
          : "border-border bg-surface-card text-on-secondary hover:text-on",
      )}
    >
      <SlidersHorizontal size={15} />
      <span>{t("common:actions.filter")}</span>
      {active && (
        <span className="ml-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-primary-700 dark:bg-primary-800 text-[10px] font-medium text-white">
          {button.activeCount}
        </span>
      )}
    </button>
  );
}

function ViewToggle({ toggle }: { toggle: ListControlBarViewToggleProps }) {
  const { t } = useTranslation("common");
  const modes = [
    {
      mode: "grid" as const,
      Icon: LayoutGrid,
      label: t("common:actions.gridView", "Grid view"),
    },
    {
      mode: "list" as const,
      Icon: List,
      label: t("common:actions.listView", "List view"),
    },
  ];
  return (
    // No border: the inset background already separates the pair from the bar,
    // and every border here competes with the list below it.
    <div className="flex bg-surface-inset rounded-xl p-1">
      {modes.map(({ mode, Icon, label }) => (
        <button
          key={mode}
          type="button"
          onClick={() => toggle.onChange(mode)}
          aria-label={label}
          className={cn(
            // 44x44 below `md`: the pair sits in a thumb's reach on a phone.
            "inline-flex items-center justify-center p-1.5 rounded-lg transition-colors min-h-11 min-w-11 md:min-h-0 md:min-w-0",
            toggle.mode === mode
              ? "bg-surface-card shadow-sm text-on"
              : "text-on-muted hover:text-on",
          )}
        >
          <Icon size={16} />
        </button>
      ))}
    </div>
  );
}

/**
 * How many rows the filters left. It sits in the first row on a bar with no
 * search field and in the second one otherwise, so it is a component rather
 * than a span written twice.
 */
function ResultCount({
  count,
  label,
  capped = false,
  className,
}: {
  count: number;
  label?: string;
  capped?: boolean;
  className?: string;
}) {
  const { t } = useTranslation("common");
  const number = capped
    ? t("common:pagination.moreThan", { count })
    : String(count);
  return (
    <span
      className={cn(
        "shrink-0 text-xs font-medium text-on-secondary",
        className,
      )}
    >
      {label
        ? `${number} ${label}`
        : capped
          ? number
          : t("common:results", { count })}
    </span>
  );
}

/**
 * The chip row and the count that follows it.
 *
 * The chips scroll instead of wrapping. Wrapping made the row's
 * height a function of how many modules are installed: a fourth chip pushed
 * the list down by a whole band, and the count — competing for the same width
 * — landed on a band of its own. The row is one band now, whatever the chip
 * count, and the count sits outside the track so it never widens it.
 */
function SecondaryRow({
  filters,
  filtersLabel,
  count,
  countLabel,
  countCapped,
}: {
  filters?: ListControlBarSecondaryFilter[];
  filtersLabel?: string;
  count?: number;
  countLabel?: string;
  countCapped?: boolean;
}) {
  return (
    // `gap-3`, not `gap-2`: the track's fade needs room to read as "there is
    // more to scroll" rather than as a chip glued to the count.
    // Below `sm:` the count takes a band of its own above the chips. The chips
    // stay one scrolling band on a phone as well: wrapped, seven 44 px chips
    // took three rows and pushed the first record of the list below the fold
    // of a 360x800 screen, so the list opened on controls only.
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-3">
      <ScrollRow
        className="flex flex-1 min-w-0 items-center gap-2"
        role={filtersLabel ? "group" : undefined}
        aria-label={filtersLabel}
      >
        {filtersLabel && filters?.length ? (
          <RowLabel>{filtersLabel}</RowLabel>
        ) : null}

        {filters?.map((f) => (
          <FilterChip key={f.key} filter={f} />
        ))}
      </ScrollRow>

      {count !== undefined && (
        <ResultCount
          count={count}
          label={countLabel}
          capped={countCapped}
          className="order-first sm:order-none"
        />
      )}
    </div>
  );
}

export function FilterChip({
  filter,
}: {
  filter: ListControlBarSecondaryFilter;
}) {
  return (
    <button
      type="button"
      data-testid={`filter-${filter.key}`}
      // A toggle: the fill says on or off to the eye, this says it to a
      // screen reader, which otherwise heard the same chip either way.
      aria-pressed={filter.active}
      onClick={filter.onToggle}
      className={cn(
        // Touch targets: 44 px below `md:`, desktop keeps the compact chip.
        // Measured at 26 px before. `shrink-0` keeps a long label from being
        // squashed under its own text when the row runs out of width.
        "inline-flex shrink-0 items-center justify-center h-11 min-w-11 md:h-7 md:min-w-0 px-3 text-xs",
        "rounded-full transition-colors whitespace-nowrap",
        // No outline on the chips: a filter bar of six outlined pills above an
        // outlined list is where the screen's border count runs away. The state
        // is a fill, not a frame.
        filter.active
          ? "bg-primary-50 text-on font-semibold ring-1 ring-primary-500"
          : "bg-surface-raised text-on-secondary hover:text-on",
      )}
    >
      {filter.label}
    </button>
  );
}

export function ListControlBar({
  search,
  primaryTabs,
  secondaryFilters,
  secondaryFiltersLabel,
  viewToggle,
  filterButton,
  resultCount,
  resultCountLabel,
  resultCountCapped,
  primaryAction,
  className,
}: ListControlBarProps) {
  const hasRow1 = !!(
    search ||
    primaryTabs ||
    viewToggle ||
    filterButton ||
    primaryAction
  );
  // Without a search field the first row holds only the tabs, so it ends at
  // whatever they measure and the count sits alone on a row below — a strip
  // hugging the left and a number hugging the right, with a band of nothing
  // between them. The count moves up to close the row.
  //
  // Only when the second row would otherwise be empty: a search field already
  // takes the slack in row 1, and chips belong beside their count.
  const countInRow1 =
    resultCount !== undefined && !search && !secondaryFilters?.length;
  const hasRow2 = !!(
    (secondaryFilters && secondaryFilters.length > 0) ||
    (resultCount !== undefined && !countInRow1)
  );

  if (!hasRow1 && !hasRow2) return null;

  return (
    <div className={cn("space-y-2", className)}>
      {hasRow1 && (
        <div className="flex flex-col sm:flex-row sm:items-center gap-2">
          {search && <SearchField search={search} />}

          {/* The tabs' own track may be narrower than its content — that is
              what makes an overlong tab list scroll instead of widening the
              page (`min-w-0`, no `shrink-0`, no `flex-wrap`: wrapping was
              what broke the scroll in the first place). The primary
              action stands outside the track, so a scroller can never carry
              it out of reach — and everything here but the track wraps, so
              an action row wider than a phone falls to a band of its own
              and folds its buttons there instead of being clipped
              unreachable by the root's overflow-x-hidden. */}
          <div className="flex flex-wrap items-center gap-2 min-w-0">
            <ScrollRow className="flex items-center gap-2 min-w-0">
              {filterButton && <FilterButton button={filterButton} />}

              {primaryTabs?.label && <RowLabel>{primaryTabs.label}</RowLabel>}

              {primaryTabs && (
                <Tabs
                  value={primaryTabs.value}
                  onValueChange={primaryTabs.onChange}
                  defaultValue={primaryTabs.value}
                  panels={false}
                >
                  <TabsList aria-label={primaryTabs.label}>
                    {primaryTabs.options.map((opt) => (
                      <TabsTrigger
                        key={opt.value}
                        value={opt.value}
                        icon={opt.icon}
                        size="sm"
                        className="flex-none"
                      >
                        {opt.label}
                      </TabsTrigger>
                    ))}
                  </TabsList>
                </Tabs>
              )}
            </ScrollRow>

            {/* Outside the scroller: behind four tabs on a phone it started
                past the screen's edge and was clipped by the strip. Here it
                wraps to a line of its own instead. */}
            {viewToggle && <ViewToggle toggle={viewToggle} />}

            {primaryAction && (
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                {primaryAction}
              </div>
            )}
          </div>

          {countInRow1 && (
            <ResultCount
              count={resultCount}
              label={resultCountLabel}
              capped={resultCountCapped}
              className="sm:ml-auto"
            />
          )}
        </div>
      )}

      {hasRow2 && (
        <SecondaryRow
          filters={secondaryFilters}
          filtersLabel={secondaryFiltersLabel}
          count={countInRow1 ? undefined : resultCount}
          countLabel={resultCountLabel}
          countCapped={resultCountCapped}
        />
      )}
    </div>
  );
}
