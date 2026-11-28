import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Pencil, Plus, Trash2 } from "lucide-react";

import {
  Button,
  Card,
  ConfirmDialog,
  Input,
  LoadingSpinner,
  NativeSelect,
  QueryError,
  QueryResult,
  ReadOnlyNotice,
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
  extractApiError,
  useCanWrite,
  useModulePageHeader,
} from "@/module-sdk";

import type {
  AssetOption,
  Kit,
  KitCreate,
  KitListRow,
  KitMemberIn,
  ModelOption,
} from "../api/rentals";
import { RentalsTabs } from "../components/RentalsTabs";
import {
  useCreateKit,
  useDeleteKit,
  useKit,
  useKits,
  useModels,
  useRentalAssets,
  useUpdateKit,
} from "../hooks/useRentals";

let nextMemberKey = 1;

/** A member row as the sheet edits it; not the wire shape. */
type MemberDraft = {
  key: number;
  kind: "asset" | "model";
  itemId: string;
  model: string;
  quantity: number;
};

function blankMember(): MemberDraft {
  return {
    key: nextMemberKey++,
    kind: "asset",
    itemId: "",
    model: "",
    quantity: 1,
  };
}

function draftOf(member: NonNullable<Kit["members"]>[number]): MemberDraft {
  if (member.item_id) {
    return {
      key: nextMemberKey++,
      kind: "asset",
      itemId: member.item_id,
      model: "",
      quantity: 1,
    };
  }
  return {
    key: nextMemberKey++,
    kind: "model",
    itemId: "",
    model: member.model ?? "",
    quantity: member.quantity,
  };
}

/** The members a member row contributes; a row with nothing picked is left out. */
function membersOf(members: MemberDraft[]): KitMemberIn[] {
  const result: KitMemberIn[] = [];
  for (const member of members) {
    if (member.kind === "asset") {
      if (member.itemId) result.push({ item_id: member.itemId, quantity: 1 });
    } else if (member.model) {
      result.push({ model: member.model, quantity: member.quantity });
    }
  }
  return result;
}

export default function KitsPage() {
  const { t } = useTranslation("rentals");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("rentals");
  const kits = useKits();
  const models = useModels();
  const assets = useRentalAssets("");
  const remove = useDeleteKit();
  const [editor, setEditor] = useState<
    { mode: "create" } | { mode: "edit"; id: string } | null
  >(null);
  const [toDelete, setToDelete] = useState<KitListRow | null>(null);
  const optionsFailed = models.isError || assets.isError;

  useEffect(() => {
    setHeader({
      title: t("kits.title"),
      backTo: "/rentals",
      actions: canWrite ? (
        <Button
          type="button"
          variant="primary"
          onClick={() => setEditor({ mode: "create" })}
        >
          <Plus className="mr-1.5 h-4 w-4" />
          {t("kits.new")}
        </Button>
      ) : undefined,
    });
  }, [setHeader, t, canWrite]);

  return (
    <div className="flex flex-col gap-5">
      <RentalsTabs />
      <ReadOnlyNotice module="rentals" />
      {optionsFailed ? (
        <p
          role="alert"
          className="m-0 rounded-lg bg-red-50 p-3 text-sm text-red-800"
        >
          {t("errors.loadChoices")}
        </p>
      ) : null}
      <QueryResult query={kits}>
        {(rows) =>
          rows.length === 0 ? (
            <p className="rounded-xl border border-zinc-200 bg-white px-4 py-6 text-sm text-zinc-500">
              {t("kits.empty")}
            </p>
          ) : (
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {rows.map((kit) => (
                <Card key={kit.id} className="flex flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <h2 className="truncate text-base font-semibold">
                        {kit.name}
                      </h2>
                      <span className="font-mono text-xs text-zinc-500">
                        {kit.code}
                      </span>
                    </div>
                    <div className="flex shrink-0 gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        aria-label={t("kits.editNamed", {
                          name: kit.name,
                        })}
                        disabled={!canWrite}
                        onClick={() => setEditor({ mode: "edit", id: kit.id })}
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        type="button"
                        variant="ghostDanger"
                        size="icon"
                        aria-label={t("kits.deleteNamed", {
                          name: kit.name,
                        })}
                        disabled={!canWrite}
                        onClick={() => setToDelete(kit)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </div>
                  {kit.summary ? (
                    <p className="m-0 text-sm text-zinc-600">{kit.summary}</p>
                  ) : null}
                  <span className="text-xs text-zinc-500">
                    {t("kits.memberCount", { count: kit.member_count })}
                  </span>
                </Card>
              ))}
            </div>
          )
        }
      </QueryResult>

      {editor ? (
        <KitSheet
          kitId={editor.mode === "edit" ? editor.id : undefined}
          assets={assets.data ?? []}
          models={models.data ?? []}
          canWrite={canWrite}
          onClose={() => setEditor(null)}
        />
      ) : null}

      <ConfirmDialog
        open={toDelete !== null}
        title={t("kits.deleteConfirmTitle")}
        message={t("kits.deleteConfirmMessage")}
        confirmLabel={t("kits.delete")}
        cancelLabel={t("kits.cancel")}
        variant="danger"
        errorFallback={t("errors.generic")}
        onConfirm={async () => {
          if (!toDelete) return;
          await remove.mutateAsync(toDelete.id);
          setToDelete(null);
        }}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

