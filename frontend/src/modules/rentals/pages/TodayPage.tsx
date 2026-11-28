import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";

import {
  Card,
  QueryResult,
  buttonVariants,
  formatDateInZone,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import { BookingStateBadge } from "../components/BookingStateBadge";
import { RentalsTabs } from "../components/RentalsTabs";
import { useToday } from "../hooks/useRentals";
import type { TodayItem } from "../api/rentals";

export default function TodayPage() {
  const { t } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const today = useToday();

  useEffect(() => {
    setHeader({
      title: t("title"),
      subtitle: today.data
        ? formatDateInZone(today.data.date, timezone)
        : undefined,
      actions: (
        <div className="flex flex-wrap gap-2">
          <Link
            to="/rentals/guide"
            className={buttonVariants({ variant: "outline" })}
          >
            {t("today.guide")}
          </Link>
          <Link
            to="/rentals/bookings/new"
            className={buttonVariants({ variant: "primary" })}
          >
            <Plus className="mr-1.5 h-4 w-4" />
            {t("today.newBooking")}
          </Link>
        </div>
      ),
    });
  }, [setHeader, t, today.data, timezone]);

  return (
    <div className="flex flex-col gap-5">
      <RentalsTabs />
      <QueryResult query={today}>
        {(data) => (
          <div className="flex flex-col gap-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <CounterCard
                label={t("today.pickupsCount")}
                value={data.pickups_count}
              />
              <CounterCard
                label={t("today.returnsCount")}
                value={data.returns_count}
              />
              <CounterCard
                label={t("today.lateCount")}
                value={data.late_count}
                danger
              />
            </div>

            <div className="flex flex-wrap items-start gap-5">
              <div className="flex min-w-0 flex-[999_1_520px] flex-col gap-5">
                <Section title={t("today.lateTitle")}>
                  {data.late.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-zinc-500">
                      {t("today.noLate")}
                    </p>
                  ) : (
                    data.late.map((item) => (
                      <BookingRow
                        key={item.booking_id}
                        item={item}
                        late
                        timeOf="due"
                        lateDays={item.late_days}
                        action={
                          <div className="flex flex-wrap gap-2">
                            <Link
                              to={`/rentals/bookings/${item.booking_id}`}
                              aria-label={t("today.extendNamed", {
                                name: item.what,
                              })}
                              className={buttonVariants({
                                variant: "outline",
                                size: "sm",
                              })}
                            >
                              {t("today.extend")}
                            </Link>
                            <Link
                              to={`/rentals/bookings/${item.booking_id}`}
                              aria-label={t("today.takeBackNamed", {
                                name: item.what,
                              })}
                              className={buttonVariants({
                                variant: "primary",
                                size: "sm",
                              })}
                            >
                              {t("today.takeBack")}
                            </Link>
                          </div>
                        }
                      />
                    ))
                  )}
                </Section>

                {(data.expired ?? []).length ? (
                  <Section title={t("today.expiredTitle")}>
                    <p className="px-4 pt-3 text-xs text-zinc-500">
                      {t("today.expiredHint")}
                    </p>
                    {(data.expired ?? []).map((item) => (
                      <BookingRow
                        key={item.booking_id}
                        item={item}
                        badge="RESERVED"
                        timeOf="return"
                        action={
                          <Link
                            to={`/rentals/bookings/${item.booking_id}`}
                            aria-label={t("today.extendNamed", {
                              name: item.what,
                            })}
                            className={buttonVariants({
                              variant: "outline",
                              size: "sm",
                            })}
                          >
                            {t("today.extend")}
                          </Link>
                        }
                      />
                    ))}
                  </Section>
                ) : null}

                <Section title={t("today.pickupsTitle")}>
                  {data.pickups.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-zinc-500">
                      {t("today.noPickups")}
                    </p>
                  ) : (
                    data.pickups.map((item) => (
                      <BookingRow
                        key={item.booking_id}
                        item={item}
                        badge="RESERVED"
                        action={
                          item.can_pickup ? (
                            <Link
                              to={`/rentals/bookings/${item.booking_id}/pickup`}
                              aria-label={t("today.handOutNamed", {
                                name: item.what,
                              })}
                              className={buttonVariants({
                                variant: "outline",
                                size: "sm",
                              })}
                            >
                              {t("today.handOut")}
                            </Link>
                          ) : (
                            <Link
                              to={`/rentals/bookings/${item.booking_id}`}
                              aria-label={t("today.extendNamed", {
                                name: item.what,
                              })}
                              className={buttonVariants({
                                variant: "outline",
                                size: "sm",
                              })}
                            >
                              {t("today.extend")}
                            </Link>
                          )
                        }
                      />
                    ))
                  )}
                </Section>

                <Section title={t("today.returnsTitle")}>
                  {data.returns.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-zinc-500">
                      {t("today.noReturns")}
                    </p>
                  ) : (
                    data.returns.map((item) => (
                      <BookingRow
                        key={item.booking_id}
                        item={item}
                        timeOf="return"
                        badge="PICKED_UP"
                        action={
                          <Link
                            to={`/rentals/bookings/${item.booking_id}`}
                            aria-label={t("today.takeBackNamed", {
                              name: item.what,
                            })}
                            className={buttonVariants({
                              variant: "outline",
                              size: "sm",
                            })}
                          >
                            {t("today.takeBack")}
                          </Link>
                        }
                      />
                    ))
                  )}
                </Section>
              </div>

              <aside className="min-w-0 flex-1 basis-72">
                <Section title={t("today.inServiceTitle")}>
                  {data.in_service.length === 0 ? (
                    <p className="px-4 py-4 text-sm text-zinc-500">
                      {t("today.noService")}
                    </p>
                  ) : (
                    data.in_service.map((block) => (
                      <div
                        key={block.id}
                        className="flex flex-col gap-0.5 border-b border-zinc-100 px-4 py-3.5 last:border-b-0"
                      >
                        <span className="text-sm font-semibold">
                          {block.item_name}
                          {block.item_serial_number
                            ? ` · ${block.item_serial_number}`
                            : ""}
                        </span>
                        <span className="text-sm text-zinc-500">
                          {t("today.until", {
                            date: formatDateInZone(block.ends_at, timezone),
                          })}
                          {" · "}
                          {block.reason}
                        </span>
                      </div>
                    ))
                  )}
                  <p className="px-4 pb-4 pt-2 text-xs text-zinc-500">
                    {t("today.serviceNote")}
                  </p>
                </Section>
              </aside>
            </div>
          </div>
        )}
      </QueryResult>
    </div>
  );
}

