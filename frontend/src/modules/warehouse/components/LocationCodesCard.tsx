import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, type QueryClient } from "@tanstack/react-query";
import { Printer, Tags } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import {
  Sheet,
  SheetActions,
  SheetBody,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/Sheet";
import { QueryFailure } from "@/components/ui/QueryResult";
import { queryKeys } from "@/hooks/queries/keys";
import type { useConfirm } from "@/hooks/useConfirm";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { invalidation } from "@/lib/api/invalidation";
import { extractApiError } from "@/lib/errors";
import { storagesApi, type StorageCodes } from "@/lib/api/storages";
import { BarcodeLabelSheet } from "@/modules/shared/components/BarcodeLabelSheet";
import type { TranslateFn } from "@/types/i18n";

interface LocationCodesCardProps {
  /** Any location of the warehouse: the codes are its top-level location's,
   *  and "Renumber by template" numbers this location's branch. */
  locationId: string;
  canWrite: boolean;
  confirm: ReturnType<typeof useConfirm>["confirm"];
  /** Open the label sheet for these locations. */
  onPrint: (locationIds: string[]) => void;
}

/**
 * The first code of each level a tree template numbers, the way the server's
 * generator writes it: a placeholder with a width is that many digits
 * (`{rack:02}` → 01), one without is a letter (`{zone}` → A), and the text
 * between them is kept. `{zone}-{rack:02}` gives A, then A-01. Read from the
 * template itself, so the explanation of `{zone:02}-{rack}` says 01, then
 * 01-A, as the codes will.
 */
function templateExamples(template: string): string[] {
  const examples: string[] = [];
  let code = "";
  let cursor = 0;
  for (const match of template.matchAll(
    /\{[A-Za-z_][A-Za-z0-9_]*(?::0?([1-9]))?\}/g,
  )) {
    const width = match[1] ? Number(match[1]) : null;
    code +=
      template.slice(cursor, match.index) +
      (width ? "1".padStart(width, "0") : "A");
    cursor = match.index + match[0].length;
    examples.push(code);
  }
  return examples;
}

/**
 * How the warehouse makes its location codes, and what waits to be
 * relabelled.
 *
 * A business numbers its shelves like the shelf reads (`A-02-01`); a
 * household's codes are random (`LOC-7KQ2`). Renumbering keeps every old code
 * scanning as an alias, and lists the locations whose sticker should be
 * replaced — printed from here, so a warehouse in focus mode never leaves
 * the module.
 */
export function LocationCodesCard({
  locationId,
  canWrite,
  confirm,
  onPrint,
}: LocationCodesCardProps) {
  const { t } = useTranslation("warehouse");
  const [editing, setEditing] = useState(false);
  const codes = useQuery({
    queryKey: queryKeys.storages.codes(locationId),
    queryFn: () => storagesApi.codes(locationId),
  });

  const renumber = useAppMutation(
    (id: string) => storagesApi.number(id, true),
    (queryClient) => invalidation.storages(queryClient),
    { errorFallback: t("putaway.locations.codes.renumberFailed") },
  );
  const replaced = useAppMutation(
    (ids: string[]) => storagesApi.markReprinted(ids),
    (queryClient) => invalidation.storages(queryClient),
    { errorFallback: t("putaway.locations.codes.replacedFailed") },
  );

  if (codes.isError) {
    return (
      <QueryFailure
        error={codes.error}
        message={t("putaway.locations.codes.loadFailed")}
        onRetry={() => void codes.refetch()}
      />
    );
  }
  if (!codes.data) return null;
  const data = codes.data;

  const askRenumber = async () => {
    if (
      !(await confirm({
        title: t("putaway.locations.codes.renumberTitle"),
        message: t("putaway.locations.codes.renumberConfirm"),
        confirmLabel: t("putaway.locations.codes.renumber"),
      }))
    ) {
      return;
    }
    // The branch the reader is looking at, not its whole warehouse: a zone
    // renumbered leaves its sibling zones' stickers alone.
    renumber.mutate(locationId, {
      onSuccess: (result) =>
        toast.success(
          t("putaway.locations.codes.renumbered", {
            count: result.changes.length,
          }),
        ),
    });
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("putaway.locations.codes.title")}</CardTitle>
        <CardDescription>
          {data.is_tree
            ? t("putaway.locations.codes.tree", {
                template: data.template,
                examples: templateExamples(data.template).join(", "),
              })
            : t("putaway.locations.codes.random", { prefix: data.template })}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {canWrite && (
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setEditing(true)}
            >
              {t("putaway.locations.codes.editTemplate")}
            </Button>
            {data.is_tree && (
              <Button
                variant="outline"
                size="sm"
                leftIcon={<Tags size={16} />}
                isLoading={renumber.isPending}
                onClick={() => void askRenumber()}
              >
                {t("putaway.locations.codes.renumber")}
              </Button>
            )}
          </div>
        )}
        {data.reprint.length > 0 && (
          <ReprintList
            reprint={data.reprint}
            canWrite={canWrite}
            isMarking={replaced.isPending}
            onPrint={() => onPrint(data.reprint.map((row) => row.id))}
            onReplaced={() =>
              replaced.mutate(data.reprint.map((row) => row.id))
            }
          />
        )}
      </CardContent>
      {editing && (
        <CodeTemplateSheet codes={data} onClose={() => setEditing(false)} />
      )}
    </Card>
  );
}

