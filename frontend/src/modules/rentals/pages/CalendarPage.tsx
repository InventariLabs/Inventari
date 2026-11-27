import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";

import {
  Button,
  NativeSelect,
  QueryResult,
  ScrollRow,
  categoryLabel,
  formatDateInZone,
  formatQuantityLocale,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import type { CalendarBar, CalendarGroup } from "../api/rentals";
import { RentalsTabs } from "../components/RentalsTabs";
import {
  useCalendar,
  useRentalCategories,
  useModels,
} from "../hooks/useRentals";
import {
  addDays,
  daysBetween,
  isoDate,
  startOfWeek,
  wallTimeToIso,
} from "../lib/datetime";

const DAYS = 14;

const LEGEND_KEYS: Record<string, string> = {
  reserved: "calendar.legend.reserved",
  out: "calendar.legend.out",
  late: "calendar.legend.late",
  returned: "calendar.legend.returned",
  block: "calendar.legend.block",
  buffer: "calendar.legend.buffer",
};

const BAR_STYLES: Record<string, string> = {
  reserved: "border-blue-300 bg-blue-100 text-blue-900",
  out: "border-success-300 bg-success-100 text-success-900",
  late: "border-red-300 bg-red-100 text-red-900",
  returned: "border-zinc-200 bg-zinc-100 text-zinc-600",
  block:
    "border-zinc-400 bg-[repeating-linear-gradient(135deg,#e4e4e7_0_6px,#f4f4f5_6px_12px)] text-zinc-700",
  buffer:
    "border-teal-200 bg-[repeating-linear-gradient(135deg,#99f6e4_0_3px,#ffffff_3px_6px)] text-teal-900",
};

export default function CalendarPage() {
  const { t, i18n } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const models = useModels();
  const categories = useRentalCategories();
  const [anchor, setAnchor] = useState(() =>
    startOfWeek(isoDate(new Date().toISOString(), timezone)),
  );
  const [model, setModel] = useState("");
  const [category, setCategory] = useState("");

  const days = useMemo(() => daysBetween(anchor, DAYS), [anchor]);
  const rangeStart = wallTimeToIso(anchor, "00:00", timezone);
  const rangeEnd = wallTimeToIso(addDays(anchor, DAYS), "00:00", timezone);
  const calendar = useCalendar(
    rangeStart,
    rangeEnd,
    model || undefined,
    category || undefined,
  );
  const optionsFailed = models.isError || categories.isError;

  useEffect(() => {
    setHeader({ title: t("title") });
  }, [setHeader, t]);

  const startMs = new Date(rangeStart).getTime();
  const endMs = new Date(rangeEnd).getTime();
  const span = endMs - startMs;
  const now = Date.now();
  const nowPercent = ((now - startMs) / span) * 100;
  const dayFormat = useMemo(
    () =>
      new Intl.DateTimeFormat(i18n.language, {
        weekday: "short",
        day: "numeric",
      }),
    [i18n.language],
  );

  return (
    <div className="flex flex-col gap-5">
      <RentalsTabs />
      {optionsFailed ? (
        <p
          role="alert"
          className="m-0 rounded-lg bg-red-50 p-3 text-sm text-red-800"
        >
          {t("errors.loadChoices")}
        </p>
      ) : null}
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex items-center gap-1">
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={t("calendar.previous")}
            onClick={() => setAnchor(addDays(anchor, -DAYS))}
          >
            <ChevronLeft className="h-4 w-4" />
          </Button>
          <span className="px-2 text-sm font-semibold">
            {formatDateInZone(rangeStart, timezone)} –{" "}
            {formatDateInZone(new Date(endMs - 1).toISOString(), timezone)}
          </span>
          <Button
            type="button"
            variant="outline"
            size="icon"
            aria-label={t("calendar.next")}
            onClick={() => setAnchor(addDays(anchor, DAYS))}
          >
            <ChevronRight className="h-4 w-4" />
          </Button>
          <Button
            type="button"
            variant="outline"
            className="ml-1"
            onClick={() =>
              setAnchor(
                startOfWeek(isoDate(new Date().toISOString(), timezone)),
              )
            }
          >
            {t("calendar.today")}
          </Button>
        </div>
        <div className="w-52">
          <NativeSelect
            label={t("calendar.model")}
            value={model}
            onChange={(event) => setModel(event.target.value)}
          >
            <option value="">{t("calendar.allModels")}</option>
            {(models.data ?? []).map((entry) => (
              <option key={entry.model} value={entry.model}>
                {entry.model}
              </option>
            ))}
          </NativeSelect>
        </div>
        <div className="w-48">
          <NativeSelect
            label={t("calendar.category")}
            value={category}
            onChange={(event) => setCategory(event.target.value)}
          >
            <option value="">{t("calendar.allCategories")}</option>
            {(categories.data ?? []).map((entry) => (
              <option key={entry.id} value={entry.id}>
                {categoryLabel(t, entry.code, entry.name)}
              </option>
            ))}
          </NativeSelect>
        </div>
      </div>

      <ScrollRow className="text-xs text-zinc-700">
        <div className="flex flex-wrap gap-4">
          {(
            ["reserved", "out", "late", "returned", "block", "buffer"] as const
          ).map((kind) => (
            <span key={kind} className="flex items-center gap-1.5">
              <span
                className={`inline-block h-2.5 w-4 rounded-sm border ${BAR_STYLES[kind]}`}
              />
              {t(LEGEND_KEYS[kind])}
            </span>
          ))}
          <span className="flex items-center gap-1.5">
            <span className="inline-block h-3.5 w-0.5 bg-teal-700" />
            {t("calendar.legend.now")}
          </span>
        </div>
      </ScrollRow>

      <QueryResult query={calendar}>
        {(data) => (
          <div className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
            <ScrollRow>
              <div className="min-w-[980px]">
                <div className="flex border-b border-zinc-200">
                  <div className="w-[210px] flex-none px-4 py-2.5 text-xs text-zinc-500">
                    {t("calendar.equipment")}
                  </div>
                  <div
                    className="grid flex-1"
                    style={{
                      gridTemplateColumns: `repeat(${DAYS}, minmax(0, 1fr))`,
                    }}
                  >
                    {days.map((day) => {
                      const isToday =
                        isoDate(new Date().toISOString(), timezone) === day;
                      return (
                        <div
                          key={day}
                          className={`border-l border-zinc-100 py-2 text-center text-xs ${
                            isToday
                              ? "bg-teal-50 font-medium text-teal-700"
                              : "text-zinc-500"
                          }`}
                        >
                          {dayFormat.format(new Date(`${day}T12:00:00Z`))}
                        </div>
                      );
                    })}
                  </div>
                </div>

                {data.groups.length === 0 ? (
                  <p className="px-4 py-8 text-center text-sm text-zinc-500">
                    {t("calendar.empty")}
                  </p>
                ) : (
                  data.groups.map((group) => (
                    <Group
                      key={group.model ?? "none"}
                      group={group}
                      days={days}
                      startMs={startMs}
                      span={span}
                      nowPercent={nowPercent}
                      timezone={timezone}
                    />
                  ))
                )}
              </div>
            </ScrollRow>
            <p className="px-4 py-3 text-xs text-zinc-500">
              {t("calendar.anyUnitNote")}
            </p>
          </div>
        )}
      </QueryResult>
    </div>
  );
}

function Group({
  group,
  days,
  startMs,
  span,
  nowPercent,
  timezone,
}: {
  group: CalendarGroup;
  days: string[];
  startMs: number;
  span: number;
  nowPercent: number;
  timezone?: string;
}) {
  const { t } = useTranslation("rentals");
  const label = group.model ?? t("calendar.noModel");
  return (
    <>
      <div className="flex items-center gap-2 border-b border-zinc-200 bg-zinc-50 px-4 py-2">
        <span className="text-sm font-semibold">{label}</span>
        <span className="text-xs text-zinc-500">
          {t("calendar.units", { count: group.total_units })}
          {group.service_units
            ? ` · ${t("calendar.inService", { count: group.service_units })}`
            : ""}
        </span>
      </div>
      {group.any_unit.length ? (
        <Row
          name={t("calendar.anyUnit")}
          italic
          bars={group.any_unit.map((entry) => ({
            kind: entry.status === "RESERVED" ? "reserved" : "out",
            label: t("calendar.anyUnitLabel", {
              name: entry.borrower_name,
              quantity: formatQuantityLocale(entry.quantity),
            }),
            starts_at: entry.starts_at,
            ends_at: entry.ends_at,
            booking_id: entry.booking_id,
          }))}
          days={days}
          startMs={startMs}
          span={span}
          nowPercent={nowPercent}
          timezone={timezone}
        />
      ) : null}
      {group.units.map((unit) => (
        <Row
          key={unit.item_id}
          name={`${unit.name}${unit.serial_number ? ` · ${unit.serial_number}` : ""}`}
          bars={unit.bars ?? []}
          days={days}
          startMs={startMs}
          span={span}
          nowPercent={nowPercent}
          timezone={timezone}
        />
      ))}
    </>
  );
}

function Row({
  name,
  bars,
  days,
  startMs,
  span,
  nowPercent,
  italic,
  timezone,
}: {
  name: string;
  bars: CalendarBar[];
  days: string[];
  startMs: number;
  span: number;
  nowPercent: number;
  italic?: boolean;
  timezone?: string;
}) {
  const { t } = useTranslation("rentals");
  // Bars that overlap in time are stacked instead of drawn over each other:
  // a returned stretch beside a new reservation is two facts, not one label.
  const laidOut = useMemo(() => {
    const laneEnds: number[] = [];
    return bars.map((bar) => {
      const start = new Date(bar.starts_at).getTime();
      const end = new Date(bar.ends_at).getTime();
      let lane = laneEnds.findIndex((until) => start >= until);
      if (lane === -1) {
        lane = laneEnds.length;
        laneEnds.push(end);
      } else {
        laneEnds[lane] = end;
      }
      return { bar, lane };
    });
  }, [bars]);
  const lanes = Math.max(1, ...laidOut.map((entry) => entry.lane + 1));
  const height = 44 + (lanes - 1) * 30;

  return (
    <div className="flex border-b border-zinc-100">
      <div
        className={`flex w-[210px] flex-none items-center px-4 text-sm ${
          italic ? "italic text-zinc-500" : "text-zinc-900"
        }`}
        style={{ height }}
      >
        {name}
      </div>
      <div className="relative flex-1" style={{ height }}>
        <div
          className="absolute inset-0 grid"
          style={{
            gridTemplateColumns: `repeat(${days.length}, minmax(0, 1fr))`,
          }}
        >
          {days.map((day) => (
            <div key={day} className="border-l border-zinc-100" />
          ))}
        </div>
        {laidOut.map(({ bar, lane }, index) => {
          const left =
            ((new Date(bar.starts_at).getTime() - startMs) / span) * 100;
          const width =
            ((new Date(bar.ends_at).getTime() -
              new Date(bar.starts_at).getTime()) /
              span) *
            100;
          const label =
            bar.kind === "buffer"
              ? ""
              : bar.kind === "block"
                ? `${t("calendar.legend.block")} · ${bar.label}`
                : bar.label;
          return (
            <div
              key={`${bar.kind}-${index}`}
              title={`${label} · ${formatDateInZone(bar.starts_at, timezone)}`}
              className={`absolute flex h-7 items-center overflow-hidden whitespace-nowrap rounded-md border px-2 text-xs font-medium ${
                BAR_STYLES[bar.kind] ?? BAR_STYLES.reserved
              }`}
              style={{
                left: `${left}%`,
                width: `${width}%`,
                top: 8 + lane * 30,
              }}
            >
              {label}
            </div>
          );
        })}
        {nowPercent >= 0 && nowPercent <= 100 ? (
          <div
            className="absolute inset-y-0 w-0.5 bg-teal-700"
            style={{ left: `${nowPercent}%` }}
          />
        ) : null}
      </div>
    </div>
  );
}