function CounterCard({
  label,
  value,
  danger,
}: {
  label: string;
  value: number;
  danger?: boolean;
}) {
  return (
    <Card
      className={
        danger ? "border-red-200 bg-red-50 px-4 py-4" : "bg-white px-4 py-4"
      }
    >
      <span className={`text-xs ${danger ? "text-red-800" : "text-zinc-500"}`}>
        {label}
      </span>
      <span
        className={`block text-xl font-semibold ${danger ? "text-red-800" : ""}`}
      >
        {value}
      </span>
    </Card>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <h2 className="border-b border-zinc-200 px-4 py-3.5 text-base font-semibold">
        {title}
      </h2>
      {children}
    </section>
  );
}

function BookingRow({
  item,
  late,
  lateDays,
  badge,
  timeOf = "start",
  action,
}: {
  item: TodayItem;
  late?: boolean;
  lateDays?: number;
  badge?: "RESERVED" | "PICKED_UP";
  /** Which moment the row leads with: pickup, return, or a missed due date. */
  timeOf?: "start" | "return" | "due";
  action: React.ReactNode;
}) {
  const { t } = useTranslation("rentals");
  const timezone = useOrganizationTimezone();
  const at = timeOf === "start" ? item.at : item.until;
  return (
    <div className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-4 py-3.5 last:border-b-0">
      <span className="w-14 text-sm font-semibold text-zinc-500">
        {formatDateInZone(at, timezone, { variant: "time" })}
      </span>
      <Link
        to={`/rentals/bookings/${item.booking_id}`}
        className="min-w-0 flex-[1_1_240px] no-underline"
      >
        <span className="block text-sm font-semibold text-zinc-900">
          {item.what}
        </span>
        <span className="block text-sm text-zinc-500">
          {item.borrower_name}
          {timeOf === "due" && item.until
            ? ` · ${t("today.wasDue", {
                date: formatDateInZone(item.until, timezone, {
                  variant: "datetime",
                }),
              })}`
            : item.until && timeOf !== "due"
              ? ` · ${t("today.untilShort", {
                  date: formatDateInZone(item.until, timezone),
                })}`
              : ""}
        </span>
      </Link>
      {badge ? (
        <BookingStateBadge status={badge} isLate={late} lateDays={lateDays} />
      ) : (
        <BookingStateBadge
          status="PICKED_UP"
          isLate={late}
          lateDays={lateDays}
        />
      )}
      {action}
    </div>
  );
}
