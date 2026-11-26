import { useEffect, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTranslation } from "react-i18next";
import { Plus, Trash2 } from "lucide-react";

import {
  Button,
  Input,
  NativeSelect,
  QueryResult,
  ReadOnlyNotice,
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  formatDate,
  useCanWrite,
  useModulePageHeader,
  useOrganizationTimezone,
} from "@/module-sdk";

import { rentalsApi } from "../api/rentals";
import { BufferRulesSection } from "../components/BufferRulesSection";
import { DateTimeField } from "../components/DateTimeField";
import { RentalsTabs } from "../components/RentalsTabs";
import {
  useBlocks,
  useBufferRules,
  useCategories,
  useDeleteBlock,
  useDeleteBufferRule,
  useModels,
  useRentalAssets,
  useSetBufferRule,
} from "../hooks/useRentals";
import { queryKeys } from "../queryKeys";
import { wallTimeToIso } from "../lib/datetime";

const SOURCE_KEYS: Record<string, string> = {
  MANUAL: "blocks.source.manual",
  SERVICE: "blocks.source.service",
};

type BlockConflict = {
  borrower_name: string;
  starts_at: string;
  ends_at: string;
};

function conflictsOf(error: unknown): BlockConflict[] {
  const detail = (
    error as {
      response?: { data?: { detail?: { conflicts?: BlockConflict[] } } };
    }
  )?.response?.data?.detail;
  return detail?.conflicts ?? [];
}

export default function BlocksPage() {
  const { t } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();
  const timezone = useOrganizationTimezone();
  const canWrite = useCanWrite("rentals");
  const qc = useQueryClient();
  const assets = useRentalAssets("");
  const models = useModels();
  const categories = useCategories();
  const blocks = useBlocks({ limit: 100 });
  const rules = useBufferRules();
  const deleteBlock = useDeleteBlock();
  const setRule = useSetBufferRule();
  const deleteRule = useDeleteBufferRule();
  const optionsFailed = assets.isError || models.isError || categories.isError;
  const [open, setOpen] = useState(false);

  useEffect(() => {
    setHeader({
      title: t("title"),
      actions: (
        <Button
          type="button"
          variant="primary"
          disabled={!canWrite}
          onClick={() => setOpen(true)}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {t("blocks.newBlock")}
        </Button>
      ),
    });
  }, [setHeader, t, canWrite]);

  return (
    <div className="flex flex-col gap-5">
      <ReadOnlyNotice module="rentals" />
      {optionsFailed ? (
        <p
          role="alert"
          className="m-0 rounded-lg bg-red-50 p-3 text-sm text-red-800"
        >
          {t("errors.loadChoices")}
        </p>
      ) : null}
      <RentalsTabs />
      <section className="overflow-hidden rounded-xl border border-zinc-200 bg-white">
        <h2 className="border-b border-zinc-200 px-4 py-3.5 text-base font-semibold">
          {t("blocks.title")}
        </h2>
        <QueryResult query={blocks}>
          {(page) =>
            page.items.length === 0 ? (
              <p className="px-4 py-6 text-sm text-zinc-500">
                {t("blocks.empty")}
              </p>
            ) : (
              page.items.map((block) => (
                <div
                  key={block.id}
                  className="flex flex-wrap items-center gap-3 border-b border-zinc-100 px-4 py-3.5 last:border-b-0"
                >
                  <div className="min-w-0 flex-1 basis-56">
                    <span className="block text-sm font-semibold">
                      {block.item_name}
                    </span>
                    <span className="block text-sm text-zinc-500">
                      {block.reason}
                    </span>
                  </div>
                  <span className="text-sm text-zinc-600">
                    {formatDate(block.starts_at)} – {formatDate(block.ends_at)}
                  </span>
                  <span className="rounded-full bg-zinc-100 px-2.5 py-1 text-xs font-semibold text-zinc-700">
                    {t(SOURCE_KEYS[block.source])}
                  </span>
                  <Button
                    type="button"
                    variant="ghostDanger"
                    size="icon"
                    aria-label={t("blocks.delete")}
                    disabled={!canWrite}
                    onClick={() => deleteBlock.mutate(block.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))
            )
          }
        </QueryResult>
      </section>

      <BufferRulesSection
        rules={rules.data}
        models={models.data ?? []}
        categories={categories.data ?? []}
        canWrite={canWrite}
        onSave={(data) => setRule.mutate(data)}
        onDelete={(id) => deleteRule.mutate(id)}
      />

      <BlockSheet
        open={open}
        onClose={() => setOpen(false)}
        assets={assets.data ?? []}
        timezone={timezone}
        canWrite={canWrite}
        onCreated={() => {
          setOpen(false);
          void qc.invalidateQueries({ queryKey: queryKeys.rentals.all });
        }}
      />
    </div>
  );
}

function BlockSheet({
  open,
  onClose,
  assets,
  timezone,
  canWrite,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  assets: { id: string; name: string }[];
  timezone?: string;
  canWrite: boolean;
  onCreated: () => void;
}) {
  const { t } = useTranslation("rentals");
  const today = new Date().toISOString().slice(0, 10);
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  const [itemId, setItemId] = useState("");
  const [startDate, setStartDate] = useState(today);
  const [startTime, setStartTime] = useState("09:00");
  const [endDate, setEndDate] = useState(tomorrow.toISOString().slice(0, 10));
  const [endTime, setEndTime] = useState("16:00");
  const [reason, setReason] = useState("");
  const create = useMutation({
    mutationFn: rentalsApi.createBlock,
    onSuccess: onCreated,
  });

  useEffect(() => {
    if (!itemId && assets.length) setItemId(assets[0].id);
  }, [assets, itemId]);

  const conflicts = conflictsOf(create.error);

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="lg"
      aria-label={t("blocks.newBlock")}
    >
      <SheetHeader title={t("blocks.newBlock")} onClose={onClose} />
      <SheetBody>
        <div className="flex flex-col gap-4">
          <NativeSelect
            label={t("blocks.asset")}
            value={itemId}
            onChange={(event) => setItemId(event.target.value)}
          >
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.name}
              </option>
            ))}
          </NativeSelect>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <DateTimeField
              id="block-start"
              label={t("blocks.from")}
              date={startDate}
              time={startTime}
              onDateChange={setStartDate}
              onTimeChange={setStartTime}
            />
            <DateTimeField
              id="block-end"
              label={t("blocks.until")}
              date={endDate}
              time={endTime}
              onDateChange={setEndDate}
              onTimeChange={setEndTime}
            />
          </div>
          <Input
            label={t("blocks.reason")}
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            required
          />
          {conflicts.length ? (
            <div
              role="alert"
              className="rounded-lg bg-red-50 p-3 text-sm text-red-800"
            >
              <p className="m-0 font-semibold">{t("blocks.bookingInTheWay")}</p>
              <ul className="m-0 mt-1 list-disc pl-4 text-xs">
                {conflicts.map((conflict, index) => (
                  <li key={index}>
                    {conflict.borrower_name} · {formatDate(conflict.starts_at)}{" "}
                    – {formatDate(conflict.ends_at)}
                  </li>
                ))}
              </ul>
            </div>
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
            disabled={!canWrite || !itemId || !reason.trim()}
            isLoading={create.isPending}
            onClick={() =>
              create.mutate({
                item_id: itemId,
                starts_at: wallTimeToIso(startDate, startTime, timezone),
                ends_at: wallTimeToIso(endDate, endTime, timezone),
                reason: reason.trim(),
              })
            }
          >
            {t("blocks.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}
