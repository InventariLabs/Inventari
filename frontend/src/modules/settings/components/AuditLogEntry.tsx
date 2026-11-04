/**
 * The parts one audit entry is made of, and the card a phone reads it on.
 *
 * The log used to be a five-column table in a horizontal scroller: at 390px
 * 391 of its 755 pixels were off-screen — "Target" and "Details", which is
 * the answer the reader came for — and "Action" broke mid-word. A row of this
 * log is one sentence ("who, when, what, on what"), and a scroller cuts it in
 * half with no way to see both halves at once.
 *
 * So below `md` the same four facts are stacked in a card, and the table keeps
 * the width it needs above it. The pieces live here rather than in the page so
 * that the card and the row say the same thing by construction — the pattern
 * `/settings/api-keys` already uses.
 */
import type { TFunction } from "i18next";
import { Copy } from "lucide-react";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { useEnabledModulesOptional } from "@/contexts/ModulesContext";
import { useHasPermission } from "@/hooks/useHasPermission";
import { formatDateTime } from "@/utils/helpers";
import type { AuditLogEntry } from "@/types/core";
import type { BadgeProps } from "@/components/ui/Badge";
import {
  auditFieldLabel,
  auditModuleName,
  auditProfileName,
  snapshotIdentity,
  type AuditChange,
} from "@/modules/settings/utils/auditChanges";
import type { TranslateFn } from "@/types/i18n";

function shortUuid(uuid: string): string {
  return uuid.slice(0, 8);
}

/** How many changed fields a row shows before it offers the rest. */
const CHANGES_SHOWN = 2;

/**
 * The number of the record an approval entry is about, when the entry
 * carries one.
 *
 * An entry about an approval request is really about the thing being
 * approved: the request's uuid ("8d6f4bf7 Wniosek o akceptację") names
 * nothing a reader can look up, while the number its module wrote beside
 * it is the record the log is asked about.
 */
function approvedTargetNumber(row: AuditLogEntry): string | null {
  if (row.target_type !== "approval_request") return null;
  const approves = row.snapshot?.approves;
  if (typeof approves !== "object" || approves === null) return null;
  const number = (approves as Record<string, unknown>).number;
  return typeof number === "string" && number !== "" ? number : null;
}

/**
 * What a record that is not named by a person reads as.
 *
 * The snapshot carries the code's own key for these — `maker`, `equipment_wms`
 * — which is a name nobody has met on a screen. A module is known by the name
 * the App Store prints, a workspace mode by the one Settings prints, and an
 * invitation by the address it went to and the role it offered: the id it is
 * filed under says nothing the reader came for.
 */
function codedTargetLabel(row: AuditLogEntry, t: TranslateFn): string | null {
  const snapshot = row.snapshot;
  if (typeof snapshot !== "object" || snapshot === null) return null;
  const record = snapshot as Record<string, unknown>;
  const name = snapshotIdentity(snapshot);
  if (row.target_type === "module" && name) return auditModuleName(t, name);
  if (row.target_type === "product_profile" && name) {
    return auditProfileName(t, name);
  }
  if (row.target_type === "invitation") {
    const { invited_email: email, role } = record;
    if (typeof email !== "string" || email === "") return null;
    const label =
      typeof role === "string" && role !== ""
        ? t(`common:settings.organization.memberRoles.${role}`, {
            defaultValue: role,
          })
        : null;
    return label ? `${email} · ${label}` : email;
  }
  return null;
}

/**
 * What the Target column says a row is about.
 *
 * Every entry about a document used to show eight characters of a UUID — the
 * one an auditor filtering for `IN/2026/009` came here to read included —
 * because a document is known by its number and the page read only `name`.
 */
function targetLabel(row: AuditLogEntry, t: TranslateFn): string {
  return (
    approvedTargetNumber(row) ??
    codedTargetLabel(row, t) ??
    snapshotIdentity(row.snapshot) ??
    shortUuid(row.target_id)
  );
}

function reasonLabel(reason: string, t: (key: string) => string): string {
  const translated = t(`settings.audit.reasons.${reason}`);
  return translated === `settings.audit.reasons.${reason}`
    ? reason
    : translated;
}

/**
 * The key an entry was written by, when one was — `meta_data.actor.key_prefix`.
 *
 * An entry a key wrote and one the same person wrote from the screen used to
 * read identically: same `user_email`, no `meta_data`. Once the key is
 * revoked it also leaves the list of keys, so this prefix is the only thing
 * that still ties a row to the credential that wrote it.
 */
export function apiKeyActor(row: AuditLogEntry): string | null {
  const actor = row.meta_data?.actor;
  if (typeof actor !== "object" || actor === null) return null;
  const { type, key_prefix: prefix } = actor as Record<string, unknown>;
  return type === "api_key" && typeof prefix === "string" && prefix !== ""
    ? prefix
    : null;
}

/**
 * The explanation a count's correction carries in its meta_data — the code
 * for what the counter found (damaged, lost, …). The entry's own `reason`
 * says why the write happened; this says what the difference was.
 */
