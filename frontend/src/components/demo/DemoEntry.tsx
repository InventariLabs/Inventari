import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { DemoSandboxFailure } from "@/lib/demoSandboxFailure";
import { DemoSandboxFailureText } from "./DemoSandboxFailureText";

interface DemoEntryProps {
  onTry: () => void;
  isOpening: boolean;
  /** Why the last attempt was refused, said plainly. */
  failure: DemoSandboxFailure | null;
}

/**
 * The public demo's way in: an organization of the visitor's own, one click.
 *
 * Above the sign-in form, which stays for the operator's own account.
 */
export function DemoEntry({ onTry, isOpening, failure }: DemoEntryProps) {
  const { t } = useTranslation("auth");

  return (
    <section aria-labelledby="demo-entry-title" className="mb-8 space-y-3">
      <h2
        id="demo-entry-title"
        className="text-xl font-semibold text-on leading-none"
      >
        {t("demo.title")}
      </h2>
      <p className="text-sm text-on-muted">{t("demo.intro")}</p>
      <Button
        size="content"
        type="button"
        onClick={onTry}
        disabled={isOpening}
        isLoading={isOpening}
        leftIcon={<Sparkles size={16} aria-hidden="true" />}
        className="w-full h-12 text-base font-semibold tracking-tight"
      >
        {t("demo.button")}
      </Button>
      {failure && (
        <p
          role="status"
          className="rounded-lg bg-amber-50 px-3 py-2.5 text-sm text-on-warning"
        >
          <DemoSandboxFailureText failure={failure} />
        </p>
      )}
      <p className="pt-3 text-center text-xs font-medium text-on-muted">
        {t("demo.orSignIn")}
      </p>
    </section>
  );
}
