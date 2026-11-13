/**
 * AuditLogPage — /settings/audit-log
 *
 * Lists immutable AuditLog rows for the current org
 * with client-side filters (target_type, user_id, since) and a
 * client-side CSV export. Reads from GET /api/v1/audit-log via
 * ``useAuditLog``. Admin-only (SettingsShell group is gated on
 * isAdmin).
 *
 * The table now shows
 * human-readable labels — user_email (LEFT JOIN in backend),
 * snapshot.name for the target, i18n-mapped action/reason badges,
 * and a user picker instead of raw-UUID input. The UUID is retained
 * in tooltips and in CSV export (audit log must stay precise even
 * when names mutate).
 */
import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { extractApiError, isUnreachableError } from "@/lib/errors";
import { downloadCsv, toCsv } from "@/lib/csv";
import { useQuery } from "@tanstack/react-query";
import { Download, History, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Badge } from "@/components/ui/Badge";
import { DateInput } from "@/components/ui/DateInput";
import Pagination from "@/components/ui/Pagination";
import { useListedPermissionLabel } from "@/modules/shared/hooks/permissionLabel";
import { useKeysetPaging } from "@/hooks/useKeysetPaging";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import {
  useAuditLog,
  useAuditTargetTypes,
} from "@/modules/settings/hooks/useAuditLog";
import {
  auditChanges,
  auditFieldTitles,
  snapshotIdentity,
  type AuditChange,
} from "@/modules/settings/utils/auditChanges";
import { usersApi } from "@/lib/api/admin";
import { useOrganization } from "@/modules/settings/hooks/useOrganization";
import { referenceTargetType } from "@/modules/settings/utils/auditChanges";
import { getTodayFilename } from "@/utils/formatters";
import { queryKeys } from "@/hooks/queries/keys";
import { toast } from "sonner";
import { copyTextOrExplain } from "@/lib/clipboard";
import type { AuditLogEntry } from "@/types/core";
import type { BadgeProps } from "@/components/ui/Badge";
import { formatDateTime } from "@/utils/helpers";
import {
  AuditActor,
  AuditDetail,
  AuditLogEntryCard,
  AuditTarget,
  apiKeyActor,
  targetTypeLabel,
} from "@/modules/settings/components/AuditLogEntry";
import { useModuleSettingTitles } from "@/modules/settings/hooks/useModuleSettingTitles";
import type { AuditActorFilter } from "@/lib/api/auditLog";

const PAGE_SIZE = 100;

/**
 * The actions the log records, in the order a record meets them.
 *
 * The subtitle names them with the same labels the Action column puts on its
 * badges — it used to spell the raw enum out instead (`CREATE / UPDATE /
 * SOFT_DELETE / PURGE`), which was the one part of the page no language ever
 * translated and which named nothing the reader could find in the table.
 */
const LOGGED_ACTIONS = [
  "CREATE",
  "UPDATE",
  "QUANTITY_CHANGE",
  "MOVE",
  "USE",
  "DISPOSE",
  "RESTORE",
  "SOFT_DELETE",
  "PURGE",
];

type ActionVariant = NonNullable<BadgeProps["variant"]>;

const ACTION_VARIANT: Record<string, ActionVariant> = {
  CREATE: "success",
  UPDATE: "secondary",
  QUANTITY_CHANGE: "secondary",
  MOVE: "secondary",
  USE: "secondary",
  DISPOSE: "warning",
  RESTORE: "success",
  SOFT_DELETE: "warning",
  PURGE: "danger",
  HARD_DELETE: "danger",
};

/**
 * An act can have a word of its own for one kind of record. The log files a
 * revoked invitation or API key as a soft delete and an accepted invitation as
 * a "use" — words of the stock vocabulary that say nothing about an access
 * that was taken back or given. Each entry is a pair the writers produce; the
 * rest of the actions read the same on every record.
 */
const TARGET_ACTION_LABELS: Record<
  string,
  Record<string, (t: (key: string) => string) => string>