function discrepancyCodeOf(row: AuditLogEntry): string | null {
  const code = row.meta_data?.discrepancy_reason_code;
  return typeof code === "string" && code !== "" ? code : null;
}

export function targetTypeLabel(
  targetType: string,
  t: (key: string) => string,
): string {
  const translated = t(`settings.audit.targetTypes.${targetType}`);
  return translated === `settings.audit.targetTypes.${targetType}`
    ? targetType
    : translated;
}

/**
 * The change list in one cell: two lines, then the rest on request.
 *
 * A row used to be as tall as the JSON document behind it — a product's
 * nutrition data from a food database, printed whole on both sides of the
 * arrow, took half a screen for one entry.
 */
function AuditChanges({
  changes,
  expanded,
  onToggle,
  t,
  titles,
}: {
  changes: AuditChange[];
  expanded: boolean;
  onToggle: () => void;
  t: TFunction;
  /** A module's own names for its settings, when the entry is about them. */
  titles?: Record<string, string>;
}) {
  // Empty hands back nothing: whether the cell needs a dash instead is the
  // row's call, made after the reason and the code have had their say.
  if (changes.length === 0) return null;
  const shown = expanded ? changes : changes.slice(0, CHANGES_SHOWN);
  return (
    <div className="space-y-0.5">
      {shown.map((change) => (
        <div key={change.path} className={expanded ? "" : "line-clamp-2"}>
          <span className="text-on-muted">
            {auditFieldLabel(change.path, t, titles)}:{" "}
          </span>
          {change.from === null ? (
            change.to
          ) : (
            <>
              {change.from} → {change.to}
            </>
          )}
        </div>
      ))}
      {changes.length > CHANGES_SHOWN && (
        <Button
          type="button"
          variant="ghost"
          size="inline"
          className="text-xs underline"
          onClick={onToggle}
        >
          {t(
            expanded
              ? "settings.audit.showLess"
              : "settings.audit.showWholeChange",
          )}
        </Button>
      )}
    </div>
  );
}

/** The record an entry is about: what it is called, its kind, its id. */
export function AuditTarget({
  row,
  t,
  onCopy,
}: {
  row: AuditLogEntry;
  t: TFunction;
  onCopy: (id: string) => void;
}) {
  return (
    <div className="text-xs">
      <div className="text-on truncate max-w-[16rem]">
        {targetLabel(row, t)}
      </div>
      <div className="text-on-muted flex items-center gap-1">
        <span>{targetTypeLabel(row.target_type, t)}</span>
        <span>·</span>
        <Button
          type="button"
          variant="ghost"
          size="contentSm"
          onClick={() => onCopy(row.target_id)}
          className="p-0.5 gap-0.5 font-mono text-on-muted hover:text-on hover:bg-transparent active:bg-transparent"
          title={row.target_id}
        >
          {shortUuid(row.target_id)}
          <Copy size={11} />
        </Button>
      </div>
    </div>
  );
}

/**
 * Who did it: the account, the key when the account sent a machine, and the
 * system when no person was there at all.
 *
 * The reader sorting a leak from a habit needs both halves on the row — the
 * person who owns the credential and which credential it was — and the key's
 * prefix is the half that still answers after the key has been revoked and
 * left the list of keys. A cut-off by the circuit breaker is the third actor:
 * nobody's account to name, and "Unknown user" read like the act of someone
 * whose account was since deleted — the breaker itself is the actor, and the
 * row says so.
 */
export function AuditActor({ row, t }: { row: AuditLogEntry; t: TFunction }) {
  const prefix = apiKeyActor(row);
  const system = systemActor(row);
  return (
    <div className="text-xs">
      <div className="truncate" title={row.user_id ?? undefined}>
        {row.user_email ??
          (system
            ? t("common:settings.audit.actor.system")
            : t("common:settings.audit.unknownUser"))}
      </div>
      {prefix && (
        <div className="text-on-muted flex items-center gap-1">
          <span>{t("common:settings.audit.actor.key")}</span>
          <span>·</span>
          <span className="font-mono">{prefix}</span>
        </div>
      )}
    </div>
  );
}

/**
 * Whether the system, not a person, wrote this entry.
 *
 * New entries say so by the structured actor (`meta_data.actor.type`); the
 * breaker's older rows only carry its mark (`auto_disabled`), and they are
 * the same actor wearing an older spelling — the safety switch, never an
 * unknown user.
 */
function systemActor(row: AuditLogEntry): boolean {
  const actor = row.meta_data?.actor;
  if (typeof actor === "object" && actor !== null) {
    const { type } = actor as Record<string, unknown>;
    if (type === "system") return true;
  }
  return row.meta_data?.auto_disabled === true;
}

/** A string field of an entry's meta_data, or null when it is absent. */
function stringMeta(row: AuditLogEntry, key: string): string | null {
  const value = row.meta_data?.[key];
  return typeof value === "string" && value !== "" ? value : null;
}