function KitSheet({
  kitId,
  assets,
  models,
  canWrite,
  onClose,
}: {
  kitId?: string;
  assets: AssetOption[];
  models: ModelOption[];
  canWrite: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation("rentals");
  const kit = useKit(kitId);
  const create = useCreateKit();
  const update = useUpdateKit();
  const [name, setName] = useState("");
  const [note, setNote] = useState("");
  const [members, setMembers] = useState<MemberDraft[]>([blankMember()]);
  const [saveError, setSaveError] = useState<string | null>(null);
  // The edit sheet fills once, when the kit arrives. Later arrivals (a
  // refetch) must not overwrite what the reader has typed since.
  const loadedKit = useRef<string | null>(null);

  useEffect(() => {
    const data = kit.data;
    if (!kitId || !data || loadedKit.current === data.id) return;
    loadedKit.current = data.id;
    setName(data.name);
    setNote(data.note ?? "");
    setMembers(
      data.members?.length ? data.members.map(draftOf) : [blankMember()],
    );
  }, [kitId, kit.data]);

  const loading = Boolean(kitId) && kit.isLoading;
  const failed = Boolean(kitId) && kit.isError;
  const payloadMembers = membersOf(members);
  const pending = create.isPending || update.isPending;
  const canSave =
    canWrite && name.trim().length > 0 && payloadMembers.length > 0 && !pending;
  const hint =
    loading || failed
      ? ""
      : !name.trim()
        ? t("kits.needName")
        : payloadMembers.length === 0
          ? t("kits.needMembers")
          : "";

  function updateMember(key: number, patch: Partial<MemberDraft>) {
    setMembers((current) =>
      current.map((member) =>
        member.key === key ? { ...member, ...patch } : member,
      ),
    );
  }

  function save() {
    if (!canSave) return;
    const data: KitCreate = {
      name: name.trim(),
      note: note.trim() || undefined,
      members: payloadMembers,
    };
    setSaveError(null);
    const options = {
      onSuccess: onClose,
      // The sheet prints the refusal under the form; a toast would repeat it.
      onError: (error: Error) =>
        setSaveError(extractApiError(error, t("errors.generic"))),
    };
    if (kitId) update.mutate({ id: kitId, data }, options);
    else create.mutate(data, options);
  }

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="xl"
      aria-label={kitId ? t("kits.edit") : t("kits.new")}
    >
      <SheetHeader
        title={kitId ? t("kits.edit") : t("kits.new")}
        onClose={onClose}
      />
      <SheetBody className="p-5">
        {loading ? (
          <div className="flex justify-center p-8">
            <LoadingSpinner />
          </div>
        ) : failed ? (
          <QueryError error={kit.error} onRetry={() => void kit.refetch()} />
        ) : (
          <div className="flex flex-col gap-4">
            <Input
              label={t("kits.name")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              required
            />
            <Input
              label={t("kits.note")}
              value={note}
              onChange={(event) => setNote(event.target.value)}
            />
            {kitId && kit.data ? (
              <div className="flex flex-col gap-0.5">
                <span className="text-xs font-medium uppercase tracking-wide text-zinc-500">
                  {t("kits.code")}
                </span>
                <span className="font-mono text-sm">{kit.data.code}</span>
                <span className="text-xs text-zinc-500">
                  {t("kits.codeHint")}
                </span>
              </div>
            ) : null}
            <fieldset className="flex flex-col gap-2.5">
              <legend className="mb-1 text-sm font-semibold">
                {t("kits.members")}
              </legend>
              {members.map((member) => (
                <MemberRow
                  key={member.key}
                  member={member}
                  assets={assets}
                  models={models}
                  onUpdate={(patch) => updateMember(member.key, patch)}
                  onRemove={() =>
                    setMembers((current) =>
                      current.filter((row) => row.key !== member.key),
                    )
                  }
                />
              ))}
              <Button
                type="button"
                variant="outline"
                className="w-full border-dashed"
                onClick={() =>
                  setMembers((current) => [...current, blankMember()])
                }
              >
                <Plus className="mr-1.5 h-4 w-4" />
                {t("kits.addMember")}
              </Button>
            </fieldset>
            {saveError ? (
              <div
                role="alert"
                className="rounded-lg bg-red-50 p-3 text-sm text-red-800"
              >
                <p className="m-0 font-semibold">{t("kits.saveFailed")}</p>
                <p className="m-0 mt-0.5">{saveError}</p>
              </div>
            ) : null}
          </div>
        )}
      </SheetBody>
      <SheetFooter>
        {hint ? <p className="mb-2 text-xs text-zinc-500">{hint}</p> : null}
        <SheetActions>
          <Button type="button" variant="outline" onClick={onClose}>
            {t("kits.cancel")}
          </Button>
          <Button
            type="button"
            variant="primary"
            disabled={!canSave || loading || failed}
            isLoading={pending}
            onClick={save}
          >
            {t("kits.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}

function MemberRow({
  member,
  assets,
  models,
  onUpdate,
  onRemove,
}: {
  member: MemberDraft;
  assets: AssetOption[];
  models: ModelOption[];
  onUpdate: (patch: Partial<MemberDraft>) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation("rentals");
  return (
    <div className="flex flex-wrap items-end gap-2 rounded-xl border border-zinc-200 p-3">
      <div className="flex gap-1.5 pb-1">
        <Button
          type="button"
          size="sm"
          variant={member.kind === "asset" ? "primary" : "outline"}
          onClick={() => onUpdate({ kind: "asset" })}
        >
          {t("kits.memberKind.asset")}
        </Button>
        <Button
          type="button"
          size="sm"
          variant={member.kind === "model" ? "primary" : "outline"}
          onClick={() => onUpdate({ kind: "model" })}
        >
          {t("kits.memberKind.model")}
        </Button>
      </div>
      <div className="min-w-0 flex-1 basis-48">
        {member.kind === "asset" ? (
          <NativeSelect
            label={t("kits.chooseAsset")}
            value={member.itemId}
            onChange={(event) => onUpdate({ itemId: event.target.value })}
          >
            <option value="">{t("kits.chooseAsset")}</option>
            {assets.map((asset) => (
              <option key={asset.id} value={asset.id}>
                {asset.name}
                {asset.serial_number ? ` · ${asset.serial_number}` : ""}
              </option>
            ))}
          </NativeSelect>
        ) : (
          <NativeSelect
            label={t("kits.chooseModel")}
            value={member.model}
            onChange={(event) => onUpdate({ model: event.target.value })}
          >
            <option value="">{t("kits.chooseModel")}</option>
            {models.map((model) => (
              <option key={model.model} value={model.model}>
                {model.model} · {t("form.units", { count: model.total_units })}
              </option>
            ))}
          </NativeSelect>
        )}
      </div>
      {member.kind === "model" ? (
        <Input
          type="number"
          min={1}
          max={999}
          label={t("kits.quantity")}
          wrapperClassName="w-24 shrink-0"
          value={String(member.quantity)}
          onChange={(event) => {
            const parsed = Math.trunc(Number(event.target.value));
            if (!Number.isFinite(parsed)) return;
            onUpdate({ quantity: Math.min(999, Math.max(1, parsed)) });
          }}
        />
      ) : null}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={t("kits.removeMember")}
        onClick={onRemove}
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    </div>
  );
}
