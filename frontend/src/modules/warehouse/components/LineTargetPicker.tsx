import { useState } from "react";
import { useTranslation } from "react-i18next";
import { SearchableCombobox } from "@/components/ui/SearchableCombobox";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { useLocationsById } from "@/module-sdk";
import {
  locationOption,
  useLocationPicker,
  type LocationOption,
} from "@/module-sdk";
import type { LineChoiceMark } from "@/modules/warehouse/locationChoices";
import type {
  DocumentLine,
  WarehouseDocument,
} from "@/modules/warehouse/types";

/** What the marker beside a line's own shelf says, in each language. */
const MARK_LABEL_KEYS: Record<LineChoiceMark, string> = {
  current: "detail.lineTargetCurrent",
  planned: "detail.lineTargetPlanned",
};

/** Documents whose lines land goods somewhere: receipts. */
const RECEIPT_TYPES: string[] = ["IN", "INTERNAL_IN"];

/** Statuses in which a line's shelf can still be named. */
const OPEN_STATUSES: string[] = ["DRAFT", "CONFIRMED"];

/**
 * The picker that says "this line goes to A-13".
 *
 * Empty means the line follows the live plan — rule, document, record —
 * and the sentence next to it spells that plan out. Choosing a shelf saves
 * the line's own target, and the plan recomputes around the choice. The
 * select is deliberately cleared-value-by-default: freezing every line's
 * plan at pick time would rebuild exactly the staleness the preview exists
 * to prevent.
 */
export function LineTargetPicker({
  document,
  line,
  disabled,
  onChange,
}: {
  document: Pick<WarehouseDocument, "type" | "status">;
  line: DocumentLine;
  disabled?: boolean;
  onChange: (lineId: string, target: string | null) => void;
}) {
  const canPick =
    RECEIPT_TYPES.includes(document.type) &&
    OPEN_STATUSES.includes(document.status) &&
    !line.executed_location_id;
  if (!canPick) return null;

  return (
    <ShelfSelect
      value={line.target_location_id ?? null}
      plannedId={line.planned_location_id}
      disabled={disabled}
      onChange={(target) => onChange(line.id, target)}
      wrapperClassName="mt-1 max-w-72"
    />
  );
}

/**
 * The control itself, with no opinion on when a line may be re-aimed.
 *
 * Two screens name a shelf and they are pickable for different reasons: the
 * office page asks about the document (a receipt, still open), the floor
 * screen asks about the row in the worker's hand (still pending). Putting
 * one guard here would have meant teaching it about both, so the guard
 * stays with each caller and only the control is shared — the empty option
 * included, because "follow the plan" has to mean the same thing in both
 * places or the sentence beside it stops being true on one of them.
 *
 * The shelves are searched on the server as the reader types: a warehouse of
 * two thousand shelves has no list a person could open. The line's own shelf
 * and the one its plan names lead the list while nothing is typed, marked,
 * and are named even when they are not on the first page.
 */
export function ShelfSelect({
  value,
  plannedId,
  disabled,
  onChange,
  wrapperClassName,
  placeholder,
}: {
  value: string | null;
  /** The shelf this line's plan sends its goods to, so it can sit at the
   *  top of the list beside the shelf the line already names. */
  plannedId?: string | null;
  disabled?: boolean;
  onChange: (target: string | null) => void;
  wrapperClassName?: string;
  /** Replaces "follow the plan" with a prompt that cannot be picked: the
   *  phone's card names its shelf itself, and the plan's jargon is no
   *  choice for the person holding the box. */
  placeholder?: string;
}) {
  const { t } = useTranslation("warehouse");
  const [typed, setTyped] = useState("");
  const picker = useLocationPicker({ purpose: "stock" }, value);
  const planned = useLocationsById(
    plannedId && plannedId !== value ? [plannedId] : [],
  );
  const followPlan = placeholder ?? t("detail.lineTargetFollowPlan");

  const marked = (mark: LineChoiceMark, option: LocationOption) => ({
    id: option.id,
    name: option.name,
    path: option.path,
    icon: option.icon,
    badge: t(MARK_LABEL_KEYS[mark]),
  });
  const plannedLocation = plannedId ? planned.byId.get(plannedId) : undefined;
  const offered = picker.options;
  const named = (id: string | null | undefined) =>
    id
      ? (offered.find((option) => option.id === id) ??
        (plannedLocation?.id === id
          ? locationOption(plannedLocation)
          : undefined))
      : undefined;
  // Nothing typed: the line's own two shelves lead, marked, the rest behind
  // them in the server's order. Under a typed query they are answers to
  // nothing and stay where the search puts them.
  const lead: Array<ReturnType<typeof marked>> = [];
  if (!typed.trim()) {
    const current = value ? named(value) : undefined;
    if (current) lead.push(marked("current", current));
    const plan =
      plannedId && plannedId !== value ? named(plannedId) : undefined;
    if (plan) lead.push(marked("planned", plan));
  }
  const leadIds = new Set(lead.map((option) => option.id));
  const rows = [
    ...lead,
    ...offered.filter((option) => !leadIds.has(option.id)),
  ];

  return (
    <>
      <SearchableCombobox
        aria-label={t("detail.lineTargetLabel")}
        disabled={disabled}
        title={followPlan}
        options={rows}
        value={value ?? ""}
        onChange={(id) => onChange(id || null)}
        placeholder={followPlan}
        searchPlaceholder={t("receive.searchWarehouse")}
        loading={picker.loading}
        onSearchChange={(query) => {
          setTyped(query);
          picker.setSearch(query);
        }}
        clearable={placeholder === undefined}
        clearLabel={followPlan}
        wrapperClassName={wrapperClassName}
      />
      {picker.error && (
        <InlineQueryError error={picker.error} onRetry={picker.retry} />
      )}
    </>
  );
}
