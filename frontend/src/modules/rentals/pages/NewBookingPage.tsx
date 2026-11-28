import { useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";

import {
  Button,
  Input,
  ReadOnlyNotice,
  Sheet,
  SheetBody,
  SheetFooter,
  SheetHeader,
  useCanWrite,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import type { Booking, BookingLineIn } from "../api/rentals";
import {
  BorrowerSection,
  LinesSection,
  WindowSection,
  type LineDraft,
  type Who,
} from "../components/BookingFormSections";
import {
  useBooking,
  useBookingCheck,
  useCreateBooking,
  useKits,
  useMembers,
  useModels,
  usePartners,
  useRentalAssets,
} from "../hooks/useRentals";
import { addDays, isoDate, isoToWall, wallTimeToIso } from "../lib/datetime";

let nextKey = 1;

function todayPlus(days: number): string {
  const value = new Date();
  value.setDate(value.getDate() + days);
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${value.getFullYear()}-${pad(value.getMonth() + 1)}-${pad(value.getDate())}`;
}

function footerMessage(
  t: (key: string, options?: Record<string, unknown>) => string,
  state: {
    borrowerReady: boolean;
    windowReady: boolean;
    failingLine?: { label: string };
    checkFailed: boolean;
    checking: boolean;
  },
): string {
  if (!state.borrowerReady) return t("form.needBorrower");
  if (!state.windowReady) return t("form.needWindow");
  if (state.failingLine)
    return t("form.fixLine", { line: state.failingLine.label });
  if (state.checkFailed) return t("errors.checkFailed");
  if (state.checking) return t("form.checking");
  return "";
}

/** The borrower kind of a booking, in the form's own vocabulary. */
function whoOf(booking: Booking): Who {
  if (booking.borrower_kind === "partner") return "partner";
  if (booking.borrower_kind === "user") return "member";
  return "external";
}

/**
 * A booking's lines as drafts: a kit's member lines collapse back into the
 * one kit line the sheet submitted.
 */
function linesOf(booking: Booking): LineDraft[] {
  const result: LineDraft[] = [];
  const seenKits = new Set<string>();
  for (const line of booking.lines) {
    if (line.kit_id) {
      if (seenKits.has(line.kit_id)) continue;
      seenKits.add(line.kit_id);
      result.push({
        key: nextKey++,
        kind: "kit",
        model: "",
        itemId: "",
        kitId: line.kit_id,
        kitName: line.kit_name ?? undefined,
        quantity: 1,
      });
    } else if (line.item_id) {
      result.push({
        key: nextKey++,
        kind: "asset",
        model: "",
        itemId: line.item_id,
        kitId: "",
        quantity: 1,
      });
    } else if (line.model) {
      result.push({
        key: nextKey++,
        kind: "model",
        model: line.model,
        itemId: "",
        kitId: "",
        quantity: line.quantity,
      });
    }
  }
  return result;
}

/** One week on from the booking, or tomorrow when that week has already passed. */
function bookAgainWindow(
  booking: Booking,
  timezone?: string,
): {
  startDate: string;
  startTime: string;
  endDate: string;
  endTime: string;
} {
  const start = isoToWall(booking.starts_at, timezone);
  const end = isoToWall(booking.ends_at, timezone);
  const shiftedStart = addDays(start.date, 7);
  const shiftedStartAt = wallTimeToIso(shiftedStart, start.time, timezone);
  if (new Date(shiftedStartAt).getTime() > Date.now()) {
    return {
      startDate: shiftedStart,
      startTime: start.time,
      endDate: addDays(end.date, 7),
      endTime: end.time,
    };
  }
  const duration =
    new Date(booking.ends_at).getTime() - new Date(booking.starts_at).getTime();
  const tomorrow = addDays(isoDate(new Date().toISOString(), timezone), 1);
  const nextStart = wallTimeToIso(tomorrow, start.time, timezone);
  const nextEnd = isoToWall(
    new Date(new Date(nextStart).getTime() + duration).toISOString(),
    timezone,
  );
  return {
    startDate: tomorrow,
    startTime: start.time,
    endDate: nextEnd.date,
    endTime: nextEnd.time,
  };
}

/** Why the form is already filled: the booking it repeats. */
function BookAgainHint({ booking }: { booking?: Booking }) {
  const { t } = useTranslation("rentals");
  if (!booking) return null;
  return (
    <p className="m-0 rounded-lg bg-blue-50 p-3 text-sm text-blue-800">
      {t("form.bookAgainHint", { name: booking.borrower_name })}
    </p>
  );
}

export default function NewBookingPage() {
  const { t } = useTranslation("rentals");
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const fromId = searchParams.get("from") ?? undefined;
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const canWrite = useCanWrite("rentals");
  const models = useModels();
  const assets = useRentalAssets("");
  const kits = useKits();
  const partners = usePartners();
  const members = useMembers();
  const source = useBooking(fromId);
  const check = useBookingCheck();
  const create = useCreateBooking();

  const [who, setWho] = useState<Who>("partner");
  const [partnerId, setPartnerId] = useState("");
  const [memberId, setMemberId] = useState("");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [note, setNote] = useState("");
  const [startDate, setStartDate] = useState(todayPlus(1));
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState(todayPlus(3));
  const [endTime, setEndTime] = useState("16:00");
  const [lines, setLines] = useState<LineDraft[]>([
    {
      key: nextKey++,
      kind: "model",
      model: "",
      itemId: "",
      kitId: "",
      quantity: 1,
    },
  ]);
  // "Book again" fills the form once, when the source booking arrives. The
  // guard keeps a later refetch from overwriting what the reader typed.
  const prefilledFrom = useRef<string | null>(null);

  useEffect(() => {
    setHeader({ title: t("form.newTitle"), backTo: "/rentals" });
  }, [setHeader, t]);

  useEffect(() => {
    if (!models.data?.length) return;
    setLines((current) =>
      current.map((line) =>
        line.kind === "model" && !line.model
          ? { ...line, model: models.data![0].model }
          : line,
      ),
    );
  }, [models.data]);

  useEffect(() => {
    const booking = source.data;
    if (!fromId || !booking || prefilledFrom.current === fromId) return;
    prefilledFrom.current = fromId;
    setWho(whoOf(booking));
    setPartnerId(booking.borrower_partner_id ?? "");
    setMemberId(booking.borrower_user_id ?? "");
    setName(booking.borrower_name);
    setEmail(booking.borrower_email ?? "");
    setNote(booking.note ?? "");
    const window = bookAgainWindow(booking, timezone);
    setStartDate(window.startDate);
    setStartTime(window.startTime);
    setEndDate(window.endDate);
    setEndTime(window.endTime);
    const prefilled = linesOf(booking);
    if (prefilled.length) setLines(prefilled);
  }, [fromId, source.data, timezone]);

  const startsAt = wallTimeToIso(startDate, startTime, timezone);
  const endsAt = wallTimeToIso(endDate, endTime, timezone);
  const payloadLines: BookingLineIn[] = useMemo(
    () =>
      lines.flatMap((line): BookingLineIn[] => {
        if (line.kind === "model") {
          return line.model
            ? [{ model: line.model, quantity: line.quantity }]
            : [];
        }
        if (line.kind === "asset") {
          return line.itemId ? [{ item_id: line.itemId, quantity: 1 }] : [];
        }
        return line.kitId ? [{ kit_id: line.kitId }] : [];
      }),
    [lines],
  );
  const payloadKey = JSON.stringify(payloadLines);
  const borrowerReady =
    (who === "partner" && Boolean(partnerId)) ||
    (who === "member" && Boolean(memberId)) ||
    (who === "external" && name.trim().length > 0);
  const windowReady = new Date(endsAt) > new Date(startsAt);

  // React Query keeps `mutate` stable, so the debounced check can list it
  // without re-firing on every render.
  const checkAvailability = check.mutate;
  useEffect(() => {
    if (!borrowerReady || !windowReady || payloadLines.length === 0) return;
    const timer = window.setTimeout(() => {
      checkAvailability({
        starts_at: startsAt,
        ends_at: endsAt,
        lines: payloadLines,
      });
    }, 350);
    return () => window.clearTimeout(timer);
  }, [
    startsAt,
    endsAt,
    payloadKey,
    borrowerReady,
    windowReady,
    checkAvailability,
    payloadLines,
  ]);

  const optionsFailed =
    models.isError ||
    assets.isError ||
    kits.isError ||
    partners.isError ||
    members.isError;
  const checkFailed = check.isError;
  const checks = check.data?.lines ?? [];
  const failingLine = checks.find((line) => !line.ok);
  const canSave =
    canWrite &&
    borrowerReady &&
    windowReady &&
    payloadLines.length > 0 &&
    !check.isPending &&
    Boolean(check.data?.ok);

  function updateLine(key: number, patch: Partial<LineDraft>) {
    setLines((current) =>
      current.map((line) => (line.key === key ? { ...line, ...patch } : line)),
    );
  }

  function moveWindow(start: string, end: string) {
    const nextStart = isoToWall(start, timezone);
    const nextEnd = isoToWall(end, timezone);
    setStartDate(nextStart.date);
    setStartTime(nextStart.time);
    setEndDate(nextEnd.date);
    setEndTime(nextEnd.time);
  }

  function save() {
    if (!canSave) return;
    create.mutate(
      {
        starts_at: startsAt,
        ends_at: endsAt,
        note: note.trim() || undefined,
        borrower_partner_id: who === "partner" ? partnerId : undefined,
        borrower_user_id: who === "member" ? memberId : undefined,
        borrower_name: who === "external" ? name.trim() : undefined,
        borrower_email:
          who === "external" ? email.trim() || undefined : undefined,
        lines: payloadLines,
      },
      { onSuccess: () => navigate("/rentals") },
    );
  }

  return (
    <Sheet
      open
      onClose={() => navigate("/rentals")}
      maxWidth="xl"
      aria-label={t("form.newTitle")}
    >
      <SheetHeader
        title={t("form.newTitle")}
        onClose={() => navigate("/rentals")}
      />
      <SheetBody className="p-5">
        <div className="flex flex-col gap-6">
          <ReadOnlyNotice module="rentals" />
          {optionsFailed ? (
            <p
              role="alert"
              className="m-0 rounded-lg bg-red-50 p-3 text-sm text-red-800"
            >
              {t("errors.loadChoices")}
            </p>
          ) : null}
          <BookAgainHint booking={source.data} />
          <BorrowerSection
            who={who}
            onWho={setWho}
            partnerId={partnerId}
            onPartnerId={setPartnerId}
            memberId={memberId}
            onMemberId={setMemberId}
            name={name}
            onName={setName}
            email={email}
            onEmail={setEmail}
            partners={partners.data ?? []}
            members={members.data ?? []}
          />
          <WindowSection
            startDate={startDate}
            onStartDate={setStartDate}
            startTime={startTime}
            onStartTime={setStartTime}
            endDate={endDate}
            onEndDate={setEndDate}
            endTime={endTime}
            onEndTime={setEndTime}
            windowReady={windowReady}
          />
          <LinesSection
            lines={lines}
            models={models.data ?? []}
            assets={assets.data ?? []}
            kits={kits.data ?? []}
            checks={checks}
            onUpdate={updateLine}
            onMoveWindow={moveWindow}
            onAdd={() =>
              setLines((current) => [
                ...current,
                {
                  key: nextKey++,
                  kind: models.data?.length ? "model" : "asset",
                  model: models.data?.[0]?.model ?? "",
                  itemId: "",
                  kitId: "",
                  quantity: 1,
                },
              ])
            }
            onRemove={(key) =>
              setLines((current) => current.filter((line) => line.key !== key))
            }
          />
          <Input
            label={t("form.note")}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("form.notePlaceholder")}
          />
        </div>
      </SheetBody>
      <SheetFooter>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <span className="mr-auto text-xs text-zinc-500">
            {footerMessage(t, {
              borrowerReady,
              windowReady,
              failingLine,
              checkFailed,
              checking: check.isPending,
            })}
          </span>
          <Button
            type="button"
            variant="ghost"
            onClick={() => navigate("/rentals")}
          >
            {t("form.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!canSave}
            isLoading={create.isPending}
            onClick={save}
          >
            {t("form.save")}
          </Button>
        </div>
      </SheetFooter>
    </Sheet>
  );
}
