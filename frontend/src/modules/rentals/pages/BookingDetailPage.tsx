import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";

import {
  Button,
  Card,
  ConfirmDialog,
  Input,
  LoadingSpinner,
  QueryError,
  RecordNotFound,
  NativeSelect,
  ReadOnlyNotice,
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  buttonVariants,
  formatDateInZone,
  formatQuantityLocale,
  isNotFoundError,
  formatDateTime,
  useCanWrite,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import {
  rentalsApi,
  type Booking,
  type ReturnRequest,
  type UnitSchema,
} from "../api/rentals";
import { BookingStateBadge } from "../components/BookingStateBadge";
import { DateTimeField } from "../components/DateTimeField";
import { useBooking } from "../hooks/useRentals";
import { isoToWall, wallTimeToIso } from "../lib/datetime";
import { queryKeys } from "../queryKeys";

export default function BookingDetailPage() {
  const { t } = useTranslation("rentals");
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("rentals");
  const booking = useBooking(id);

  useEffect(() => {
    setHeader({ title: t("detail.title"), backTo: "/rentals" });
  }, [setHeader, t]);

  if (booking.isPending || booking.isLoading) return <LoadingSpinner />;
  if (booking.isError && !isNotFoundError(booking.error)) {
    return (
      <QueryError
        error={booking.error}
        onRetry={() => void booking.refetch()}
      />
    );
  }
  if (!booking.data) {
    return (
      <RecordNotFound
        title={t("detail.notFound")}
        backTo="/rentals"
        backLabel={t("title")}
      />
    );
  }
  const data = booking.data;

  return (
    <div className="flex flex-col gap-5">
      <ReadOnlyNotice module="rentals" />
      <Link
        to="/rentals"
        className="inline-flex min-h-11 items-center gap-1 text-sm"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("title")}
      </Link>
      <div className="flex flex-wrap items-start gap-5">
        <div className="flex min-w-0 flex-[999_1_480px] flex-col gap-5">
          <BookingHeader booking={data} canWrite={canWrite} />
          {data.status === "PICKED_UP" ? (
            <ReturnForm
              booking={data}
              canWrite={canWrite}
              onDone={() => {
                void qc.invalidateQueries({ queryKey: queryKeys.rentals.all });
                navigate("/rentals");
              }}
            />
          ) : null}
        </div>
        <aside className="min-w-0 flex-1 basis-72">
          <BookingFacts booking={data} />
        </aside>
      </div>
    </div>
  );
}

function BookingHeader({
  booking,
  canWrite,
}: {
  booking: Booking;
  canWrite: boolean;
}) {
  const { t } = useTranslation("rentals");
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [extendOpen, setExtendOpen] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const cancel = useMutation({
    mutationFn: () => rentalsApi.cancel(booking.id),
    onSuccess: async () => {
      await qc.invalidateQueries({ queryKey: queryKeys.rentals.all });
      navigate("/rentals");
    },
  });
  const summary = booking.lines
    .map((line) =>
      line.item_id
        ? line.item_name
        : t("form.modelWithCount", {
            model: line.model ?? "",
            quantity: formatQuantityLocale(line.quantity),
          }),
    )
    .filter(Boolean)
    .join(", ");
  return (
    <header className="flex flex-wrap items-center gap-3">
      <div className="min-w-0 flex-1">
        <h2 className="m-0 text-xl font-semibold">
          {booking.borrower_name} · {summary}
        </h2>
        <div className="mt-1 flex flex-wrap items-center gap-2">
          <BookingStateBadge
            status={booking.status}
            isLate={booking.is_late}
            lateDays={booking.late_days}
          />
          {booking.can_pickup ? (
            <Link
              to={`/rentals/bookings/${booking.id}/pickup`}
              className={buttonVariants({ variant: "primary", size: "sm" })}
            >
              {t("detail.handOut")}
            </Link>
          ) : null}
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {booking.can_extend ? (
          <Button
            type="button"
            variant="outline"
            disabled={!canWrite}
            onClick={() => setExtendOpen(true)}
          >
            {t("detail.extend")}
          </Button>
        ) : null}
        {booking.can_cancel ? (
          <Button
            type="button"
            variant="ghost"
            disabled={!canWrite}
            onClick={() => setConfirmCancel(true)}
          >
            {t("detail.cancel")}
          </Button>
        ) : null}
      </div>
      {extendOpen ? (
        <ExtendSheet
          booking={booking}
          onClose={() => setExtendOpen(false)}
          onDone={async () => {
            setExtendOpen(false);
            await qc.invalidateQueries({ queryKey: queryKeys.rentals.all });
          }}
        />
      ) : null}
      <ConfirmDialog
        open={confirmCancel}
        title={t("detail.cancelConfirmTitle")}
        message={t("detail.cancelConfirmMessage")}
        confirmLabel={t("detail.cancel")}
        cancelLabel={t("form.cancel")}
        variant="warning"
        onConfirm={() => cancel.mutate()}
        onCancel={() => setConfirmCancel(false)}
      />
    </header>
  );
}

