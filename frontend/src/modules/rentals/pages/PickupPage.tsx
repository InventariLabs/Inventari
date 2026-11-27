import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, CheckCircle2, CircleDashed, ScanLine } from "lucide-react";

import {
  Button,
  Card,
  Input,
  LoadingSpinner,
  NativeSelect,
  QueryError,
  ReadOnlyNotice,
  RecordNotFound,
  formatDateInZone,
  isNotFoundError,
  useCanWrite,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import type { AssetOption, Booking, CalendarBar } from "../api/rentals";
import { rentalsApi } from "../api/rentals";
import {
  useBooking,
  useCalendar,
  usePickupBooking,
  useRentalAssets,
} from "../hooks/useRentals";

type Slot = {
  key: string;
  lineId: string;
  itemId: string | null;
  model: string | null;
  label: string;
};

type TakenUnit = {
  item_name?: string;
  item_serial_number?: string | null;
  reasons?: { kind: string; label?: string | null }[];
};

const BAR_KIND_KEYS: Record<string, string> = {
  reserved: "calendar.legend.reserved",
  out: "calendar.legend.out",
  late: "calendar.legend.late",
  returned: "calendar.legend.returned",
  block: "calendar.legend.block",
  buffer: "calendar.legend.buffer",
};

function takenUnit(error: unknown): TakenUnit | null {
  const detail = (
    error as {
      response?: {
        data?: { detail?: { code?: string; units?: TakenUnit[] } };
      };
    }
  )?.response?.data?.detail;
  if (detail?.code !== "RENTAL_PICKUP_ASSET_TAKEN") return null;
  return detail.units?.[0] ?? null;
}

/**
 * The units another booking, block or buffer holds before this booking ends.
 * They are not a choice at pickup, and a scan of one is refused with what is in
 * the way. A hand-out before the booking starts takes its units from now on, so
 * the time up to the start counts as much as the window itself.
 */
function useUnitsBusyForHandOut(booking: Booking | undefined) {
  const [openedAt] = useState(() => new Date().toISOString());
  const startsAt = booking?.starts_at ?? "";
  const from =
    startsAt && new Date(startsAt) > new Date(openedAt) ? openedAt : startsAt;
  const { data, isError, isLoading } = useCalendar(
    from,
    booking?.ends_at ?? "",
    undefined,
    undefined,
    Boolean(booking),
  );
  const busy = useMemo(() => {
    const found = new Map<string, CalendarBar>();
    // While the calendar is loading or failed, the screen guesses nothing:
    // the confirm is where a taken unit is named with what stands in the way.
    if (!booking || isLoading || isError) return found;
    const starts = new Date(from).getTime();
    const ends = new Date(booking.ends_at).getTime();
    for (const group of data?.groups ?? []) {
      for (const unit of group.units) {
        const bar = (unit.bars ?? []).find(
          (entry) =>
            entry.kind !== "returned" &&
            entry.booking_id !== booking.id &&
            new Date(entry.starts_at).getTime() < ends &&
            starts < new Date(entry.ends_at).getTime(),
        );
        if (bar) found.set(unit.item_id, bar);
      }
    }
    return found;
  }, [booking, data, from, isError, isLoading]);
  return { busy, isError };
}

export default function PickupPage() {
  const { t } = useTranslation("rentals");
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const canWrite = useCanWrite("rentals");
  const booking = useBooking(id);
  const assets = useRentalAssets("");
  const pickup = usePickupBooking();
  const { busy, isError: calendarFailed } = useUnitsBusyForHandOut(
    booking.data,
  );
  const [picked, setPicked] = useState<Record<string, string>>({});
  const [code, setCode] = useState("");
  const [message, setMessage] = useState<{ ok: boolean; text: string } | null>(
    null,
  );

  useEffect(() => {
    setHeader({
      title: t("pickup.title"),
      backTo: id ? `/rentals/bookings/${id}` : "/rentals",
    });
  }, [setHeader, t, id]);

  const slots: Slot[] = useMemo(() => {
    if (!booking.data) return [];
    const list: Slot[] = [];
    for (const line of booking.data.lines) {
      if (line.item_id) {
        list.push({
          key: `${line.id}:0`,
          lineId: line.id,
          itemId: line.item_id,
          model: null,
          label: line.item_name ?? "",
        });
        continue;
      }
      for (let index = 0; index < line.quantity; index += 1) {
        list.push({
          key: `${line.id}:${index}`,
          lineId: line.id,
          itemId: null,
          model: line.model ?? null,
          label: `${line.model} · ${t("pickup.anyUnit")}`,
        });
      }
    }
    return list;
  }, [booking.data, t]);

  const totalSlots = booking.isLoading ? 0 : slots.length;
  const pickedCount = slots.filter((slot) => picked[slot.key]).length;
  const ready = totalSlots > 0 && pickedCount === totalSlots;
  const assetsById = useMemo(
    () => new Map((assets.data ?? []).map((asset) => [asset.id, asset])),
    [assets.data],
  );
  const busyReason = (bar: CalendarBar) =>
    bar.label || t(BAR_KIND_KEYS[bar.kind] ?? "calendar.legend.block");

  function assignSlot(slot: Slot, itemId: string, viaScan: boolean) {
    setPicked((current) => ({ ...current, [slot.key]: itemId }));
    const asset = assetsById.get(itemId);
    if (viaScan) {
      setMessage({
        ok: true,
        text:
          slot.model !== null
            ? t("pickup.scanResolvedModel", {
                name: asset?.name ?? itemId,
                model: slot.model,
              })
            : t("pickup.scanMatched", { name: asset?.name ?? itemId }),
      });
    }
  }

  async function scan(raw: string) {
    const value = raw.trim();
    if (!value) return;
    setCode("");
    try {
      const matches = await rentalsApi.assets({ search: value });
      const exact =
        matches.find(
          (asset) =>
            asset.barcode === value ||
            asset.serial_number === value ||
            asset.asset_tag === value,
        ) ?? matches[0];
      if (!exact) {
        setMessage({ ok: false, text: t("pickup.nothingFound") });
        return;
      }
      if (Object.values(picked).includes(exact.id)) {
        setMessage({
          ok: false,
          text: t("pickup.alreadyPicked", { name: exact.name }),
        });
        return;
      }
      const slot =
        slots.find(
          (entry) =>
            entry.itemId === exact.id &&
            !picked[entry.key] &&
            entry.model === null,
        ) ??
        slots.find(
          (entry) => entry.model === exact.model && !picked[entry.key],
        );
      if (!slot) {
        setMessage({
          ok: false,
          text: t("pickup.notOnThisBooking", { name: exact.name }),
        });
        return;
      }
      const taken = busy.get(exact.id);
      if (taken) {
        setMessage({
          ok: false,
          text: t("pickup.busyUnit", {
            name: `${exact.name}${
              exact.serial_number ? ` · ${exact.serial_number}` : ""
            }`,
            reason: busyReason(taken),
          }),
        });
        return;
      }
      assignSlot(slot, exact.id, true);
    } catch {
      setMessage({ ok: false, text: t("pickup.nothingFound") });
    }
  }

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

  const optionsFor = (slot: Slot, selected: string): AssetOption[] => {
    if (slot.itemId) {
      return (assets.data ?? []).filter((asset) => asset.id === slot.itemId);
    }
    const taken = new Set(Object.values(picked));
    return (assets.data ?? []).filter(
      (asset) =>
        asset.model === slot.model &&
        (asset.id === selected || !taken.has(asset.id)) &&
        !busy.has(asset.id) &&
        !slots.some(
          (entry) => entry.model === null && entry.itemId === asset.id,
        ),
    );
  };

  return (
    <div className="mx-auto flex w-full max-w-xl flex-col gap-4">
      <ReadOnlyNotice module="rentals" />
      {assets.isError || calendarFailed ? (
        <p
          role="alert"
          className="m-0 rounded-lg bg-red-50 p-3 text-sm text-red-800"
        >
          {t("errors.loadChoices")}
        </p>
      ) : null}
      <Link
        to={id ? `/rentals/bookings/${id}` : "/rentals"}
        className="inline-flex min-h-11 items-center gap-1 text-sm"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("pickup.back")}
      </Link>

      <Card className="flex flex-col gap-0.5 px-4 py-3">
        <span className="text-base font-semibold">{t("pickup.title")}</span>
        <span className="text-sm text-zinc-500">
          {data.borrower_name} · {formatDateInZone(data.ends_at, timezone)}{" "}
          {formatDateInZone(data.ends_at, timezone, { variant: "time" })}
        </span>
      </Card>

      {message ? (
        <div
          role="status"
          className={`flex items-start gap-2.5 rounded-xl px-3.5 py-3 text-sm ${
            message.ok
              ? "bg-success-50 text-success-900"
              : "bg-red-50 text-red-800"
          }`}
        >
          <span className="font-semibold">{message.text}</span>
        </div>
      ) : null}

      <PickupSlots
        slots={slots}
        picked={picked}
        pickedCount={pickedCount}
        totalSlots={totalSlots}
        assetsById={assetsById}
        optionsFor={optionsFor}
        onAssign={assignSlot}
      />
      <ScanCard code={code} onCode={setCode} onScan={scan} />
      <ConfirmBar
        ready={ready}
        canWrite={canWrite}
        pending={pickup.isPending}
        missing={totalSlots - pickedCount}
        onConfirm={() =>
          pickup.mutate(
            {
              id: data.id,
              data: {
                item_ids: slots
                  .map((slot) => picked[slot.key])
                  .filter((value): value is string => Boolean(value)),
              },
            },
            {
              onSuccess: () => navigate(`/rentals/bookings/${data.id}`),
              onError: (failure: unknown) => {
                const taken = takenUnit(failure);
                if (taken) {
                  const reason = taken.reasons?.[0];
                  setMessage({
                    ok: false,
                    text: t("pickup.assetTaken", {
                      name: `${taken.item_name ?? ""}${
                        taken.item_serial_number
                          ? ` · ${taken.item_serial_number}`
                          : ""
                      }`,
                      reason:
                        reason?.label ||
                        (reason?.kind
                          ? t(BAR_KIND_KEYS[reason.kind] ?? "errors.generic")
                          : t("errors.generic")),
                    }),
                  });
                  return;
                }
                setMessage({
                  ok: false,
                  text:
                    (
                      failure as {
                        response?: {
                          data?: { detail?: { message?: string } };
                        };
                      }
                    )?.response?.data?.detail?.message ?? t("errors.generic"),
                });
              },
            },
          )
        }
      />
    </div>
  );
}

