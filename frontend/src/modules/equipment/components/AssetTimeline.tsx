import { useTranslation } from "react-i18next";
import {
  AlertTriangle,
  Package,
  User,
  RotateCcw,
  Wrench,
  RefreshCw,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { cn } from "@/lib/utils";
import LoadingSpinner from "@/components/LoadingSpinner";
import { formatMoney } from "@/utils/formatters";
import { formatDate } from "@/utils/helpers";
import { getEquipmentMeta } from "@/modules/equipment/components/assetUtils";
import { useAssetTimeline } from "@/modules/equipment/hooks/useEquipment";
import type { Item } from "@/types";
import type { AssetTimelineEvent } from "@/modules/equipment/api/equipment_timeline";
import { useOrganizationCurrency } from "@/hooks/useOrganizationCurrency";
import { useFormatOrgDay } from "@/hooks/useOrganizationTimezone";
import { EmptyState } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";

type TimelineT = ReturnType<typeof useTranslation<"equipment">>["t"];

const TYPE_ICONS: Record<string, React.ReactNode> = {
  CREATED: <Package size={16} />,
  CHECKOUT: <User size={16} />,
  CHECKIN: <RotateCcw size={16} />,
  MAINTENANCE: <Wrench size={16} />,
  STATUS_CHANGED: <RefreshCw size={16} />,
  DISPUTED: <AlertTriangle size={16} />,
};

const TYPE_BG: Record<string, string> = {
  CREATED: "bg-primary-50 text-primary-600",
  CHECKOUT: "bg-primary-50 text-primary-600",
  CHECKIN: "bg-success-50 text-success-600",
  MAINTENANCE: "bg-amber-50 text-amber-600",
  STATUS_CHANGED: "bg-surface text-on-secondary",
  DISPUTED: "bg-red-50 text-red-600",
};

/** The reported problem in the words the holder picked it from. */
const DISPUTE_TYPE_KEYS: Record<string, string> = {
  MISSING: "attestation.public.issueTypeMissing",
  DAMAGED: "attestation.public.issueTypeDamaged",
  WRONG_ITEM: "attestation.public.issueTypeWrongItem",
  OTHER: "attestation.public.issueTypeOther",
};

/** The timeline entry the interface renders: the kind names the icon and
 * the badge, the rest is already the server's wording of what happened. */
interface TimelineEvent {
  id: string;
  type: string;
  date: string;
  title: string;
  subtitle: string | null;
  details: string[];
}

/** An equipment status value into the interface's vocabulary; a status the
 * dictionary does not know reads back as itself rather than as nothing. */
function statusLabel(t: TimelineT, value: string | null | undefined): string {
  if (!value) return "—";
  return t(`status.${value.toLowerCase()}`, value);
}

/**
 * What the holder answered an attestation with, on the asset itself: the
 * report used to stay on the campaign's response alone.
 */
function disputedEntry(event: AssetTimelineEvent, t: TimelineT) {
  const typeKey = event.condition ? DISPUTE_TYPE_KEYS[event.condition] : null;
  return {
    type: "DISPUTED",
    title: t("timeline.attestation_disputed", { name: event.holder_name }),
    subtitle: event.title ?? null,
    details: [
      ...(typeKey ? [t(typeKey)] : []),
      ...(event.notes ? [event.notes] : []),
    ],
  };
}

/** The return card's title: a person's return names the holder, a
 * deployment's names the place it left. A return read as "who the asset
 * was with" used to claim the holder carried it back even when an
 * administrator checked it off for them — the entry says which of the two
 * happened. */
function checkinTitle(event: AssetTimelineEvent, t: TimelineT): string {
  if (event.holder_kind === "location") {
    return event.operator_name
      ? t(
          "timeline.removed_from_by",
          "Returned from {{name}} by {{operator}}",
          {
            name: event.holder_name,
            operator: event.operator_name,
          },
        )
      : t("timeline.removed_from", "Returned from {{name}}", {
          name: event.holder_name,
        });
  }
  if (
    event.operator_name != null &&
    event.operator_name === event.holder_name
  ) {
    return t("timeline.checked_in_by", "Returned by {{name}}", {
      name: event.holder_name,
    });
  }
  if (event.operator_name) {
    return t(
      "timeline.checked_in_for",
      "Returned for {{name}} by {{operator}}",
      { name: event.holder_name, operator: event.operator_name },
    );
  }
  return t("timeline.checked_in", "Returned");
}

function eventFromServer(
  event: AssetTimelineEvent,
  t: TimelineT,
  orgCurrency: string | null,
  lang: string,
  // The expected return is an org-clock day; the caller owns the zone.
  formatDay: (value: string | null | undefined) => string,
): TimelineEvent | null {
  const base = {
    // The source row's own identity; the string is only a stand-in for
    // feeds that predate it.
    id: event.id ?? `${event.kind}-${event.date}-${event.title ?? ""}`,
    date: event.date,
    subtitle: null as string | null,
    details: [] as string[],
  };

  switch (event.kind) {
    case "created": {
      return {
        ...base,
        type: "CREATED",
        title: t("timeline.created", "Asset created"),
      };
    }
    case "checkout": {
      // A deployment has no person to name; the entry says the asset was
      // placed in the location instead of claiming it was handed to one.
      const placedIn = event.holder_kind === "location";
      return {
        ...base,
        type: "CHECKOUT",
        title: placedIn
          ? t("timeline.placed_in", "Checked out to {{name}}", {
              name: event.holder_name,
            })
          : t("timeline.checked_out_to", "Checked out to {{name}}", {
              name: event.holder_name,
            }),
        subtitle: placedIn ? null : (event.holder_email ?? null),
        details: [
          ...(event.expected_return_at
            ? [
                `${t("timeline.expected_return")}: ${formatDay(event.expected_return_at)}`,
              ]
            : []),
          // Who handed the asset over — the other half of the handover
          // record, so an auditor can reconstruct who was responsible for
          // the transfer, not only who received it.
          ...(event.issued_by_name
            ? [`${t("timeline.issued_by")}: ${event.issued_by_name}`]
            : []),
          ...(event.notes ? [event.notes] : []),
        ],
      };
    }
    case "checkin": {
      return {
        ...base,
        type: "CHECKIN",
        title: checkinTitle(event, t),
        details: [
          ...(event.condition
            ? [
                `${t("timeline.condition")}: ${t(`assignments.condition_${event.condition.toLowerCase()}`)}`,
              ]
            : []),
          ...(event.notes ? [event.notes] : []),
        ],
      };
    }
    case "maintenance": {
      return {
        ...base,
        type: "MAINTENANCE",
        title: `${t(`maintenance.type_${(event.maintenance_type ?? "other").toLowerCase()}`)}: ${event.title}`,
        subtitle: event.actor ?? null,
        details: [
          ...(event.cost != null
            ? [
                `${t("maintenance.cost")}: ${formatMoney(event.cost, event.currency ?? orgCurrency, lang)}`,
              ]
            : []),
          ...(event.description ? [event.description] : []),
          ...(event.next_maintenance_at
            ? [
                `${t("maintenance.next_maintenance")}: ${formatDate(event.next_maintenance_at)}`,
              ]
            : []),
        ],
      };
    }
    case "status_changed":
      return {
        ...base,
        type: "STATUS_CHANGED",
        title: t("timeline.status_changed", "Status changed"),
        details: [
          `${statusLabel(t, event.old_status)} → ${statusLabel(t, event.new_status)}`,
        ],
      };
    case "attestation_disputed":
      return { ...base, ...disputedEntry(event, t) };
    // A kind this screen cannot name is left out rather than dressed as a
    // status change with an empty transition — the server applies the same
    // rule to the history rows it reads.
    default:
      return null;
  }
}

interface AssetTimelineProps {
  item: Item;
}

export function AssetTimeline({ item }: AssetTimelineProps) {
  const { t, i18n } = useTranslation("equipment");
  const lang = i18n.language?.substring(0, 2) ?? "en";
  const orgCurrency = useOrganizationCurrency();
  const formatOrgDay = useFormatOrgDay();
  const {
    data: events = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useAssetTimeline(item.id);

  // A failed read says so; the default empty array must not speak for it —
  // the timeline would otherwise open on "Asset created" over a record the
  // register could not finish reading.
  if (isError) {
    return (
      <QueryFailure
        error={error}
        onRetry={() => {
          void refetch();
        }}
      />
    );
  }

  if (isLoading) {
    return (
      <div>
        <LoadingSpinner />
      </div>
    );
  }

  const meta = getEquipmentMeta(item);
  const brandInfo = [item.brand, meta.model].filter(Boolean).join(" — ");

  // One ordering, one owner: the feed arrives sorted by the server, and
  // nothing is appended around it — a card pushed in front of a
  // newest-first feed would put the asset's oldest day on top.
  const timeline: TimelineEvent[] = events.flatMap((event) => {
    const rendered = eventFromServer(
      event,
      t,
      orgCurrency ?? null,
      lang,
      formatOrgDay,
    );
    if (rendered === null) return [];
    if (event.kind === "created" && brandInfo) {
      return [{ ...rendered, details: [brandInfo] }];
    }
    return [rendered];
  });

  return (
    <div className="space-y-4">
      {timeline.length === 0 ? (
        <EmptyState
          variant="compact"
          title={t("timeline.empty", "No history yet")}
        />
      ) : (
        <div className="relative pl-12 space-y-0">
          <div className="absolute left-[15px] top-2 bottom-2 w-px bg-border" />

          {timeline.map((event) => (
            <div key={event.id} className="relative pb-5 last:pb-0">
              <div
                className={cn(
                  "absolute -left-[21px] top-1 flex h-7 w-7 items-center justify-center rounded-full ring-4 ring-surface",
                  TYPE_BG[event.type] ?? "bg-surface text-on-secondary",
                )}
              >
                {TYPE_ICONS[event.type] ?? <Package size={16} />}
              </div>

              <div className="ml-3">
                <div className="flex items-center gap-2 flex-wrap">
                  <span className="text-sm font-medium text-on">
                    {event.title}
                  </span>
                  <Badge variant="secondary" className="text-xs">
                    {t(`timeline.type_${event.type.toLowerCase()}` as const)}
                  </Badge>
                </div>

                {event.subtitle && (
                  <div className="text-xs text-on-muted mt-0.5">
                    {event.subtitle}
                  </div>
                )}

                <div className="text-xs text-on-muted mt-0.5">
                  {formatDate(event.date)}
                </div>

                {event.details.length > 0 && (
                  <div className="mt-1 space-y-0.5">
                    {event.details.map((d, i) => (
                      <p key={i} className="text-xs text-on-muted line-clamp-2">
                        {d}
                      </p>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
