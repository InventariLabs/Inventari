import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { CalendarClock } from "lucide-react";

import {
  EmptyState,
  LoadingSpinner,
  QueryError,
  formatDateInZone,
  useOrganizationTimezone,
} from "@/module-sdk";

import type { BookingListParams, BookingListPage } from "../api/rentals";
import { useBookings } from "../hooks/useRentals";
import { BookingStateBadge } from "./BookingStateBadge";

type BookingRow = BookingListPage["items"][number];

/** How many bookings the card shows before the full list takes over. */
const ROW_LIMIT = 5;

/** A booking that is still to happen, or is out with its borrower. */
const UPCOMING: ReadonlyArray<BookingRow["status"]> = ["RESERVED", "PICKED_UP"];

interface RentalHistorySectionProps {
  /** Names the region for a screen reader — "Rental history — <subject>". */
  sectionLabel: string;
  heading: string;
  emptyTitle: string;
  params: BookingListParams;
  viewAllTo: string;
  /** An asset's card names who borrowed it; a partner's card is about them. */
  showBorrower?: boolean;
  /**
   * In the partner sheet the sheet's own name is the `h2`, so the section is
   * an `h3`; on an asset page the section is the first level of content.
   */
  headingLevel?: "h2" | "h3";
}

/**
 * A partner's or an asset's rentals, read through the module's own list.
 *
 * Shared by the two slots so the two cards cannot drift: the only differences
 * are the heading, the empty sentence, whether the borrower is named and the
 * address of the full list. The list itself stays the authority on history —
 * this card shows the latest few and opens it.
 */
export function RentalHistorySection({
  sectionLabel,
  heading,
  emptyTitle,
  params,
  viewAllTo,
  showBorrower = false,
  headingLevel = "h2",
}: RentalHistorySectionProps) {
  const { t } = useTranslation("rentals");
  const timezone = useOrganizationTimezone();
  const bookings = useBookings({ ...params, limit: ROW_LIMIT });
  const rows = (bookings.data?.items ?? []).slice(0, ROW_LIMIT);
  const upcoming = rows.filter((row) => UPCOMING.includes(row.status));
  const past = rows.filter((row) => !UPCOMING.includes(row.status));
  const Heading = headingLevel;
  const GroupHeading = headingLevel === "h2" ? "h3" : "h4";

  return (
    <section aria-label={sectionLabel} className="space-y-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <Heading className="text-base font-semibold text-on">{heading}</Heading>
        {rows.length > 0 && (
          <Link
            to={viewAllTo}
            className="text-sm font-medium text-on-primary hover:underline"
          >
            {t("history.viewAll")}
          </Link>
        )}
      </div>

      {bookings.isError ? (
        <QueryError
          error={bookings.error}
          onRetry={() => void bookings.refetch()}
        />
      ) : bookings.isLoading ? (
        <LoadingSpinner />
      ) : rows.length === 0 ? (
        <EmptyState variant="compact" icon={CalendarClock} title={emptyTitle} />
      ) : (
        <div className="space-y-3">
          {upcoming.length > 0 && (
            <div className="space-y-1.5">
              <GroupHeading className="text-xs font-medium uppercase tracking-wide text-on-muted">
                {t("history.upcoming")}
              </GroupHeading>
              <RentalRows
                rows={upcoming}
                showBorrower={showBorrower}
                timezone={timezone}
              />
            </div>
          )}
          {past.length > 0 && (
            <div className="space-y-1.5">
              <GroupHeading className="text-xs font-medium uppercase tracking-wide text-on-muted">
                {t("history.past")}
              </GroupHeading>
              <RentalRows
                rows={past}
                showBorrower={showBorrower}
                timezone={timezone}
              />
            </div>
          )}
        </div>
      )}
    </section>
  );
}

function RentalRows({
  rows,
  showBorrower,
  timezone,
}: {
  rows: BookingRow[];
  showBorrower: boolean;
  timezone: string | undefined;
}) {
  return (
    <ul className="divide-y divide-border overflow-hidden rounded-lg border border-border">
      {rows.map((row) => (
        <li key={row.id}>
          <Link
            to={`/rentals/bookings/${row.id}`}
            className="flex items-start justify-between gap-3 px-3 py-2.5 text-inherit no-underline hover:bg-surface-raised"
          >
            <span className="min-w-0 flex-1 text-sm">
              {showBorrower && (
                <span className="block font-medium text-on">
                  {row.borrower_name}
                </span>
              )}
              <span className="block text-on-secondary">{row.summary}</span>
              <span className="mt-0.5 block text-xs text-on-muted">
                {formatDateInZone(row.starts_at, timezone)}{" "}
                {formatDateInZone(row.starts_at, timezone, {
                  variant: "time",
                })}
                {" – "}
                {formatDateInZone(row.ends_at, timezone)}{" "}
                {formatDateInZone(row.ends_at, timezone, {
                  variant: "time",
                })}
              </span>
            </span>
            <span className="shrink-0">
              <BookingStateBadge
                status={row.status}
                isLate={row.is_late}
                lateDays={row.late_days}
              />
            </span>
          </Link>
        </li>
      ))}
    </ul>
  );
}