function PickupSlots({
  slots,
  picked,
  pickedCount,
  totalSlots,
  assetsById,
  optionsFor,
  onAssign,
}: {
  slots: Slot[];
  picked: Record<string, string>;
  pickedCount: number;
  totalSlots: number;
  assetsById: Map<string, AssetOption>;
  optionsFor: (slot: Slot, selected: string) => AssetOption[];
  onAssign: (slot: Slot, itemId: string, viaScan: boolean) => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <Card className="overflow-hidden">
      <h2 className="m-0 border-b border-zinc-200 px-3.5 py-3 text-sm font-semibold">
        {t("pickup.toHandOut", {
          count: totalSlots,
          picked: pickedCount,
          total: totalSlots,
        })}
      </h2>
      {slots.map((slot) => {
        const value = picked[slot.key] ?? "";
        const asset = value ? assetsById.get(value) : undefined;
        return (
          <div
            key={slot.key}
            className="flex flex-wrap items-center gap-2.5 border-b border-zinc-100 px-3.5 py-3 last:border-b-0"
          >
            {asset ? (
              <CheckCircle2 className="h-5 w-5 flex-none text-success-700" />
            ) : (
              <CircleDashed className="h-5 w-5 flex-none text-zinc-400" />
            )}
            <div className="min-w-0 flex-1">
              <span className="block text-sm font-medium">
                {asset?.name ?? slot.label}
              </span>
              <span className="block text-xs text-zinc-500">
                {slot.itemId
                  ? t("pickup.specificUnit")
                  : t("pickup.anyUnitLine")}
              </span>
            </div>
            {slot.itemId && value ? null : (
              <div className="w-full sm:w-56">
                <NativeSelect
                  aria-label={t("pickup.choose", { name: slot.label })}
                  value={value}
                  onChange={(event) =>
                    onAssign(slot, event.target.value, false)
                  }
                >
                  <option value="">{t("pickup.chooseUnit")}</option>
                  {optionsFor(slot, value).map((option) => (
                    <option key={option.id} value={option.id}>
                      {option.name}
                      {option.serial_number ? ` · ${option.serial_number}` : ""}
                    </option>
                  ))}
                </NativeSelect>
              </div>
            )}
          </div>
        );
      })}
    </Card>
  );
}

