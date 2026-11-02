import { useTranslation } from "react-i18next";
import { Eye } from "lucide-react";

import { useCanManage, useCanWrite } from "@/hooks/useCanWrite";
import { useHasPermission } from "@/hooks/useHasPermission";

interface ReadOnlyNoticeProps {
  /** Backend module name — the namespace its permission keys live under. */
  module: string;
  /**
   * The exact key to ask about, when the screen is not guarded by its own
   * module's `:write`.
   *
   * Two screens are not: the API keys list is guarded by
   * `org:settings:write`, because issuing a key that can act as the
   * organization is an organization setting rather than something the module
   * owns; the approval workflows are guarded by `approvals:configure`, which
   * that module declares alongside a `:write` meaning something else
   * entirely. Naming the key here is what keeps the notice and the endpoint
   * asking the same question — `module` still says whose screen it is.
   */
  permission?: string;
  /**
   * Which right the hidden actions needed.
   *
   * `write` is the ordinary case: this account may not change the records.
   * `manage` is the narrower one — it may change the records but not how the
   * module behaves — and only modules declaring a `:manage` key have it.
   */
  right?: "write" | "manage";
}

/**
 * One line saying why this screen has no buttons on it.
 *
 * Hiding the write actions from an account that may not write is only half an
 * answer. A list that used to carry "Add", "Import" and eight bulk actions and
 * now carries none reads as a broken page, not as a boundary — the reader has
 * no way to tell "you may not" from "it failed to load". So a module page that
 * hides its actions says this instead, in the same words the module settings
 * screen already uses for the same situation.
 *
 * Renders nothing for an account that holds the right, which is what lets a
 * page place it unconditionally.
 */
export function ReadOnlyNotice({
  module,
  right = "write",
  permission,
}: ReadOnlyNoticeProps) {
  const { t } = useTranslation("common");
  const canWrite = useCanWrite(module);
  const canManage = useCanManage(module);
  // Hooks cannot be called conditionally, so the explicit key is always
  // asked about and only consulted when one was given.
  const holdsExplicit = useHasPermission(permission ?? `${module}:write`);

  const granted = permission
    ? holdsExplicit
    : right === "manage"
      ? canManage
      : canWrite;
  if (granted) return null;

  const title =
    right === "manage"
      ? t("settings.moduleSettings.forbidden")
      : t("access.readOnly");
  const hint =
    right === "manage"
      ? t("settings.moduleSettings.forbiddenHint")
      : t("access.readOnlyHint");

  return (
    <div
      className="flex items-start gap-2 rounded-xl bg-surface-inset px-4 py-3 text-on-secondary"
      role="note"
    >
      <Eye size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div>
        <p className="text-sm font-medium text-on">{title}</p>
        <p className="text-sm">{hint}</p>
      </div>
    </div>
  );
}
