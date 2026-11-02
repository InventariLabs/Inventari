import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { Checkbox } from "@/components/ui/Checkbox";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { extractApiError } from "@/lib/errors";
import { makeTDynamic } from "@/lib/i18nHelpers";
import {
  CAPABILITIES,
  PROVIDERS,
  PROVIDER_GROUPS,
  providerDefaults,
  providerDescriptionKey,
} from "@/modules/settings/components/ai/providers";
import { useTestAiConnection } from "@/modules/settings/hooks/useAiConnections";
import type { AiConnectionDraft, LlmCapability, LlmProvider } from "@/types/ai";

interface AiConnectionFieldsProps {
  value: AiConnectionDraft;
  onChange: (value: AiConnectionDraft) => void;
  errors?: Partial<Record<keyof AiConnectionDraft, string>>;
}

// Local providers usually don't need a key (Ollama, LM Studio, vLLM run
// unauthenticated on localhost). Used to decide whether the draft carries
// enough for the test to be worth sending.
const LOCAL_PROVIDERS: ReadonlySet<LlmProvider> = new Set([
  "ollama",
  "lm_studio",
  "vllm",
]);

// A refusal can run for paragraphs. Enough of it to recognise what the model
// said, not so much that the toast becomes the model's essay.
const PREVIEW_CHARS = 160;

const truncate = (text: string) =>
  text.length <= PREVIEW_CHARS ? text : `${text.slice(0, PREVIEW_CHARS)}…`;

