import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useAuthStore } from "@/store/authStore";

/**
 * The public forms (forgot password, reset, request access) are for people
 * who are not signed in. Opened on a device with a live session they used to
 * look exactly as they do for a stranger, as though nothing were signed in.
 * Say whose session this is and offer both ways on: back into the app, or
 * out of the session when the form really is meant for someone else.
 */
export function SignedInNotice() {
  const { t } = useTranslation("auth");
  const signedIn = useAuthStore((state) => state.user);
  const logout = useAuthStore((state) => state.logout);
  if (!signedIn) return null;
  return (
    <div
      role="status"
      data-testid="signed-in-notice"
      className="mb-4 flex flex-col items-start gap-2 rounded-lg border border-border bg-surface-raised p-3 text-sm text-on-secondary"
    >
      <p>{t("signedInHere", { email: signedIn.email })}</p>
      <div className="flex flex-wrap items-center gap-3">
        <Link
          to="/"
          className="inline-flex min-h-11 items-center font-medium text-primary-600 hover:underline md:min-h-0"
        >
          {t("signedInContinue")}
        </Link>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => void logout()}
        >
          {t("signOutFirst")}
        </Button>
      </div>
    </div>
  );
}
