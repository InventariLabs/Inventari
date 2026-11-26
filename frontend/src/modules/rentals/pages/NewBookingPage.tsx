import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
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

import type { BookingLineIn } from "../api/rentals";
import {
  BorrowerSection,
  LinesSection,
  WindowSection,
  type LineDraft,
  type Who,
} from "../components/BookingFormSections";
import {
  useBookingCheck,
  useCreateBooking,
  useMembers,
  useModels,
  usePartners,
  useRentalAssets,
} from "../hooks/useRentals";
import { isoToWall, wallTimeToIso } from "../lib/datetime";

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

export default function NewBookingPage() {
  const { t } = useTranslation("rentals");
  const navigate = useNavigate();
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const canWrite = useCanWrite("rentals");
  const models = useModels();
  const assets = useRentalAssets("");
  const partners = usePartners();
  const members = useMembers();
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
    { key: nextKey++, kind: "model", model: "", itemId: "", quantity: 1 },
  ]);

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

  const startsAt = wallTimeToIso(startDate, startTime, timezone);
  const endsAt = wallTimeToIso(endDate, endTime, timezone);
  const payloadLines: BookingLineIn[] = useMemo(
    () =>
      lines
        .filter((line) =>
          line.kind === "model" ? Boolean(line.model) : Boolean(line.itemId),
        )
        .map((line) =>
          line.kind === "model"
            ? { model: line.model, quantity: line.quantity }
            : { item_id: line.itemId, quantity: 1 },
        ),
    [lines],
  );
  const payloadKey = JSON.stringify(payloadLines);
  const borrowerReady =
    (who === "partner" && Boolean(partnerId)) ||
    (who === "member" && Boolean(memberId)) ||
    (who === "external" && name.trim().length > 0);
  const windowReady = new Date(endsAt) > new Date(startsAt);

  useEffect(() => {
    if (!borrowerReady || !windowReady || payloadLines.length === 0) return;
    const timer = window.setTimeout(() => {
      check.mutate({
        starts_at: startsAt,
        ends_at: endsAt,
        lines: payloadLines,
      });
    }, 350);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [startsAt, endsAt, payloadKey, borrowerReady, windowReady]);

  const optionsFailed =
    models.isError || assets.isError || partners.isError || members.isError;
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
      <SheetBody>
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
