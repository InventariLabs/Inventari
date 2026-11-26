import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import { Button, Input, NativeSelect, formatDate } from "@/module-sdk";

import type { AssetOption, LineCheck, ModelOption } from "../api/rentals";
import { DateTimeField } from "./DateTimeField";

export type Who = "partner" | "member" | "external";

const WHO_KEYS: Record<Who, string> = {
  partner: "form.whoKinds.partner",
  member: "form.whoKinds.member",
  external: "form.whoKinds.external",
};

export type LineDraft = {
  key: number;
  kind: "model" | "asset";
  model: string;
  itemId: string;
  quantity: number;
};

export type BorrowerOption = { id: string; name: string };

export function BorrowerSection({
  who,
  onWho,
  partnerId,
  onPartnerId,
  memberId,
  onMemberId,
  name,
  onName,
  email,
  onEmail,
  partners,
  members,
}: {
  who: Who;
  onWho: (value: Who) => void;
  partnerId: string;
  onPartnerId: (value: string) => void;
  memberId: string;
  onMemberId: (value: string) => void;
  name: string;
  onName: (value: string) => void;
  email: string;
  onEmail: (value: string) => void;
  partners: BorrowerOption[];
  members: BorrowerOption[];
}) {
  const { t } = useTranslation("rentals");
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="mb-2 text-sm font-semibold">{t("form.who")}</legend>
      <div className="flex flex-wrap gap-1.5">
        {(["partner", "member", "external"] as Who[]).map((kind) => (
          <Button
            key={kind}
            type="button"
            variant={who === kind ? "primary" : "outline"}
            className="rounded-full"
            onClick={() => onWho(kind)}
          >
            {t(WHO_KEYS[kind])}
          </Button>
        ))}
      </div>
      {who === "partner" ? (
        <NativeSelect
          label={t("form.partner")}
          value={partnerId}
          onChange={(event) => onPartnerId(event.target.value)}
        >
          <option value="">{t("form.choosePartner")}</option>
          {partners.map((partner) => (
            <option key={partner.id} value={partner.id}>
              {partner.name}
            </option>
          ))}
        </NativeSelect>
      ) : who === "member" ? (
        <NativeSelect
          label={t("form.member")}
          value={memberId}
          onChange={(event) => onMemberId(event.target.value)}
        >
          <option value="">{t("form.chooseMember")}</option>
          {members.map((member) => (
            <option key={member.id} value={member.id}>
              {member.name}
            </option>
          ))}
        </NativeSelect>
      ) : (
        <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2">
          <Input
            label={t("form.name")}
            value={name}
            onChange={(event) => onName(event.target.value)}
            required
          />
          <Input
            label={t("form.email")}
            type="email"
            value={email}
            onChange={(event) => onEmail(event.target.value)}
          />
        </div>
      )}
    </fieldset>
  );
}

export function WindowSection({
  startDate,
  onStartDate,
  startTime,
  onStartTime,
  endDate,
  onEndDate,
  endTime,
  onEndTime,
  windowReady,
}: {
  startDate: string;
  onStartDate: (value: string) => void;
  startTime: string;
  onStartTime: (value: string) => void;
  endDate: string;
  onEndDate: (value: string) => void;
  endTime: string;
  onEndTime: (value: string) => void;
  windowReady: boolean;
}) {
  const { t } = useTranslation("rentals");
  return (
    <fieldset className="flex flex-col gap-2.5">
      <legend className="mb-2 text-sm font-semibold">{t("form.when")}</legend>
      <div className="grid grid-cols-1 items-end gap-3 sm:grid-cols-2">
        <DateTimeField
          id="rental-start"
          label={t("form.pickup")}
          date={startDate}
          time={startTime}
          onDateChange={onStartDate}
          onTimeChange={onStartTime}
        />
        <DateTimeField
          id="rental-end"
          label={t("form.return")}
          date={endDate}
          time={endTime}
          onDateChange={onEndDate}
          onTimeChange={onEndTime}
          error={!windowReady ? t("form.windowOrder") : undefined}
        />
      </div>
      <p className="text-xs text-zinc-500">{t("form.bufferHint")}</p>
    </fieldset>
  );
}

export function LinesSection({
  lines,
  models,
  assets,
  checks,
  onUpdate,
  onAdd,
  onRemove,
  onMoveWindow,
}: {
  lines: LineDraft[];
  models: ModelOption[];
  assets: AssetOption[];
  checks: LineCheck[];
  onUpdate: (key: number, patch: Partial<LineDraft>) => void;
  onAdd: () => void;
  onRemove: (key: number) => void;
  onMoveWindow: (startsAt: string, endsAt: string) => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <fieldset className="flex flex-col gap-3">
      <legend className="mb-2 text-sm font-semibold">{t("form.what")}</legend>
      {lines.map((line, index) => (
        <LineEditor
          key={line.key}
          line={line}
          check={checks[index]}
          models={models}
          assets={assets}
          onUpdate={(patch) => onUpdate(line.key, patch)}
          onRemove={lines.length > 1 ? () => onRemove(line.key) : undefined}
          onMoveWindow={onMoveWindow}
          canAdd={line.kind === "model"}
        />
      ))}
      <Button
        type="button"
        variant="outline"
        className="w-full border-dashed"
        onClick={onAdd}
      >
        <Plus className="mr-1.5 h-4 w-4" />
        {t("form.addLine")}
      </Button>
    </fieldset>
  );
}