export function AiConnectionFields({
  value,
  onChange,
  errors,
}: AiConnectionFieldsProps) {
  const { t } = useTranslation("modules");
  const tDyn = makeTDynamic(t);
  const providerMeta = PROVIDERS.find((p) => p.id === value.provider);
  const testConn = useTestAiConnection();

  /**
   * What the last test said, kept beside the button that produced it.
   *
   * The toast is gone in a few seconds and belongs to the whole screen; the
   * reader who pressed Test is looking at this dialog, and a refusal that
   * leaves nothing behind is one they press again — which, the test being a
   * billed call, spends the organization's budget twice. Cleared as soon as
   * the draft changes: the sentence described what was sent, not what is on
   * screen now.
   */
  const [refusal, setRefusal] = useState<string | null>(null);
  useEffect(() => setRefusal(null), [value]);

  const canTest = LOCAL_PROVIDERS.has(value.provider) || Boolean(value.api_key);

  /**
   * Choosing a provider fills in what that provider needs.
   *
   * Switching invalidates the model that was there — a model name belongs to
   * one provider's catalogue — so the descriptor's default replaces it rather
   * than being merged with it.
   */
  const selectProvider = (provider: LlmProvider) => {
    if (!PROVIDERS.some((p) => p.id === provider)) return;
    onChange({ ...value, provider, ...providerDefaults(provider) });
  };

  const toggleCapability = (cap: LlmCapability, enabled: boolean) => {
    const next = enabled
      ? Array.from(new Set([...value.capabilities, cap]))
      : value.capabilities.filter((c) => c !== cap);
    onChange({ ...value, capabilities: next });
  };

  const onTest = async () => {
    // A draft the test cannot work with is refused here, in the reader's own
    // language, instead of on the wire. Both gaps used to be silent: with no
    // key the button was not rendered at all, and a missing base URL only
    // came back as the provider's transport error.
    if (!canTest) {
      setRefusal(t("config.testNeedsApiKey"));
      return;
    }
    if (providerMeta?.showBaseUrl && !value.api_base_url?.trim()) {
      setRefusal(t("config.testNeedsBaseUrl"));
      return;
    }
    setRefusal(null);
    try {
      const result = await testConn.mutateAsync(value);

      // The reader is not a model: no model list to fill the form from and
      // no contract to read — the LLM sentences below would report "0
      // models available" and "the model read the sample label" for a
      // page fetch. Its three outcomes get their own words.
      if (result.contract.purpose === "recipes.url_fetch") {
        if (result.verdict === "ok") {
          toast.success(t("config.testReaderOk"));
        } else if (result.verdict === "contract_failed") {
          const message = t("config.testReaderEmpty");
          setRefusal(message);
          toast.error(message);
        } else {
          toast.warning(t("config.testReaderFreeTier"));
        }
        return;
      }

      // Auto-fill the model from the discovered list when the user hasn't
      // typed one — the OpenWebUI auto-detect pattern.
      if (result.models.length > 0 && !value.model_name) {
        onChange({ ...value, model_name: result.models[0] });
      }

      // Three outcomes, three messages. A model that took the key and then
      // returned prose is not the same news as one that did the job, and
      // rolling both into "connection works" is how the failure gets found
      // in the field instead of here.
      if (result.verdict === "contract_failed") {
        const message = t("config.testContractFailed", {
          preview: truncate(result.contract.answer_preview ?? ""),
        });
        // A model that answered off-contract failed the test just as a
        // refused key did, so it gets the same standing line — not only the
        // toast that fades.
        setRefusal(message);
        toast.error(message);
        return;
      }
      if (result.verdict === "unchecked") {
        toast.warning(
          t("config.testUnchecked", { count: result.models.length }),
        );
        return;
      }
      // A green verdict means the answer was the agreed shape. Whether the
      // model also read the label is a different question, and one the person
      // choosing a model has to see: a well-formed guess passes the contract
      // too. Nothing read is reported as a warning rather than success — the
      // contract holds, the model is still the wrong one.
      const reading = result.contract.reading;
      if (reading && reading.matched < reading.of) {
        toast.warning(
          t("config.testReadPartial", {
            matched: reading.matched,
            of: reading.of,
          }),
        );
      } else if (reading) {
        toast.success(t("config.testReadAll", { of: reading.of }));
      } else {
        toast.success(
          t("config.testContractOk", { count: result.models.length }),
        );
      }
      if (!result.contract.schema_enforced) {
        toast.warning(t("config.testShapeNotEnforced"));
      }
    } catch (error) {
      // The backend writes its refusals for the person at the screen —
      // an unresolvable hostname is a typo, a private address is a policy,
      // a 429 carries the numbers the counter measured — and translates
      // them. Swallowing them here made every refusal read "check the key
      // and URL", even when the key was fine.
      //
      // It lands in two places on purpose: the toast is how this app reports
      // a failed action, and the line under the button is the copy that is
      // still there when the toast has faded.
      const message = extractApiError(error, t("config.testFailed"));
      setRefusal(message);
      toast.error(message);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div>
        <NativeSelect
          label={t("config.fieldProvider")}
          value={value.provider}
          onChange={(e) => selectProvider(e.target.value as LlmProvider)}
        >
          {PROVIDER_GROUPS.map((group) => {
            const options = PROVIDERS.filter((p) => p.group === group.id);
            if (options.length === 0) return null;
            return (
              <optgroup key={group.id} label={t(group.labelKey)}>
                {options.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.nameKey ? tDyn(p.nameKey) : p.name}
                  </option>
                ))}
              </optgroup>
            );
          })}
        </NativeSelect>
        {providerMeta && (
          <p className="text-xs text-on-muted mt-1">
            {tDyn(providerDescriptionKey(providerMeta.id))}
          </p>
        )}
      </div>

      <div>
        <Input
          label={t("config.fieldName")}
          value={value.name}
          onChange={(e) => onChange({ ...value, name: e.target.value })}
          placeholder={t("config.fieldNamePlaceholder")}
          // Without this the browser reads "name" as a person's and offers
          // the address it has on file: the field arrived holding an email
          // nobody typed into it.
          autoComplete="off"
          aria-invalid={Boolean(errors?.name)}
        />
        {errors?.name && (
          <p className="text-xs text-red-600 mt-1">{errors.name}</p>
        )}
      </div>

      {providerMeta?.needsApiKey && (
        <div>
          <Input
            label={t("config.fieldApiKey")}
            type="password"
            value={value.api_key ?? ""}
            onChange={(e) =>
              onChange({ ...value, api_key: e.target.value || null })
            }
            placeholder={
              providerMeta.apiKeyPlaceholder ??
              t("config.fieldApiKeyPlaceholder")
            }
            autoComplete="off"
          />
          {providerMeta.docsUrl && (
            <a
              href={providerMeta.docsUrl}
              target="_blank"
              rel="noreferrer noopener"
              className="mt-1 inline-block text-xs text-primary-700 dark:text-primary-500 hover:text-primary-800 dark:hover:text-primary-500 underline"
            >
              {t("config.fieldApiKeyDocs", { provider: providerMeta.name })}
            </a>
          )}
        </div>
      )}

      {providerMeta?.showBaseUrl && (
        <div>
          <Input
            label={t("config.fieldBaseUrl")}
            value={value.api_base_url ?? ""}
            onChange={(e) =>
              onChange({ ...value, api_base_url: e.target.value || null })
            }
            onBlur={() => {
              // An emptied field used to strand the connection: the save
              // went through and the first call died on a relative URL.
              // The descriptor's default comes back on blur. Every
              // provider that shows this field carries one except
              // "custom" — an address no descriptor can know — which
              // keeps its deliberate blank.
              const fallback = providerMeta?.defaultBaseUrl;
              if (!value.api_base_url && fallback) {
                onChange({ ...value, api_base_url: fallback });
              }
            }}
            placeholder="https://api.example.com/v1"
            aria-invalid={Boolean(errors?.api_base_url)}
          />
          {errors?.api_base_url && (
            <p className="text-xs text-red-600 mt-1">{errors.api_base_url}</p>
          )}
          {/* The one place the form hands out a default the backend will
              refuse. A local engine lives on a private address, and the SSRF
              guard is closed until an operator opens it — so say it here,
              beside the address, rather than letting the save fail first. */}
          {providerMeta.group === "local" && (
            <p className="mt-1 text-xs text-on-secondary">
              {t("config.localEngineHint")}
            </p>
          )}
        </div>
      )}

      {providerMeta?.hasModel !== false && (
        <div>
          <Input
            label={t("config.fieldModel")}
            value={value.model_name ?? ""}
            onChange={(e) =>
              onChange({ ...value, model_name: e.target.value || null })
            }
            placeholder="google/gemini-2.0-flash-001"
          />
        </div>
      )}

      {/* Always offered. The button used to be rendered only once the draft
          carried a key, so the reader whose form was missing something had
          nothing to press and nothing to read. Pressing it on an incomplete
          draft now answers with the field that is missing. */}
      <div className="flex flex-col gap-2">
        <div>
          <Button
            type="button"
            variant="ghost"
            onClick={onTest}
            disabled={testConn.isPending}
          >
            {testConn.isPending
              ? t("config.testing")
              : t("config.testConnection")}
          </Button>
        </div>
        {/* The refusal stands where the proof would have. `role="alert"`
            because it is news the moment it arrives, and it is part of the
            form rather than of the screen as a whole. */}
        {refusal && (
          <p
            role="alert"
            className="text-sm text-on-danger bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-900/40 rounded-lg px-3 py-2"
          >
            {refusal}
          </p>
        )}
      </div>

      <div>
        {/* A heading over a group of checkboxes rather than a label: a label
            names one control, and this names several. */}
        <p className="block text-xs font-medium text-on-muted uppercase tracking-wide mb-1.5">
          {t("config.fieldCapabilities")}
        </p>
        <p className="text-xs text-on-muted mb-1.5">
          {t("config.fieldCapabilitiesHint")}
        </p>
        <div className="flex flex-wrap items-center gap-3">
          {/* Every capability is a checkbox, including the ones the provider
              suggested. The suggestion comes from the protocol, and the
              protocol says nothing about the model behind it: a connection to
              a text-only model through an OpenAI-compatible endpoint used to
              wear an unremovable VISION badge and stay on the list of things
              to read photographs with. */}
          {CAPABILITIES.map((cap) => {
            const isChecked = value.capabilities.includes(cap.value);
            return (
              <Checkbox
                key={cap.value}
                checked={isChecked}
                onChange={() => toggleCapability(cap.value, !isChecked)}
                label={
                  <span className="text-sm text-on">{t(cap.labelKey)}</span>
                }
              />
            );
          })}
        </div>
      </div>
    </div>
  );
}