function ExtendSheet({
  booking,
  onClose,
  onDone,
}: {
  booking: Booking;
  onClose: () => void;
  onDone: () => Promise<void>;
}) {
  const { t } = useTranslation("rentals");
  const timezone = useOrganizationTimezone();
  const initial = isoToWall(booking.ends_at, timezone);
  const [date, setDate] = useState(initial.date);
  const [time, setTime] = useState(initial.time);
  const [error, setError] = useState<string | null>(null);
  const extend = useMutation({
    mutationFn: () =>
      rentalsApi.extend(booking.id, wallTimeToIso(date, time, timezone)),
    onSuccess: () => void onDone(),
    onError: (failure: unknown) => {
      const detail = (
        failure as {
          response?: {
            data?: { detail?: { message?: string; conflicts?: unknown[] } };
          };
        }
      )?.response?.data?.detail;
      setError(
        detail?.conflicts?.length
          ? t("detail.extendBlocked")
          : (detail?.message ?? t("errors.generic")),
      );
    },
  });
  return (
    <Sheet open onClose={onClose} maxWidth="lg" aria-label={t("detail.extend")}>
      <SheetHeader title={t("detail.extend")} onClose={onClose} />
      <SheetBody className="p-5">
        <div className="flex flex-col gap-3">
          <DateTimeField
            id="extend-end"
            label={t("form.return")}
            date={date}
            time={time}
            onDateChange={setDate}
            onTimeChange={setTime}
          />
          {error ? (
            <p role="alert" className="m-0 text-sm text-red-700">
              {error}
            </p>
          ) : null}
        </div>
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("form.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            isLoading={extend.isPending}
            onClick={() => extend.mutate()}
          >
            {t("detail.extendSave")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}

const CONDITION_KEYS = {
  GOOD: "detail.condition.good",
  DAMAGED: "detail.condition.damaged",
  NEEDS_REPAIR: "detail.condition.needs_repair",
} as const;

type UnitReturn = {
  condition: "GOOD" | "DAMAGED" | "NEEDS_REPAIR";
  note: string;
  serviceReason: string;
  serviceDate: string;
  serviceTime: string;
};

type ServiceConflict = {
  booking_id: string;
  line_id: string;
  borrower_name: string;
  starts_at: string;
  ends_at: string;
  item_id: string;
  item_name: string;
  suggested_until: string;
  free_units: {
    item_id: string;
    name: string;
    serial_number?: string | null;
  }[];
};

function conflictsOf(error: unknown): ServiceConflict[] {
  const detail = (
    error as {
      response?: { data?: { detail?: { conflicts?: ServiceConflict[] } } };
    }
  )?.response?.data?.detail;
  return detail?.conflicts ?? [];
}

function ReturnForm({
  booking,
  onDone,
  canWrite,
}: {
  booking: Booking;
  onDone: () => void;
  canWrite: boolean;
}) {
  const { t } = useTranslation("rentals");
  const timezone = useOrganizationTimezone();
  const units = useMemo(
    () => booking.lines.flatMap((line) => line.units ?? []),
    [booking.lines],
  );
  const [state, setState] = useState<Record<string, UnitReturn>>(() => {
    const initial: Record<string, UnitReturn> = {};
    for (const unit of units) {
      initial[unit.id] = {
        condition: "GOOD",
        note: "",
        serviceReason: "",
        serviceDate: "",
        serviceTime: "16:00",
      };
    }
    return initial;
  });
  const [conflicts, setConflicts] = useState<ServiceConflict[]>([]);
  const [moveTo, setMoveTo] = useState<Record<string, string>>({});
  const [moveChecked, setMoveChecked] = useState<Record<string, boolean>>({});
  const [error, setError] = useState<string | null>(null);

  const submit = useMutation({
    mutationFn: (payload: ReturnRequest) =>
      rentalsApi.returnUnits(booking.id, payload),
    onSuccess: () => onDone(),
    onError: (failure: unknown) => {
      const found = conflictsOf(failure);
      if (found.length) {
        setConflicts(found);
        setMoveTo((current) => {
          const next = { ...current };
          for (const conflict of found) {
            next[conflict.booking_id] ??= conflict.free_units[0]?.item_id ?? "";
          }
          return next;
        });
        setMoveChecked((current) => {
          const next = { ...current };
          for (const conflict of found)
            next[conflict.booking_id] = conflict.free_units.length > 0;
          return next;
        });
        setError(null);
        return;
      }
      setError(
        (failure as { response?: { data?: { detail?: { message?: string } } } })
          ?.response?.data?.detail?.message ?? t("errors.generic"),
      );
    },
  });

  function update(unitId: string, patch: Partial<UnitReturn>) {
    setState((current) => ({
      ...current,
      [unitId]: { ...current[unitId], ...patch } as UnitReturn,
    }));
  }

  function buildPayload(): ReturnRequest {
    const payload: ReturnRequest = {
      units: units.map((unit) => {
        const entry = state[unit.id] as UnitReturn;
        return {
          unit_id: unit.id,
          condition: entry.condition,
          note: entry.note.trim() || undefined,
          service_reason:
            entry.condition === "NEEDS_REPAIR"
              ? entry.serviceReason.trim()
              : undefined,
          service_until:
            entry.condition === "NEEDS_REPAIR"
              ? wallTimeToIso(entry.serviceDate, entry.serviceTime, timezone)
              : undefined,
        };
      }),
      moves: conflicts
        .filter(
          (conflict) =>
            moveChecked[conflict.booking_id] && moveTo[conflict.booking_id],
        )
        .map((conflict) => ({
          line_id: conflict.line_id,
          from_item_id: conflict.item_id,
          to_item_id: moveTo[conflict.booking_id],
        })),
    };
    return payload;
  }

  const ready = units.every((unit) => {
    const entry = state[unit.id] as UnitReturn;
    if (entry.condition !== "NEEDS_REPAIR") return true;
    return Boolean(entry.serviceReason.trim() && entry.serviceDate);
  });

  return (
    <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
      <h2 className="border-b border-zinc-200 px-4 py-3.5 text-base font-semibold">
        {t("detail.returnTitle")}
      </h2>
      <div className="flex flex-col">
        {units.map((unit) => (
          <UnitReturnBlock
            key={unit.id}
            unit={unit}
            value={state[unit.id] as UnitReturn}
            onChange={(patch) => update(unit.id, patch)}
          />
        ))}
      </div>

      {conflicts.map((conflict) => (
        <div
          key={`${conflict.booking_id}-${conflict.item_id}`}
          role="alert"
          className="m-4 flex flex-col gap-2 rounded-lg bg-amber-50 p-3 text-sm text-amber-900"
        >
          <span className="font-semibold">
            {t("detail.blockConflict", {
              name: conflict.borrower_name,
              from: formatDateInZone(conflict.starts_at, timezone),
              to: formatDateInZone(conflict.ends_at, timezone),
            })}
          </span>
          {conflict.free_units.length ? (
            <>
              <label className="flex min-h-10 items-center gap-2.5">
                <input
                  type="checkbox"
                  className="h-5 w-5 accent-amber-700"
                  checked={moveChecked[conflict.booking_id] ?? false}
                  onChange={(event) =>
                    setMoveChecked((current) => ({
                      ...current,
                      [conflict.booking_id]: event.target.checked,
                    }))
                  }
                />
                {t("detail.moveBooking", { name: conflict.borrower_name })}
              </label>
              <NativeSelect
                label={t("detail.moveTo")}
                value={moveTo[conflict.booking_id] ?? ""}
                onChange={(event) =>
                  setMoveTo((current) => ({
                    ...current,
                    [conflict.booking_id]: event.target.value,
                  }))
                }
              >
                {conflict.free_units.map((unit) => (
                  <option key={unit.item_id} value={unit.item_id}>
                    {unit.name}
                    {unit.serial_number ? ` · ${unit.serial_number}` : ""}
                  </option>
                ))}
              </NativeSelect>
            </>
          ) : (
            <span className="text-xs">{t("detail.noFreeUnit")}</span>
          )}
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => {
              const end = isoToWall(conflict.suggested_until, timezone);
              const unit = units.find(
                (candidate) => candidate.item_id === conflict.item_id,
              );
              if (!unit) return;
              update(unit.id, {
                serviceDate: end.date,
                serviceTime: end.time,
              });
              setConflicts([]);
            }}
          >
            {t("detail.endBlockBefore", {
              date: formatDateInZone(conflict.suggested_until, timezone),
            })}
          </Button>
        </div>
      ))}

      {error ? (
        <p role="alert" className="mx-4 mb-2 mt-0 text-sm text-red-700">
          {error}
        </p>
      ) : null}

      <div className="flex justify-end border-t border-zinc-100 p-4">
        <Button
          type="button"
          variant="primary"
          disabled={!ready || !canWrite}
          isLoading={submit.isPending}
          onClick={() => submit.mutate(buildPayload())}
        >
          {t("detail.confirmReturn")}
        </Button>
      </div>
    </section>
  );
}

function UnitReturnBlock({
  unit,
  value,
  onChange,
}: {
  unit: UnitSchema;
  value: UnitReturn;
  onChange: (patch: Partial<UnitReturn>) => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <fieldset className="flex flex-col gap-2.5 border-b border-zinc-100 p-4 last:border-b-0">
      <legend className="text-sm font-semibold">{unit.item_name}</legend>
      <div className="flex flex-wrap gap-1.5">
        {(["GOOD", "DAMAGED", "NEEDS_REPAIR"] as const).map((condition) => {
          const active = value.condition === condition;
          return (
            <Button
              key={condition}
              type="button"
              variant={active ? "primary" : "outline"}
              className={
                active && condition === "NEEDS_REPAIR"
                  ? "rounded-full border-amber-700 bg-amber-50 text-amber-900 hover:bg-amber-100"
                  : "rounded-full"
              }
              onClick={() => onChange({ condition })}
            >
              {t(CONDITION_KEYS[condition])}
            </Button>
          );
        })}
      </div>
      {value.condition === "NEEDS_REPAIR" ? (
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-3">
          <div className="sm:col-span-1">
            <Input
              label={t("detail.whatHappened")}
              value={value.serviceReason}
              onChange={(event) =>
                onChange({ serviceReason: event.target.value })
              }
              required
            />
          </div>
          <div className="sm:col-span-2">
            <DateTimeField
              id={`service-${unit.id}`}
              label={t("detail.unavailableUntil")}
              date={value.serviceDate}
              time={value.serviceTime}
              onDateChange={(date) => onChange({ serviceDate: date })}
              onTimeChange={(time) => onChange({ serviceTime: time })}
            />
          </div>
        </div>
      ) : (
        <Input
          label={t("detail.note")}
          value={value.note}
          onChange={(event) => onChange({ note: event.target.value })}
        />
      )}
    </fieldset>
  );
}

function BookingFacts({ booking }: { booking: Booking }) {
  const { t } = useTranslation("rentals");
  const timezone = useOrganizationTimezone();
  return (
    <div className="flex flex-col gap-5">
      <Card className="flex flex-col gap-3 px-4 py-3.5">
        <h2 className="m-0 text-base font-semibold">{t("detail.summary")}</h2>
        <Fact label={t("detail.who")}>
          <span className="block">{booking.borrower_name}</span>
          {booking.borrower_email ? (
            <span className="block text-xs text-zinc-500">
              {booking.borrower_email}
            </span>
          ) : null}
        </Fact>
        <Fact label={t("detail.period")}>
          {formatDateInZone(booking.starts_at, timezone, {
            variant: "datetime",
          })}
          {" – "}
          {formatDateInZone(booking.ends_at, timezone, { variant: "datetime" })}
        </Fact>
        <Fact label={t("detail.equipment")}>
          {booking.lines.map((line) => (
            <span key={line.id} className="block">
              {line.item_id
                ? line.item_name
                : `${line.model} (${t("detail.anyUnit")})`}
              {(line.units?.length ?? 0) > 0 && line.item_id === null
                ? ` → ${(line.units ?? []).map((unit) => unit.item_name).join(", ")}`
                : ""}
            </span>
          ))}
        </Fact>
        {booking.note ? (
          <Fact label={t("detail.note")}>{booking.note}</Fact>
        ) : null}
      </Card>
      <Card className="flex flex-col gap-2 px-4 py-3.5">
        <h2 className="m-0 text-base font-semibold">{t("detail.history")}</h2>
        <HistoryRow
          label={t("detail.reserved")}
          when={booking.created_at}
          who={booking.created_by_name}
        />
        {booking.handed_out_at ? (
          <HistoryRow
            label={t("detail.handedOut")}
            when={booking.handed_out_at}
          />
        ) : null}
        {booking.returned_at ? (
          <HistoryRow label={t("detail.returned")} when={booking.returned_at} />
        ) : null}
        {!booking.handed_out_at && !booking.returned_at ? (
          <p className="m-0 text-xs text-zinc-500">
            {t("detail.notHandedOut")}
          </p>
        ) : null}
      </Card>
    </div>
  );
}

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-xs text-zinc-500">{label}</span>
      <span className="text-sm">{children}</span>
    </div>
  );
}

function HistoryRow({
  label,
  when,
  who,
}: {
  label: string;
  when: string;
  who?: string | null;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-sm">{label}</span>
      <span className="text-xs text-zinc-500">
        {formatDateTime(when)}
        {who ? ` · ${who}` : ""}
      </span>
    </div>
  );
}