function ReprintList({
  reprint,
  canWrite,
  isMarking,
  onPrint,
  onReplaced,
}: {
  reprint: StorageCodes["reprint"];
  canWrite: boolean;
  isMarking: boolean;
  onPrint: () => void;
  onReplaced: () => void;
}) {
  const { t } = useTranslation("warehouse");
  return (
    <section
      aria-label={t("putaway.locations.codes.reprintTitle", {
        count: reprint.length,
      })}
      className="space-y-3 rounded-lg bg-amber-50 px-4 py-3 dark:bg-amber-950/30"
    >
      <p className="text-sm font-medium text-on-warning">
        {t("putaway.locations.codes.reprintTitle", { count: reprint.length })}
      </p>
      <p className="text-xs text-on-secondary">
        {t("putaway.locations.codes.reprintHint")}
      </p>
      <ul className="max-h-48 space-y-1 overflow-y-auto text-sm">
        {reprint.map((row) => (
          <li key={row.id} className="flex flex-wrap gap-x-2">
            <span className="text-on">{row.path}</span>
            <span className="text-on-secondary tabular-nums">
              {/* Two codes and an arrow: nothing to translate. */}
              {`${row.old_code} → ${row.short_code ?? "—"}`}
            </span>
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-2">
        <Button size="sm" leftIcon={<Printer size={16} />} onClick={onPrint}>
          {t("putaway.locations.codes.printNew")}
        </Button>
        {canWrite && (
          <Button
            variant="outline"
            size="sm"
            isLoading={isMarking}
            onClick={onReplaced}
          >
            {t("putaway.locations.codes.markReplaced")}
          </Button>
        )}
      </div>
    </section>
  );
}

/** The warehouse's template, as a person types it; empty follows the profile. */
function CodeTemplateSheet({
  codes,
  onClose,
}: {
  codes: StorageCodes;
  onClose: () => void;
}) {
  const { t } = useTranslation(["warehouse", "common"]);
  const [template, setTemplate] = useState(codes.stored ? codes.template : "");
  const [refusal, setRefusal] = useState<string | null>(null);
  const save = useAppMutation(
    (value: string | null) =>
      storagesApi.setCodeTemplate(codes.warehouse_id, value),
    (queryClient) => invalidation.storages(queryClient),
    { errorFallback: t("warehouse:putaway.locations.codes.saveFailed") },
  );

  const submit = (value: string | null) =>
    save.mutate(value, {
      onSuccess: () => {
        toast.success(t("warehouse:putaway.locations.codes.saved"));
        onClose();
      },
      // Said under the field, in the server's words: the template it read.
      onError: (error) =>
        setRefusal(
          extractApiError(
            error,
            t("warehouse:putaway.locations.codes.saveFailed"),
          ),
        ),
    });

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="md"
      aria-label={t("warehouse:putaway.locations.codes.editTemplate")}
    >
      <SheetHeader
        title={t("warehouse:putaway.locations.codes.editTemplate")}
        onClose={onClose}
      />
      <SheetBody className="space-y-4 p-5">
        <Input
          label={t("warehouse:putaway.locations.codes.templateLabel")}
          value={template}
          placeholder={codes.default_template}
          onChange={(e) => {
            setTemplate(e.target.value);
            setRefusal(null);
          }}
          error={refusal ?? undefined}
        />
        <p className="text-sm text-on-secondary">
          {t("warehouse:putaway.locations.codes.templateHelp", {
            letters: "{zone}",
            digits: "{rack:02}",
          })}
        </p>
        <p className="text-sm text-on-secondary">
          {t("warehouse:putaway.locations.codes.templateDefault", {
            template: codes.default_template,
          })}
        </p>
      </SheetBody>
      <SheetFooter>
        <SheetActions>
          <Button variant="ghost" onClick={onClose}>
            {t("common:actions.cancel")}
          </Button>
          <Button
            isLoading={save.isPending}
            onClick={() => submit(template.trim() || null)}
          >
            {t("common:actions.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </Sheet>
  );
}

/**
 * "Number this rack" over the selection: each chosen location and what is
 * under it gets its template code, parents first so a rack numbered in the
 * same pass is a numbered parent for its levels. Codes already right stay.
 */
export async function numberBranches({
  ids,
  paths,
  queryClient,
  t,
  onDone,
}: {
  ids: string[];
  /** Each location's path, to put parents before their children. */
  paths: Map<string, string>;
  queryClient: QueryClient;
  t: TranslateFn;
  onDone: () => void;
}) {
  const ordered = [...ids].sort(
    (a, b) => (paths.get(a) ?? "").length - (paths.get(b) ?? "").length,
  );
  let changed = 0;
  let failure: unknown = null;
  for (const id of ordered) {
    try {
      changed += (await storagesApi.number(id, false)).changes.length;
    } catch (error) {
      failure ??= error;
    }
  }
  invalidation.storages(queryClient);
  if (failure) {
    toast.error(
      extractApiError(failure, t("putaway.locations.codes.numberFailed")),
    );
    return;
  }
  toast.success(t("putaway.locations.codes.numbered", { count: changed }));
  onDone();
}

/** The shelf label sheet a screen opens for some locations: `print(ids)`
 *  opens it, `sheet` is what to render. */
export function useShelfLabelSheet() {
  const [ids, setIds] = useState<string[] | null>(null);
  const sheet =
    ids && ids.length > 0 ? (
      <BarcodeLabelSheet
        target={{ storageIds: ids }}
        onClose={() => setIds(null)}
      />
    ) : null;
  return { print: setIds, sheet };
}