function LineEditor({
  line,
  check,
  models,
  assets,
  onUpdate,
  onRemove,
  onMoveWindow,
  canAdd,
}: {
  line: LineDraft;
  check?: LineCheck;
  models: ModelOption[];
  assets: AssetOption[];
  onUpdate: (patch: Partial<LineDraft>) => void;
  onRemove?: () => void;
  onMoveWindow: (startsAt: string, endsAt: string) => void;
  canAdd: boolean;
}) {
  const { t } = useTranslation("rentals");
  const conflicts = check && !check.ok ? (check.conflicts ?? []) : [];
  const nearest = check?.nearest_window;
  return (
    <div
      className={`rounded-xl border ${
        conflicts.length ? "border-red-300" : "border-zinc-200"
      }`}
    >
      <div className="flex flex-wrap items-center gap-3 px-3.5 py-3">
        <div className="min-w-0 flex-1 basis-48">
          <div className="mb-1 flex gap-1.5">
            <Button
              type="button"
              size="sm"
              variant={line.kind === "model" ? "primary" : "outline"}
              onClick={() => onUpdate({ kind: "model" })}
            >
              {t("form.modelLine")}
            </Button>
            <Button
              type="button"
              size="sm"
              variant={line.kind === "asset" ? "primary" : "outline"}
              onClick={() => onUpdate({ kind: "asset" })}
            >
              {t("form.assetLine")}
            </Button>
          </div>
          {line.kind === "model" ? (
            <NativeSelect
              aria-label={t("form.model")}
              value={line.model}
              onChange={(event) => onUpdate({ model: event.target.value })}
            >
              <option value="">{t("form.chooseModel")}</option>
              {models.map((model) => (
                <option key={model.model} value={model.model}>
                  {model.model} ·{" "}
                  {t("form.units", { count: model.total_units })}
                </option>
              ))}
            </NativeSelect>
          ) : (
            <NativeSelect
              aria-label={t("form.asset")}
              value={line.itemId}
              onChange={(event) => onUpdate({ itemId: event.target.value })}
            >
              <option value="">{t("form.chooseAsset")}</option>
              {assets.map((asset) => (
                <option key={asset.id} value={asset.id}>
                  {asset.name}
                  {asset.serial_number ? ` · ${asset.serial_number}` : ""}
                </option>
              ))}
            </NativeSelect>
          )}
        </div>
        {canAdd ? (
          <div className="flex items-center gap-1">
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("form.less")}
              onClick={() =>
                onUpdate({ quantity: Math.max(1, line.quantity - 1) })
              }
            >
              −
            </Button>
            <span className="w-10 text-center text-sm">{line.quantity}</span>
            <Button
              type="button"
              variant="outline"
              size="icon"
              aria-label={t("form.more")}
              onClick={() => onUpdate({ quantity: line.quantity + 1 })}
            >
              +
            </Button>
          </div>
        ) : check?.ok ? (
          <span className="rounded-full bg-success-50 px-2.5 py-1 text-xs font-semibold text-success-800">
            {t("form.fits")}
          </span>
        ) : null}
        {onRemove ? (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("form.removeLine")}
            onClick={onRemove}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        ) : null}
      </div>
      {conflicts.length ? (
        <div
          role="alert"
          className="flex flex-col gap-2.5 bg-red-50 px-3.5 py-3"
        >
          <span className="text-sm font-semibold text-red-800">
            {t("form.doesNotFit", {
              available: check?.available ?? 0,
              requested: check?.requested ?? line.quantity,
            })}
          </span>
          <ul className="m-0 flex list-disc flex-col gap-0.5 pl-4 text-xs text-red-800">
            {conflicts.slice(0, 6).map((conflict, conflictIndex) => (
              <li key={`${conflict.kind}-${conflictIndex}`}>
                {conflict.item_name ? `${conflict.item_name}: ` : ""}
                {conflict.kind === "block"
                  ? t("form.blocked", {
                      reason: conflict.reason ?? conflict.label,
                      date: conflict.ends_at
                        ? formatDate(conflict.ends_at)
                        : "",
                    })
                  : conflict.kind === "model_booking"
                    ? t("form.heldBy", {
                        name: conflict.label,
                        count: conflict.reason ?? "",
                      })
                    : t("form.busy", {
                        name: conflict.label,
                        from: conflict.starts_at
                          ? formatDate(conflict.starts_at)
                          : "",
                        to: conflict.ends_at
                          ? formatDate(conflict.ends_at)
                          : "",
                      })}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            {line.kind === "model" && (check?.max_quantity ?? 0) > 0 ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onUpdate({ quantity: check?.max_quantity ?? 1 })}
              >
                {t("form.reduceTo", { count: check?.max_quantity ?? 1 })}
              </Button>
            ) : null}
            {nearest ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                onClick={() => onMoveWindow(nearest.starts_at, nearest.ends_at)}
              >
                {t("form.moveTo", {
                  from: formatDate(nearest.starts_at),
                  to: formatDate(nearest.ends_at),
                })}
              </Button>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