function ScanCard({
  code,
  onCode,
  onScan,
}: {
  code: string;
  onCode: (value: string) => void;
  onScan: (value: string) => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <Card className="flex flex-col gap-2 px-3.5 py-3">
      <div className="flex gap-2">
        <Input
          id="pickup-scan"
          label={t("pickup.scan")}
          value={code}
          onChange={(event) => onCode(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              onScan(code);
            }
          }}
          placeholder={t("pickup.scanPlaceholder")}
        />
        <Button type="button" variant="outline" onClick={() => onScan(code)}>
          <ScanLine className="mr-1.5 h-4 w-4" />
          {t("pickup.scanButton")}
        </Button>
      </div>
      <p className="m-0 text-xs text-zinc-500">{t("pickup.scanHint")}</p>
    </Card>
  );
}

function ConfirmBar({
  ready,
  canWrite,
  pending,
  missing,
  onConfirm,
}: {
  ready: boolean;
  canWrite: boolean;
  pending: boolean;
  missing: number;
  onConfirm: () => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <div className="sticky bottom-[calc(var(--mobile-nav-height)+env(safe-area-inset-bottom,0px)+0.5rem)] z-[var(--z-sticky)] rounded-xl border border-zinc-200 bg-white p-3 md:bottom-2">
      <Button
        type="button"
        variant="primary"
        className="w-full"
        disabled={!ready || !canWrite}
        isLoading={pending}
        onClick={onConfirm}
      >
        {ready ? t("pickup.confirm") : t("pickup.missing", { count: missing })}
      </Button>
    </div>
  );
}
