import React, { useId, useState } from "react";
import { AlertTriangle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useWebhookAvailableEvents } from "@/modules/webhooks/hooks/useWebhooks";
import { Input } from "@/components/ui/Input";
import { Checkbox } from "@/components/ui/Checkbox";
import { ChoiceGroup } from "@/components/ui/ChoiceGroup";
import { SheetActions, SheetBody, SheetFooter } from "@/components/ui/Sheet";
import { FIELD_LABEL_CLASS } from "@/components/ui/fieldLabel";
import { extractApiError, extractApiErrorField } from "@/lib/errors";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { QueryFailure } from "@/components/ui/QueryResult";
import type {
  WebhookEndpoint,
  WebhookEndpointCreate,
  WebhookEndpointUpdate,
} from "@/modules/webhooks/types/webhooks";

const MASKED = "**********";

/**
 * The subscriptions the catalogue no longer lists, kept fixable.
 *
 * They still sit in `event_types` (those rows are not migrated), but the
 * list below renders the catalogue alone — so without this block the field
 * shows "1 selected" with nothing ticked, and every save answers 422 with
 * the name it refused. Rendering the name, ticked, is what lets the
 * administrator remove it.
 */
function WithdrawnEvents({
  events,
  onToggle,
}: {
  events: string[];
  onToggle: (value: string) => void;
}) {
  const { t } = useTranslation("webhooks");
  if (events.length === 0) return null;
  return (
    <div className="mb-1 space-y-1 border-b border-border pb-2">
      <p className="px-2 text-xs font-medium text-on-warning">
        {t("form.withdrawnEvents")}
      </p>
      <p className="px-2 text-xs text-on-muted">
        {t("form.withdrawnEventsHint")}
      </p>
      {events.map((value) => (
        <label
          key={value}
          className="flex items-center gap-2 cursor-pointer hover:bg-surface px-2 py-1 rounded"
        >
          <Checkbox checked onChange={() => onToggle(value)} />
          <span className="text-xs font-mono text-on-warning">{value}</span>
          <span className="text-xs text-on-muted dark:text-on-secondary">
            {`— ${t(`events.${value}`, { defaultValue: value })}`}
          </span>
        </label>
      ))}
    </div>
  );
}

interface WebhookFormProps {
  webhook?: WebhookEndpoint | null;
  onSave: (
    data: WebhookEndpointCreate | WebhookEndpointUpdate,
  ) => Promise<void>;
  onCancel: () => void;
  isSaving?: boolean;
}

