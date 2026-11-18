import { useState } from "react";

import { useAutoResetFlag } from "@/hooks/useAutoResetFlag";
import { useTranslation } from "react-i18next";
import { Check, Copy, Mail } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { copyText } from "@/lib/clipboard";
import { Sheet } from "@/components/ui/Sheet";

interface InviteLinkDialogProps {
  /** The address the invitation was issued for. */
  email: string;
  link: string;
  onClose: () => void;
}

/**
 * The invitation link, shown deliberately.
 *
 * It is shown in a dialog rather than a panel under the form, so a refresh
 * cannot take it away without notice. The same shape as the API-key dialog:
 * one habit to learn for "here is something you have to carry somewhere
 * yourself", not two.
 *
 * The hint says what is true: the invitation's row menu offers Copy link and
 * the API returns the code for as long as the invitation is pending.
 */
export default function InviteLinkDialog({
  email,
  link,
  onClose,
}: InviteLinkDialogProps) {
  const { t } = useTranslation("common");
  const [copied, copy] = useAutoResetFlag(2000);
  // This link is the only way to a second user in an organization that
  // sends no mail, so a copy that did not land has to say how to carry it
  // by hand rather than change the button and say nothing.
  const [failed, setFailed] = useState(false);

  const handleCopy = async () => {
    if ((await copyText(link)) === "copied") {
      setFailed(false);
      copy();
    } else {
      setFailed(true);
    }
  };

  return (
    <Sheet
      open
      onClose={onClose}
      maxWidth="md"
      aria-label={t("settings.organization.inviteLinkTitle")}
    >
      <div className="flex items-center gap-3 p-5 border-b border-border">
        <div className="w-9 h-9 rounded-xl bg-primary-50 dark:bg-primary-500/15 flex items-center justify-center shrink-0">
          <Mail size={18} className="text-on-primary" />
        </div>
        <h2 className="text-base font-semibold text-on">
          {t("settings.organization.inviteLinkTitle")}
        </h2>
      </div>

      <div className="p-5 space-y-4 flex-1 overflow-y-auto">
        <p className="text-sm text-on-secondary">
          {t("settings.organization.inviteLinkHint", { email })}
        </p>

        <div className="space-y-2">
          <div className="w-full rounded-xl bg-surface-inset border border-border px-4 py-3 min-h-[56px] flex items-center">
            <code className="text-sm font-mono text-on break-all select-all leading-relaxed">
              {link}
            </code>
          </div>
          <Button
            variant="outline"
            className="w-full"
            onClick={() => void handleCopy()}
            leftIcon={
              copied ? (
                <Check size={16} className="text-accent-500" />
              ) : (
                <Copy size={16} />
              )
            }
          >
            {copied
              ? t("settings.organization.inviteLinkCopied")
              : t("settings.organization.inviteLinkCopy")}
          </Button>
          {failed && (
            <p
              data-testid="copy-link-manual-hint"
              className="text-xs text-on-warning"
            >
              {t("copy.selectManually")}
            </p>
          )}
        </div>
      </div>

      <div className="px-5 pb-5">
        <Button variant="primary" className="w-full" onClick={onClose}>
          {t("settings.organization.inviteLinkDone")}
        </Button>
      </div>
    </Sheet>
  );
}