> = {
  invitation: {
    SOFT_DELETE: (t) => t("settings.audit.revoked"),
    USE: (t) => t("settings.audit.invitationAccepted"),
  },
  api_key: {
    SOFT_DELETE: (t) => t("settings.audit.revoked"),
  },
};

function actionLabel(
  action: string,
  t: (key: string) => string,
  row?: Pick<AuditLogEntry, "target_type" | "snapshot">,
): string {
  const own = row && TARGET_ACTION_LABELS[row.target_type]?.[action];
  if (own) return own(t);
  // A profile writes its module settings when it is applied (onboarding, a
  // switch), under the person who chose it. The row says so instead of
  // passing for that person's own edit of a setting.
  if (
    action === "UPDATE" &&
    row?.target_type === "module" &&
    String(row.snapshot?.subject ?? "").startsWith("profile:")
  ) {
    return t("settings.audit.profileDefault");
  }
  const translated = t(`settings.audit.actions.${action}`);
  return translated === `settings.audit.actions.${action}`
    ? action
    : translated;
}

/**
 * Which module a row is about, when it is about one.
 *
 * A module's entries carry the module's name where a record carries its name —
 * the toggle and the settings write both put it in the snapshot — which is
 * also what the Target column reads. It is the key to asking that module how
 * its settings call themselves.
 */
function moduleOf(row: AuditLogEntry): string | null {
  return row.target_type === "module" ? snapshotIdentity(row.snapshot) : null;
}

/**
 * The exported journal, columns matching the row plus the key's prefix.
 *
 * The export is the copy an auditor takes away, and the one place a revoked
 * key can still be asked about: keeping the prefix out of it would leave the
 * file unable to tell a key's work from its owner's.
 */
function auditLogCsv(rows: AuditLogEntry[]): string {
  const header = [
    "id",
    "created_at",
    "user_id",
    "user_email",
    "api_key",
    "action",
    "target_type",
    "target_id",
    "target_label",
    "reason",
    "snapshot",
  ];
  const pickName = (r: AuditLogEntry): string =>
    snapshotIdentity(r.snapshot) ?? "";
  const body = rows.map((r) => [
    r.id,
    r.created_at,
    r.user_id ?? "",
    r.user_email ?? "",
    apiKeyActor(r) ?? "",
    r.action,
    r.target_type,
    r.target_id,
    pickName(r),
    r.reason ?? "",
    r.snapshot ? JSON.stringify(r.snapshot) : "",
  ]);
  return toCsv([header, ...body]);
}

/**
 * What the filters are built from: the kinds of record in the log (built from
 * the log itself — a hand-typed list offered modules this profile does not
 * install and left out the things that actually changed) and the members.
 * Either failing leaves its select with nothing to offer, which the page says.
 *
 * The members query is local — settings owns its own member picker rather
 * than importing useOrgMembers from the approvals module (AGENTS.md: respect
 * module boundaries).
 */
function useAuditFilterLookups() {
  const targetTypesQuery = useAuditTargetTypes();
  const membersQuery = useQuery({
    queryKey: queryKeys.users.orgMembers,
    queryFn: () => usersApi.getOrgMembers(),
    staleTime: 60_000,
  });
  const failed = targetTypesQuery.isError ? targetTypesQuery : membersQuery;
  return {
    targetTypes: targetTypesQuery.data ?? [],
    members: membersQuery.data ?? [],
    lookupError: failed.isError ? failed.error : null,
    retryLookups: () => {
      if (targetTypesQuery.isError) void targetTypesQuery.refetch();
      if (membersQuery.isError) void membersQuery.refetch();
    },
  };
}