/**
 * The document behind the entry, named and reachable.
 *
 * The number was written into `meta_data` from the day the executors started
 * carrying one — a receipt or a dispatch names the document that moved the
 * goods, and a correction names both itself and the one it corrects — and
 * the Detail column read only the change list and the reason. "Document
 * execution" without a number says something else wrote the change and
 * nothing about which document to look up.
 *
 * The number becomes a link only where the link leads somewhere: the module
 * has to be enabled for the organization and the account allowed to read
 * documents, or following it would be a refusal arriving after the click.
 * A numbered row with no document id — an entry from before the id was
 * recorded — shows the number as plain text.
 */
function AuditDocumentReference({
  row,
  t,
}: {
  row: AuditLogEntry;
  t: TFunction;
}) {
  const number = stringMeta(row, "document_number");
  const enabledModules = useEnabledModulesOptional();
  const mayRead = useHasPermission("warehouse:read");
  if (!number) return null;
  const documentId = stringMeta(row, "source_document_id");
  const corrects = stringMeta(row, "corrects_document_number");
  const reachable =
    documentId !== null && enabledModules.includes("warehouse") && mayRead;
  return (
    <span className="text-on-muted">
      {t("common:settings.audit.document")}:{" "}
      {reachable ? (
        <Link
          to={`/warehouse/documents/${documentId}`}
          className="text-on-primary hover:underline"
        >
          {number}
        </Link>
      ) : (
        number
      )}
      {corrects && (
        <span>
          {" · "}
          {t("common:settings.audit.corrects", { number: corrects })}
        </span>
      )}
    </span>
  );
}

/**
 * What changed, and why.
 *
 * Numbers and reason were an either/or, so the entry with the richer record
 * showed less: a stock take's correction answered "what changed" but dropped
 * the why, and one carrying only a reason kept that. Both halves are shown
 * now, one under the other.
 */
export function AuditDetail({
  row,
  changes,
  expanded,
  onToggle,
  t,
  titles,
}: {
  row: AuditLogEntry;
  /** Resolved by the page: naming a uuid needs the members it has loaded. */
  changes: AuditChange[];
  expanded: boolean;
  onToggle: () => void;
  t: TFunction;
  /** A module's own names for its settings, when the entry is about them. */
  titles?: Record<string, string>;
}) {
  const code = discrepancyCodeOf(row);
  const document = stringMeta(row, "document_number");
  // A production run's reason is a code without a number; the run is named
  // beside it so two runs on one day do not read the same.
  const runNumber = stringMeta(row, "production_order_number");
  // The person's half of the breaker: it switched the channel off by
  // itself, and this entry says someone switched it back on. Without the
  // sentence the row reads as a plain update over a channel that was never
  // off.
  const reactivated = row.meta_data?.reactivated_after_circuit_breaker;
  return (
    <div className="flex flex-col gap-0.5">
      <AuditChanges
        changes={changes}
        expanded={expanded}
        onToggle={onToggle}
        t={t}
        titles={titles}
      />
      {row.reason && (
        <span className="text-on-muted">
          {reasonLabel(row.reason, t)}
          {runNumber ? ` ${runNumber}` : ""}
        </span>
      )}
      {document && <AuditDocumentReference row={row} t={t} />}
      {reactivated === true && (
        <span className="text-on-muted">
          {t("common:settings.audit.reactivatedAfterBreaker")}
        </span>
      )}
      {code && (
        <span className="text-on-muted">
          {t(`stock_takes:reasons.discrepancy.codes.${code}`, {
            defaultValue: code,
          })}
        </span>
      )}
      {!changes.length && !row.reason && !code && !reactivated && !document && (
        <>—</>
      )}
    </div>
  );
}

/** One entry as a card: the whole sentence, no sideways scrolling. */
export function AuditLogEntryCard({
  row,
  changes,
  actionVariant,
  actionLabel,
  expanded,
  onToggle,
  onCopy,
  t,
  titles,
}: {
  row: AuditLogEntry;
  changes: AuditChange[];
  actionVariant: BadgeProps["variant"];
  actionLabel: string;
  expanded: boolean;
  onToggle: () => void;
  onCopy: (id: string) => void;
  t: TFunction;
  /** A module's own names for its settings, when the entry is about them. */
  titles?: Record<string, string>;
}) {
  return (
    <Card className="p-3 space-y-2" data-testid="audit-log-card">
      <div className="flex items-start justify-between gap-2">
        <span className="font-mono text-xs text-on-secondary">
          {formatDateTime(row.created_at)}
        </span>
        <Badge variant={actionVariant}>{actionLabel}</Badge>
      </div>
      <AuditActor row={row} t={t} />
      <AuditTarget row={row} t={t} onCopy={onCopy} />
      <div className="text-xs text-on-secondary">
        <AuditDetail
          row={row}
          changes={changes}
          expanded={expanded}
          onToggle={onToggle}
          t={t}
          titles={titles}
        />
      </div>
    </Card>
  );
}
