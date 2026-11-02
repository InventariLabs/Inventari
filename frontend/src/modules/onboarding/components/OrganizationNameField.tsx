import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/module-sdk";

/**
 * The name invitations, outgoing mail and printed documents give the
 * organization. Registration only guessed one from the founder's own name, so
 * the setup screen offers it and lets them say what the place is really called.
 *
 * `typed` stays `null` until the reader types, so the field follows the name
 * the server holds (it may still be loading) instead of freezing an empty one.
 */
export function useOrganizationName(registeredName: string | undefined) {
  const [typed, setTyped] = useState<string | null>(null);
  const name = typed ?? registeredName ?? "";
  // A name the reader emptied is refused rather than answered with the name
  // registration guessed from their own: that guess ("<full name>'s
  // Organization") is the thing this field exists to replace. Untouched, the
  // field shows the registered name, so there is always something to send.
  const blank = typed !== null && typed.trim() === "";
  return {
    name,
    setName: setTyped,
    answer: name.trim() || undefined,
    blank,
  };
}

export function OrganizationNameField({
  visible,
  value,
  onChange,
  blank = false,
}: {
  /** Asked with the first choice only; the later steps are about modules. */
  visible: boolean;
  value: string;
  onChange: (value: string) => void;
  /** The reader emptied the field: say so, and the screen will not go on. */
  blank?: boolean;
}) {
  const { t } = useTranslation("onboarding");
  if (!visible) return null;
  return (
    <div className="mt-8 w-full max-w-2xl">
      <Input
        id="onboarding-organization-name"
        label={t("organizationNameLabel")}
        description={t("organizationNameHint")}
        value={value}
        maxLength={255}
        aria-required
        error={blank ? t("organizationNameRequired") : undefined}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}