export default function AuditLogPage() {
  const { t } = useTranslation("common");
  /**
   * One entry, one shape per viewport. Five columns in a horizontal scroller
   * left "Target" and "Details" off a 390px screen — the answer this page is
   * opened for — and an entry reads whole or not at all. Rendered exactly once
   * per viewport size (useMediaQuery), which keeps the desktop markup
   * unchanged and testable in jsdom.
   */
  const isNarrow = useMediaQuery("(max-width: 767px)");
  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      title: t("settings.audit.title"),
      subtitle: t("settings.audit.subtitle", {
        actions: LOGGED_ACTIONS.map((action) => actionLabel(action, t)).join(
          " · ",
        ),
      }),
    });
  }, [setHeader, t]);

  const [targetType, setTargetType] = useState<string>("");
  const [userId, setUserId] = useState<string>("");
  const [actor, setActor] = useState<AuditActorFilter | "">("");
  const [since, setSince] = useState<string>("");
  const [until, setUntil] = useState<string>("");
  // An empty journal answers two different questions: an organization that
  // has not done anything yet, and a filter that matched nothing. The first
  // is the state of the data; the second is the state of the ask (the same
  // distinction `ItemsEmptyState` draws with its `hasFilters`).
  const hasFilters = Boolean(targetType || userId || actor || since || until);
  // Rows the reader asked to see in full. A change list is short by default
  // so that the size of a product's nutrition document stops deciding the
  // height of the row it changed.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const { targetTypes, members, lookupError, retryLookups } =
    useAuditFilterLookups();

  // The organization the journal belongs to. Every row here is about it, and
  // its name is what an `organization_id` in a snapshot means — the shell has
  // already loaded it, so this asks the cache rather than the network.
  const { data: organization } = useOrganization();

  const question = useMemo(
    () => ({
      target_type: targetType || undefined,
      user_id: userId || undefined,
      actor: actor || undefined,
      since: since || undefined,
      until: until || undefined,
    }),
    [targetType, userId, actor, since, until],
  );

  // Any change to the question starts the journal again from its first page:
  // a position in one list means nothing in another.
  const paging = useKeysetPaging(question);

  const filters = useMemo(
    () => ({ ...question, limit: PAGE_SIZE, cursor: paging.cursor }),
    [question, paging.cursor],
  );

  const { data, isLoading, isError, error, isPlaceholderData, refetch } =
    useAuditLog(filters);
  // Memoised because `resolveId` reads it: `?? []` is a fresh array on every
  // render, and a dependency that always changes is a memo that never holds.
  const rows: AuditLogEntry[] = useMemo(() => data?.items ?? [], [data]);
  const total = data?.total ?? 0;
  // The journal counts only as far as the server's cap, as every list that
  // grows with the organization does; past it the bar says "more than".
  const totalCapped = data?.total_capped ?? false;

  /**
   * A name for an id, from what this page can vouch for.
   *
   * Three sources, in the order they can be trusted:
   *
   * 1. Rows of the *same* kind as the field asks for. A module switch-on puts
   *    the organization's id in its target column while its snapshot names the
   *    module — the one map this replaced held both by id alone, so a product
   *    row on the same page read `Organization: stats`. Names are kept by
   *    kind now, and only the kind the field names is asked for.
   * 2. The organization this page belongs to, which the settings shell has
   *    already loaded: every entry in the journal is about it, and its name
   *    does not depend on which rows the page is showing.
   * 3. The members, loaded above for the filter — a user id is a user id.
   *
   * Anything else is an id this page has no name for, and it says so.
   */
  // The catalogue is read only when a key's row is on the page: a reader who
  // cannot issue keys would otherwise meet a refused request for a screen
  // that has no key on it.
  const showsApiKey = rows.some((row) => row.target_type === "api_key");
  const permissionLabel = useListedPermissionLabel(showsApiKey);
  const resolveId = useMemo(() => {
    const namesByKind = new Map<string, Map<string, string>>();
    for (const row of rows) {
      const label = snapshotIdentity(row.snapshot);
      if (!label) continue;
      const ofKind = namesByKind.get(row.target_type) ?? new Map();
      ofKind.set(row.target_id, label);
      namesByKind.set(row.target_type, ofKind);
    }
    const memberEmails = new Map<string, string>();
    for (const member of members) {
      if (member.email) memberEmails.set(member.id, member.email);
    }
    return (uuid: string, kind?: string) => {
      if (kind === "permission") {
        // A permission is named by what the key's dialog calls it; one the
        // catalogue does not list is left to the caller.
        return permissionLabel(uuid);
      }
      if (kind === "organization" && organization?.id === uuid) {
        return organization.name ?? null;
      }
      const named = kind
        ? namesByKind.get(referenceTargetType(kind))?.get(uuid)
        : undefined;
      return named ?? memberEmails.get(uuid) ?? null;
    };
  }, [members, rows, organization, permissionLabel]);

  const changesOf = (row: AuditLogEntry): AuditChange[] =>
    auditChanges(row.snapshot, row.action, resolveId, t);

  // The names a module gives its own settings, for the rows that changed one.
  const moduleTitles = useModuleSettingTitles(rows.map(moduleOf));
  const titlesOf = (row: AuditLogEntry) =>
    auditFieldTitles(row.target_type, moduleTitles[moduleOf(row) ?? ""]);

  const toggleExpanded = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const onExport = () => {
    // The file is dated the day the reader took it out, in their own zone.
    downloadCsv(auditLogCsv(rows), `audit-log-${getTodayFilename()}.csv`);
  };

  const onCopy = async (uuid: string) => {
    if (await copyTextOrExplain(uuid, t("common:copy.failed"))) {
      toast.success(t("actions.copied"));
    }
  };

  return (
    <div className="space-y-4">
      <Card className="p-4">
        {/* The controls carry their own labels (UI_GUIDELINES §2.10): a
            hand-rolled label beside the field spaces itself, and the three
            here each sat a different distance above their control. */}
        <div className="flex flex-wrap items-end gap-3">
          <NativeSelect
            label={t("settings.audit.targetType")}
            wrapperClassName="w-full sm:w-48"
            value={targetType}
            onChange={(e) => setTargetType(e.target.value)}
          >
            <option value="">{t("settings.audit.anyTarget")}</option>
            {targetTypes.map((tt) => (
              <option key={tt} value={tt}>
                {targetTypeLabel(tt, t)}
              </option>
            ))}
          </NativeSelect>
          <NativeSelect
            label={t("settings.audit.userId")}
            wrapperClassName="w-full sm:w-56"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
          >
            <option value="">{t("settings.audit.allUsers")}</option>
            {members.map((m) => (
              <option key={m.id} value={m.id}>
                {m.email}
              </option>
            ))}
          </NativeSelect>
          {lookupError != null && (
            <InlineQueryError error={lookupError} onRetry={retryLookups} />
          )}
          {/* The journal answers two questions with one list: what the
              organisation did, and what its machine credentials did. An
              administrator who revoked a key on suspicion of a leak reads
              the second. */}
          <NativeSelect
            label={t("settings.audit.actor.label")}
            wrapperClassName="w-full sm:w-44"
            value={actor}
            onChange={(e) => setActor(e.target.value as AuditActorFilter | "")}
          >
            <option value="">{t("settings.audit.actor.everyone")}</option>
            <option value="human">{t("settings.audit.actor.people")}</option>
            <option value="api_key">{t("settings.audit.actor.apiKeys")}</option>
          </NativeSelect>
          {/* A filter names a range, so "last week" earns its place here —
              see UI_GUIDELINES §2.8 on presets. */}
          {/* A range needs both ends: `since` alone can answer
              "everything after Tuesday" but never "what happened that
              afternoon". */}
          <DateInput
            label={t("settings.audit.since")}
            value={since}
            onChange={setSince}
            presets={["minus1Week", "minus1Month"]}
            wrapperClassName="w-full sm:w-44"
          />
          <DateInput
            label={t("settings.audit.until")}
            value={until}
            onChange={setUntil}
            presets={["today", "yesterday"]}
            wrapperClassName="w-full sm:w-44"
          />
          <div className="flex w-full gap-2 sm:ml-auto sm:w-auto">
            <Button
              variant="outline"
              className="flex-1 sm:flex-none"
              onClick={() => void refetch()}
              disabled={isLoading}
              leftIcon={<RefreshCw size={16} />}
            >
              {t("actions.refresh")}
            </Button>
            <Button
              variant="outline"
              className="flex-1 sm:flex-none"
              onClick={onExport}
              disabled={rows.length === 0}
              leftIcon={<Download size={16} />}
            >
              {t("settings.audit.exportCsv")}
            </Button>
          </div>
        </div>
      </Card>

      <Card className="p-0 overflow-hidden">
        {isLoading ? (
          <div className="p-8 text-center text-sm text-on-muted">
            {t("messages.loading")}
          </div>
        ) : isError ? (
          <div className="p-8 text-center text-sm text-on-danger">
            {extractApiError(
              error,
              isUnreachableError(error)
                ? t("errors.backendUnavailableTitle")
                : t("messages.error"),
            )}
          </div>
        ) : rows.length === 0 ? (
          <div className="p-8 text-center text-sm text-on-muted">
            <History size={28} className="mx-auto mb-2 opacity-40" />
            {hasFilters
              ? t("settings.audit.empty")
              : t("settings.audit.emptyNoFilters")}
          </div>
        ) : (
          <>
            {isNarrow ? (
              <div className="flex flex-col gap-3 p-3">
                {rows.map((r) => (
                  <AuditLogEntryCard
                    key={r.id}
                    row={r}
                    changes={changesOf(r)}
                    actionVariant={ACTION_VARIANT[r.action] ?? "outline"}
                    actionLabel={actionLabel(r.action, t, r)}
                    expanded={expanded.has(r.id)}
                    onToggle={() => toggleExpanded(r.id)}
                    onCopy={onCopy}
                    t={t}
                    titles={titlesOf(r)}
                  />
                ))}
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-raised border-b border-border">
                    <tr>
                      <th className="px-3 py-2 text-left font-medium text-on-secondary">
                        {t("settings.audit.columns.timestamp")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-on-secondary">
                        {t("settings.audit.columns.user")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-on-secondary">
                        {t("settings.audit.columns.action")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-on-secondary">
                        {t("settings.audit.columns.target")}
                      </th>
                      <th className="px-3 py-2 text-left font-medium text-on-secondary">
                        {t("settings.audit.columns.detail")}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map((r) => (
                      <tr
                        key={r.id}
                        className="border-b border-border/60 hover:bg-surface-raised/50"
                      >
                        <td className="px-3 py-2 whitespace-nowrap font-mono text-xs text-on-secondary">
                          {formatDateTime(r.created_at)}
                        </td>
                        <td className="px-3 py-2 text-xs">
                          <AuditActor row={r} t={t} />
                        </td>
                        <td className="px-3 py-2">
                          <Badge
                            variant={ACTION_VARIANT[r.action] ?? "outline"}
                          >
                            {actionLabel(r.action, t, r)}
                          </Badge>
                        </td>
                        <td className="px-3 py-2 text-xs">
                          <AuditTarget row={r} t={t} onCopy={onCopy} />
                        </td>
                        <td className="px-3 py-2 align-top text-on-secondary text-xs">
                          <AuditDetail
                            row={r}
                            changes={changesOf(r)}
                            expanded={expanded.has(r.id)}
                            onToggle={() => toggleExpanded(r.id)}
                            t={t}
                            titles={titlesOf(r)}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </Card>

      <Pagination
        skip={paging.page * PAGE_SIZE}
        limit={PAGE_SIZE}
        total={total}
        totalCapped={totalCapped}
        keyset={{ rows: rows.length, hasNext: Boolean(data?.next_cursor) }}
        onPrev={paging.goPrev}
        // The cursor on screen belongs to the page it came with; while the
        // next page loads the old rows are still shown, and their cursor must
        // not be taken for the new page's.
        onNext={() => !isPlaceholderData && paging.goNext(data?.next_cursor)}
      />
    </div>
  );
}