export default function WebhookForm({
  webhook,
  onSave,
  onCancel,
  isSaving = false,
}: WebhookFormProps) {
  const { t } = useTranslation(["webhooks", "common"]);

  const isEdit = !!webhook;
  const eventsLabelId = useId();
  const activeLabelId = useId();

  const [name, setName] = useState(webhook?.name ?? "");
  const [url, setUrl] = useState(webhook?.url ?? "");
  const [secret, setSecret] = useState("");
  const [httpMethod, setHttpMethod] = useState<"POST" | "PUT">(
    // The contract types the method as a plain string; the server only stores the two it accepts.
    (webhook?.http_method as "POST" | "PUT" | undefined) ?? "POST",
  );
  const [selectedEvents, setSelectedEvents] = useState<string[]>(
    webhook?.event_types ?? [],
  );
  const [maxRetries, setMaxRetries] = useState(webhook?.max_retries ?? 3);
  const [timeoutSeconds, setTimeoutSeconds] = useState(
    webhook?.timeout_seconds ?? 10,
  );
  const [isActive, setIsActive] = useState(webhook?.is_active ?? true);
  /**
   * What the server said when it refused the save. `await onSave(...)` used
   * to run without a `catch`, so a 422 — naming the address it rejected and
   * the switch that would allow it — reached nobody, and the form sat there
   * looking saved.
   */
  const [saveError, setSaveError] = useState<{
    message: string;
    field: string | null;
  } | null>(null);
  const urlRejection = saveError?.field === "url" ? saveError.message : null;
  const formRejection = saveError && !urlRejection ? saveError.message : null;

  const {
    data: availableEvents = [],
    isPending: eventsLoading,
    isError: eventsFailed,
    error: eventsError,
    refetch: refetchEvents,
  } = useWebhookAvailableEvents();
  // The module a disabled event needs is named the way the rest of the app
  // names it — `modules.<name>.name`, never the raw identifier.
  const moduleLabels = useModuleLabels();

  // A subscription the catalogue no longer lists still sits in `event_types`
  // (those rows are not migrated), but it has no checkbox of its own — the
  // list renders the catalogue alone — so the field could never be
  // unchecked: "1 selected" with nothing ticked, and Save answered 422 with
  // the name it refused. Rendering it here is what makes the field fixable.
  // Only once the catalogue has arrived: during the first fetch every
  // selection would look withdrawn.
  const withdrawnEvents =
    !eventsLoading && !eventsFailed
      ? selectedEvents.filter(
          (value) => !availableEvents.some((ev) => ev.event_type === value),
        )
      : [];

  const toggleEvent = (value: string) => {
    setSelectedEvents((prev) =>
      prev.includes(value) ? prev.filter((e) => e !== value) : [...prev, value],
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const data: WebhookEndpointCreate | WebhookEndpointUpdate = {
      name,
      url,
      http_method: httpMethod,
      event_types: selectedEvents,
      max_retries: maxRetries,
      timeout_seconds: timeoutSeconds,
      is_active: isActive,
    };
    if (secret && secret !== MASKED) {
      data.secret = secret;
    }
    setSaveError(null);
    try {
      await onSave(data);
    } catch (error) {
      setSaveError({
        message: extractApiError(error, t("common:messages.error")),
        field: extractApiErrorField(error, "field"),
      });
    }
  };

  return (
    // The fields scroll, the actions do not: with forty-two events on offer
    // the form is taller than a 900px window, and Save used to sit below the
    // bottom edge of the dialog.
    <form onSubmit={handleSubmit} className="flex min-h-0 flex-1 flex-col">
      <SheetBody className="space-y-5 p-5">
        {/* Name */}
        <Input
          label={t("common:form.name")}
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t("form.namePlaceholder")}
          required
          autoFocus
        />

        {/* URL */}
        <div className="space-y-1.5">
          <Input
            label={t("form.url")}
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            placeholder={t("form.urlPlaceholder")}
            required
            type="url"
            error={urlRejection ?? undefined}
          />
          <p className="text-xs text-on-muted">{t("form.urlHint")}</p>
          {url.startsWith("http://") && (
            <p className="text-xs text-on-warning flex items-start gap-1.5">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" />
              {t("form.insecureUrlWarning")}
            </p>
          )}
        </div>

        {/* Secret */}
        <div className="space-y-1.5">
          {isEdit && webhook?.has_secret && !secret && (
            <p className="text-xs text-on-secondary dark:text-on-muted">
              {t("form.secretMasked")}
            </p>
          )}
          <Input
            label={t("form.secret")}
            value={secret}
            onChange={(e) => setSecret(e.target.value)}
            placeholder={
              isEdit && webhook?.has_secret
                ? MASKED
                : t("form.secretPlaceholder")
            }
            type="password"
            autoComplete="new-password"
          />
          {!secret && !(isEdit && webhook?.has_secret) && (
            <p className="text-xs text-on-warning flex items-start gap-1.5">
              <AlertTriangle size={13} className="shrink-0 mt-0.5" />
              {t("form.noSecretWarning")}
            </p>
          )}
        </div>

        {/* HTTP method — a group of options has no single field to label, so
            it names itself. The hand-rolled radios also carried
            `accent-blue-600`, which is blue whatever palette the profile is
            painted in. */}
        <ChoiceGroup
          label={t("form.httpMethod")}
          options={[
            { id: "POST", label: "POST" },
            { id: "PUT", label: "PUT" },
          ]}
          value={httpMethod}
          onChange={(id) => setHttpMethod(id as "POST" | "PUT")}
        />

        {/* Event types */}
        <div className="space-y-1.5">
          <p id={eventsLabelId} className={FIELD_LABEL_CLASS}>
            {t("form.eventTypes")}
            {selectedEvents.length > 0 && (
              <span className="ml-2 normal-case text-on-primary">
                {t("form.eventsSelected", { count: selectedEvents.length })}
              </span>
            )}
          </p>
          <div
            role="group"
            aria-labelledby={eventsLabelId}
            className="border border-border rounded-lg p-3 max-h-48 overflow-y-auto space-y-1"
          >
            {/* "No event types" and "the list did not arrive" send the
                reader different places: the first to an administrator, the
                second back to this button. */}
            {eventsFailed ? (
              <QueryFailure
                error={eventsError}
                onRetry={() => refetchEvents()}
              />
            ) : (
              availableEvents.length === 0 && (
                <p className="text-sm text-on-muted">
                  {t("form.eventTypesPlaceholder")}
                </p>
              )
            )}
            <WithdrawnEvents events={withdrawnEvents} onToggle={toggleEvent} />
            {availableEvents.map((ev) => (
              <label
                key={ev.event_type}
                className="flex items-center gap-2 cursor-pointer hover:bg-surface px-2 py-1 rounded"
              >
                <Checkbox
                  checked={selectedEvents.includes(ev.event_type)}
                  onChange={() => toggleEvent(ev.event_type)}
                />
                <span className="text-xs font-mono text-on-secondary dark:text-on-muted">
                  {ev.event_type}
                </span>
                {/* The catalogue is translated here; the API's English sentence
                    is the fallback for an event added after this locale. */}
                <span className="text-xs text-on-muted dark:text-on-secondary">
                  {`— ${t(`events.${ev.event_type}`, {
                    defaultValue: ev.description,
                  })}`}
                </span>
                {!ev.available && ev.source_module && (
                  <span className="text-[10px] text-on-muted border border-border rounded px-1.5 py-0.5 shrink-0">
                    {t("form.eventNeedsModule", {
                      module: moduleLabels({
                        name: ev.source_module,
                        display_name: ev.source_module,
                        description: "",
                      }).name,
                    })}
                  </span>
                )}
              </label>
            ))}
          </div>
        </div>

        {/* Retries + Timeout */}
        <div className="grid grid-cols-2 items-end gap-4">
          <Input
            label={t("form.maxRetries")}
            type="number"
            min={0}
            max={10}
            value={maxRetries}
            onChange={(e) => setMaxRetries(Number(e.target.value))}
          />
          <Input
            label={t("form.timeoutSeconds")}
            type="number"
            min={1}
            max={30}
            value={timeoutSeconds}
            onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
          />
        </div>

        {/* Active toggle. The switch track keeps a transparent 2px border: that
            is the inset the knob travels within, not a visible frame, so the 1px
            rule of UI_GUIDELINES §2.10 does not apply to it.

            `aria-labelledby` is what gives it a name: wrapping a `<div>` in a
            `<label>` names nothing, because a label only names a form control. */}
        <div className="flex items-center gap-3">
          <div
            role="switch"
            aria-checked={isActive}
            aria-labelledby={activeLabelId}
            tabIndex={0}
            onClick={() => setIsActive((v) => !v)}
            onKeyDown={(e) => {
              if (e.key === " " || e.key === "Enter") {
                e.preventDefault();
                setIsActive((v) => !v);
              }
            }}
            className={`relative inline-flex h-6 w-11 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors focus:outline-none focus:ring-2 focus:ring-primary-500 ${
              isActive ? "bg-primary-600" : "bg-surface-inset"
            }`}
          >
            <span
              className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-surface-card shadow ring-0 transition duration-200 ease-in-out ${
                isActive ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </div>
          <span id={activeLabelId} className="text-sm text-on-secondary">
            {t("form.isActive")}
          </span>
        </div>

        {/* A refusal that is not about one field still has to be readable — it
            used to vanish with the rejected promise. */}
        {formRejection && (
          <p
            role="alert"
            className="text-sm text-on-danger bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40 rounded-lg px-3 py-2"
          >
            {formRejection}
          </p>
        )}
      </SheetBody>

      <SheetFooter>
        <SheetActions>
          <Button type="button" variant="outline" onClick={onCancel}>
            {t("common:form.cancel")}
          </Button>
          <Button
            type="submit"
            variant="primary"
            isLoading={isSaving}
            disabled={selectedEvents.length === 0}
          >
            {t("common:form.save")}
          </Button>
        </SheetActions>
      </SheetFooter>
    </form>
  );
}
