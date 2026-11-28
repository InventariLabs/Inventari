import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Plus } from "lucide-react";

import {
  Card,
  Input,
  NativeSelect,
  Pagination,
  QueryResult,
  buttonVariants,
  formatDateInZone,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import { BookingStateBadge } from "../components/BookingStateBadge";
import { RentalsTabs } from "../components/RentalsTabs";
import { useBookings } from "../hooks/useRentals";

const PAGE_SIZE = 25;

export default function BookingsPage() {
  const { t } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [params] = useSearchParams();
  const partnerId = params.get("partner_id") ?? undefined;
  const itemId = params.get("item_id") ?? undefined;
  const bookings = useBookings({
    search: search.trim() || undefined,
    status: status || undefined,
    partner_id: partnerId,
    item_id: itemId,
    limit: PAGE_SIZE,
    offset,
  });

  useEffect(() => {
    setHeader({
      title: t("title"),
      actions: (
        <Link
          to="/rentals/bookings/new"
          className={buttonVariants({ variant: "primary" })}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {t("today.newBooking")}
        </Link>
      ),
    });
  }, [setHeader, t]);

  return (
    <div className="flex flex-col gap-5">
      <RentalsTabs />
      {partnerId || itemId ? (
        <div className="flex flex-wrap items-center gap-2 rounded-lg bg-zinc-100 px-3 py-2 text-sm">
          <span>
            {itemId ? t("bookings.itemFilter") : t("bookings.partnerFilter")}
          </span>
          <Link to="/rentals/bookings" className="text-teal-700 underline">
            {t("bookings.clearFilter")}
          </Link>
        </div>
      ) : null}
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-0 flex-1 basis-64">
          <Input
            type="search"
            label={t("bookings.search")}
            value={search}
            onChange={(event) => {
              setOffset(0);
              setSearch(event.target.value);
            }}
          />
        </div>
        <div className="w-48">
          <NativeSelect
            label={t("bookings.status")}
            value={status}
            onChange={(event) => {
              setOffset(0);
              setStatus(event.target.value);
            }}
          >
            <option value="">{t("bookings.all")}</option>
            <option value="RESERVED">{t("status.reserved")}</option>
            <option value="PICKED_UP">{t("status.picked_up")}</option>
            <option value="RETURNED">{t("status.returned")}</option>
            <option value="CANCELLED">{t("status.cancelled")}</option>
          </NativeSelect>
        </div>
      </div>

      <QueryResult query={bookings}>
        {(page) => (
          <>
            {page.items.length === 0 ? (
              <Card className="px-4 py-10 text-center text-sm text-zinc-500">
                {t("bookings.empty")}
              </Card>
            ) : (
              <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
                {page.items.map((booking) => (
                  <Link
                    key={booking.id}
                    to={`/rentals/bookings/${booking.id}`}
                    className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-4 py-3.5 text-inherit no-underline last:border-b-0 hover:bg-zinc-50"
                  >
                    <div className="min-w-0 flex-[1_1_240px]">
                      <span className="block text-sm font-semibold">
                        {booking.borrower_name}
                      </span>
                      <span className="block text-sm text-zinc-500">
                        {booking.summary}
                      </span>
                    </div>
                    <span className="text-sm text-zinc-600">
                      {formatDateInZone(booking.starts_at, timezone)}{" "}
                      {formatDateInZone(booking.starts_at, timezone, {
                        variant: "time",
                      })}
                      {" – "}
                      {formatDateInZone(booking.ends_at, timezone)}{" "}
                      {formatDateInZone(booking.ends_at, timezone, {
                        variant: "time",
                      })}
                    </span>
                    <BookingStateBadge
                      status={booking.status}
                      isLate={booking.is_late}
                      lateDays={booking.late_days}
                    />
                  </Link>
                ))}
              </div>
            )}
            <Pagination
              skip={offset}
              limit={PAGE_SIZE}
              total={page.total}
              onPrev={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
              onNext={() => setOffset(offset + PAGE_SIZE)}
              onPageChange={setOffset}
            />
          </>
        )}
      </QueryResult>
    </div>
  );
}
