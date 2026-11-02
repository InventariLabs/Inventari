import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import axios from "axios";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { extractApiError } from "@/lib/errors";
import { AiConnectionFields } from "@/modules/settings/components/ai/AiConnectionFields";
import { providerDefaults } from "@/modules/settings/components/ai/providers";
import {
  useCreateAiConnection,
  useUpdateAiConnection,
} from "@/modules/settings/hooks/useAiConnections";
import type { AiConnection, AiConnectionDraft, LlmProvider } from "@/types/ai";

interface AiConnectionFormModalProps {
  open: boolean;
  editing: AiConnection | null;
  connections: AiConnection[];
  onClose: () => void;
}

const emptyCreate = (
  provider: LlmProvider = "openrouter",
): AiConnectionDraft => ({
  name: "",
  provider,
  api_key: null,
  temperature: null,
  max_tokens: null,
  top_p: null,
  // The provider the dialog opens on fills its own fields, exactly as
  // picking one from the list does. Opening with a provider selected and
  // its address empty made the shortest path — accept, type the key, save
  // — the one that ended in a refusal from the backend.
  ...providerDefaults(provider),
});

const editingToCreate = (connection: AiConnection): AiConnectionDraft => ({
  name: connection.name,
  provider: connection.provider,
  api_key: null,
  api_base_url: connection.api_base_url,
  model_name: connection.model_name,
  temperature: connection.temperature,
  max_tokens: connection.max_tokens,
  top_p: connection.top_p,
  capabilities: connection.capabilities ?? [],
});

// The fields this form can paint an inline error under. A 422 entry that
// names one of them lands under its input; anything else (or a 422 naming
// a field with no inline slot) keeps the toast, so no refusal loses its
// addressee on the way.
const INLINE_ERROR_FIELDS: ReadonlySet<string> = new Set([
  "name",
  "api_base_url",
]);

// A 422 whose loc names a field speaks to one input, not to the whole
// screen. The name-required rule renders red under its input; a server
// refusal with the same information used to surface only as a vanishing
// toast with the wire string.
const fieldErrorsFrom422 = (
  error: unknown,
): Partial<Record<keyof AiConnectionDraft, string>> | null => {
  if (!axios.isAxiosError(error)) return null;
  if (error.response?.status !== 422) return null;
  const detail: unknown = error.response.data?.detail;
  if (!Array.isArray(detail) || detail.length === 0) return null;

  const next: Record<string, string> = {};
  for (const entry of detail) {
    if (!entry || typeof entry !== "object") return null;
    const { loc, msg } = entry as { loc?: unknown; msg?: unknown };
    if (!Array.isArray(loc) || typeof msg !== "string") return null;
    const field = loc[loc.length - 1];
    if (typeof field !== "string" || !INLINE_ERROR_FIELDS.has(field)) {
      return null;
    }
    next[field] = msg;
  }
  return next;
};

export function AiConnectionFormModal({
  open,
  editing,
  connections,
  onClose,
}: AiConnectionFormModalProps) {
  const { t } = useTranslation("modules");
  const [draft, setDraft] = useState<AiConnectionDraft>(() => emptyCreate());
  const [errors, setErrors] = useState<
    Partial<Record<keyof AiConnectionDraft, string>>
  >({});

  const create = useCreateAiConnection(t("config.createFailed"));
  const update = useUpdateAiConnection(t("config.updateFailed"));

  useEffect(() => {
    if (!open) return;
    setDraft(editing ? editingToCreate(editing) : emptyCreate());
    setErrors({});
  }, [open, editing]);

  const validate = (): boolean => {
    const next: Partial<Record<keyof AiConnectionDraft, string>> = {};
    const name = draft.name.trim();
    if (!name) {
      next.name = t("config.errorNameRequired");
    } else if (
      connections.some(
        (c) =>
          c.id !== editing?.id &&
          c.name.trim().toLowerCase() === name.toLowerCase(),
      )
    ) {
      next.name = t("config.errorNameTaken");
    }
    if (draft.capabilities.length === 0) {
      next.capabilities = t("config.errorCapabilityRequired");
    }
    setErrors(next);
    return Object.keys(next).length === 0;
  };

  const onSubmit = () => {
    if (!validate()) return;
    // Taking onError here quiets the hook's toast for the whole mutation,
    // so this handler owns the addressee of every failure: a 422 naming
    // a field goes under that field, everything else goes to the toast.
    const onMutateError =
      (fallback: string) =>
      (error: unknown): void => {
        const inline = fieldErrorsFrom422(error);
        if (inline) {
          setErrors((prev) => ({ ...prev, ...inline }));
          return;
        }
        toast.error(extractApiError(error, fallback));
      };
    if (editing) {
      // provider is immutable after creation — AiConnectionUpdate schema
      // uses extra='forbid', so omit it (and api_key when unchanged).
      const { provider: _provider, ...rest } = draft;
      const updateData = {
        ...rest,
        api_key: draft.api_key ?? undefined,
      };
      update.mutate(
        { id: editing.id, data: updateData },
        {
          onSuccess: onClose,
          onError: onMutateError(t("config.updateFailed")),
        },
      );
    } else {
      create.mutate(draft, {
        onSuccess: onClose,
        onError: onMutateError(t("config.createFailed")),
      });
    }
  };

  const isPending = create.isPending || update.isPending;
  const titleId = "ai-connection-form-title";

  return (
    <Sheet
      open={open}
      onClose={onClose}
      maxWidth="lg"
      aria-labelledby={titleId}
    >
      <div className="flex flex-col gap-4 p-6 max-h-[90vh] sm:max-h-[calc(90vh-2rem)] overflow-hidden">
        <div>
          <h2 id={titleId} className="text-lg font-semibold text-on">
            {editing ? t("config.editConnection") : t("config.addConnection")}
          </h2>
          <p className="text-sm text-on-muted mt-1">
            {t("config.formDescription")}
          </p>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto pr-1 -mr-1">
          <AiConnectionFields
            value={draft}
            onChange={setDraft}
            errors={errors}
          />
        </div>

        <div className="flex justify-end gap-2 pt-2 border-t border-border">
          <Button variant="ghost" onClick={onClose} disabled={isPending}>
            {t("config.cancel")}
          </Button>
          <Button onClick={onSubmit} disabled={isPending}>
            {isPending ? t("config.saving") : t("config.save")}
          </Button>
        </div>
      </div>
    </Sheet>
  );
}
