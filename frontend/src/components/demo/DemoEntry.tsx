import { useTranslation } from "react-i18next";
import { ChevronDown, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import type { DemoSandboxFailure } from "@/lib/demoSandboxFailure";
import { DemoSandboxFailureText } from "./DemoSandboxFailureText";

/** The id of the sign-in form the entry's toggle opens and closes. */
export const ACCOUNT_FORM_ID = "account-sign-in";

interface DemoEntryProps {
  onTry: () => void;
  isOpening: boolean;
  /** Why the last attempt was refused, said plainly. */
  failure: DemoSandboxFailure | null;
  accountFormOpen: boolean;
  onToggleAccountForm: () => void;
}

/**
 * The public demo's way in: an organization of the visitor's own, one click.
 *
 * Its button is the page's one main action; the sign-in form for the
 * operator's own account opens from the line beneath it.
 */
export function DemoEntry({
  onTry,
  isOpening,
  failure,
  accountFormOpen,
  onToggleAccountForm,
}: DemoEntryProps) {
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
      <button
        type="button"
        onClick={onToggleAccountForm}
        aria-expanded={accountFormOpen}
        aria-controls={ACCOUNT_FORM_ID}
        className="mx-auto mt-3 flex min-h-11 items-center gap-1.5 text-xs font-medium text-on-muted hover:text-on md:min-h-0"
      >
        {t("demo.orSignIn")}
        <ChevronDown
          size={18}
          aria-hidden="true"
          className={accountFormOpen ? "rotate-180" : undefined}
        />
      </button>
    </section>
  );
}
