import { useTranslation } from "react-i18next";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { Badge } from "@/components/ui/Badge";
import { NativeSelect } from "@/components/ui/NativeSelect";
import { useHasPermission } from "@/hooks/useHasPermission";
import { useModuleLabels } from "@/hooks/useModuleLabels";
import { getProviderDescriptor } from "@/modules/settings/components/ai/providers";
import { useSetAiBinding } from "@/modules/settings/hooks/useAiConnections";
import type { AiConnection, AiPurpose } from "@/types/ai";

/** Letters and digits only, so "MiniMax-M3" and "minimax m3" compare equal. */
const squash = (text: string) => text.toLowerCase().replace(/[^a-z0-9]/g, "");

/**
 * One connection, named so it can be told from the others.
 *
 * The options read "minimax · MiniMax-M3", "minimax m3 · MiniMax-M3",
 * "deepseek-flash · deepseek-v4-flash" — the same word twice on every line,
 * and no sign of the one thing that separated the first two, which was the
 * provider they went through.
 *
 * The connection's own name always stays: it is unique within the
 * organization, so it is what makes two entries tellable apart. The provider
 * joins it only when the name does not already say it, and the model only
 * when it is not just the name written differently.
 */
function optionLabel(connection: AiConnection): string {
  const provider = getProviderDescriptor(connection.provider)?.name;
  const name = connection.name;
  const model = connection.model_name ?? "";

  const parts: string[] = [];
  if (provider && !squash(name).includes(squash(provider)))
    parts.push(provider);
  parts.push(name);
  if (model && squash(model) !== squash(name)) parts.push(model);
  return parts.join(" · ");
}

interface PurposeBindingSelectProps {
  purpose: AiPurpose;
  connections: AiConnection[];
  /** False when the module that declared this purpose is switched off. */
  available?: boolean;
}

export function PurposeBindingSelect({
  purpose,
  connections,
  available = true,
}: PurposeBindingSelectProps) {
  const { t } = useTranslation("modules");
  const moduleLabels = useModuleLabels();
  // Binding a purpose is an organization setting: the endpoint checks
  // `org:settings:write`, and an account without it could still pick a
  // connection here and meet the refusal only after the change.
  const canWriteBinding = useHasPermission("org:settings:write");
  const setBinding = useSetAiBinding(t("config.bindingFailed"));

  const declared = useMemo(
    () =>
      connections.filter((c) => c.capabilities?.includes(purpose.capability)),
    [connections, purpose.capability],
  );

  // A connection whose test for this very capability came back failed is not
  // a candidate for it: the backend refuses to hand it out, so offering it
  // here would only produce "nothing is configured" later, from a screen
  // where something plainly was.
  const failed = useMemo(
    () =>
      declared.filter(
        (c) => c.capability_checks?.[purpose.capability]?.ok === false,
      ),
    [declared, purpose.capability],
  );
  const eligible = useMemo(
    () => declared.filter((c) => !failed.includes(c)),
    [declared, failed],
  );

  // The org's current choice is always on its own list, refused verdict or
  // not. A binding that is missing from the options makes the browser fall
  // back to rendering "Not configured" as already chosen — so no change
  // event can ever fire, and the binding can be neither detached nor the
  // connection deleted. Leaving it off the list is how a connection that
  // failed its test became a dead end instead of a repairable state.
  const options = useMemo(() => {
    const bound = connections.find((c) => c.id === purpose.bound_connection_id);
    if (!bound || eligible.includes(bound)) return eligible;
    return [...eligible, bound];
  }, [connections, purpose.bound_connection_id, eligible]);

  // Nothing chosen, yet the purpose runs: the server's own default model
  // serves it (the verdict is the backend's `usable`, which for an unbound
  // purpose is exactly the env fallback). Saying "not configured" here told
  // an administrator who had set that default that it did not exist.
  const servedByServerDefault =
    purpose.bound_connection_id == null && purpose.usable;

  const handleChange = (value: string) => {
    setBinding.mutate({
      purpose_key: purpose.key,
      connection_id: value === "" ? null : value,
    });
  };

  return (
    <div className="flex flex-col gap-1.5">
      <p className="flex items-center gap-2 text-xs font-medium text-on-muted uppercase tracking-wide">
        {t(purpose.label_key, { defaultValue: purpose.key })}
        {/* Which module asked for this. The purposes read as one flat list,
            so two of them phrased alike gave no way to tell whose setting
            was whose — and this one binding is the only one there is: the
            module's own settings page drives the same value. */}
        {/* /80 blended this 12px label to 3.18:1 — under AA (UI_GUIDELINES
            §6: no opacity de-emphasis on small text). */}
        <span className="normal-case font-medium text-on-muted">
          {
            moduleLabels({
              name: purpose.owner_module,
              display_name: purpose.owner_module,
              description: "",
            }).name
          }
        </span>
        {!available && (
          <Badge variant="secondary">{t("config.purposeUnavailable")}</Badge>
        )}
      </p>
      <p className="text-xs text-on-muted">
        {t(purpose.description_key, { defaultValue: "" })}
      </p>
      <NativeSelect
        aria-label={t(purpose.label_key, { defaultValue: purpose.key })}
        value={purpose.bound_connection_id ?? ""}
        onChange={(e) => handleChange(e.target.value)}
        disabled={setBinding.isPending || !available || !canWriteBinding}
      >
        <option value="">
          {servedByServerDefault
            ? t("config.serverDefaultOption")
            : t("config.noBinding")}
        </option>
        {options.map((connection) => (
          <option key={connection.id} value={connection.id}>
            {optionLabel(connection)}
          </option>
        ))}
      </NativeSelect>
      {available && !canWriteBinding && (
        <p className="text-xs text-on-muted">
          {t("common:access.readOnlyHint")}
        </p>
      )}
      {!available && (
        <p className="text-xs text-on-muted">
          {t("config.purposeUnavailableHint", {
            module: moduleLabels({
              name: purpose.owner_module,
              display_name: purpose.owner_module,
              description: "",
            }).name,
          })}
        </p>
      )}
      {available && failed.length > 0 && (
        // Silently dropping it would leave a connection on the Connections
        // screen that this screen refuses to admit exists.
        <p className="text-xs text-on-warning">
          {t("config.connectionFailedCapability", {
            names: failed.map((c) => c.name).join(", "),
            capability: t(`config.capability.${purpose.capability}`),
          })}
        </p>
      )}
      {available && servedByServerDefault && (
        <p className="text-xs text-on-muted">{t("config.serverDefaultHint")}</p>
      )}
      {available && eligible.length === 0 && !servedByServerDefault && (
        // Saying there is nothing to pick is only half an answer, so the
        // message carries the way to the screen that creates one rather than
        // leaving the reader to find it.
        <p className="text-xs text-on-warning">
          {t("config.noEligibleConnections", {
            capability: t(`config.capability.${purpose.capability}`),
          })}{" "}
          <Link
            to="/settings/ai"
            className="font-semibold underline underline-offset-2 hover:no-underline"
          >
            {t("config.noEligibleConnectionsCta")}
          </Link>
        </p>
      )}
    </div>
  );
}
