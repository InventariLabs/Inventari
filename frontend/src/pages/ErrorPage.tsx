import { useRouteError, isRouteErrorResponse, Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { logger } from "@/utils/logger";
import { AlertTriangle } from "lucide-react";
import ErrorDetails from "@/components/ErrorDetails";
import { isStaleChunkError } from "@/lib/staleChunk";
import { Button, buttonVariants } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

/**
 * The screen named by the route tree's `errorElement`.
 *
 * Every string here used to be an English literal — an h1, a sentence and a
 * way back — so the one moment the application owed the reader an explanation
 * was the one moment it stopped speaking their language. The three keys are
 * the ones the error boundary already uses for the same three jobs; a second
 * set of words for one situation is how two screens end up describing one
 * failure differently.
 *
 * The wiring is worth knowing while reading this: `errorElement` is armed
 * only by a *data* router, and the route tree in `App.tsx` mounts one — every
 * top-level route is handed this screen by `createAppRoutes`. It used to sit
 * on a declarative `<BrowserRouter>`, where the attribute was never armed and
 * a render error in a route went to the boundary in `main.tsx` instead.
 */
export default function ErrorPage() {
  const { t } = useTranslation("common");
  const error = useRouteError();
  // A chunk that went missing behind a deploy is the app being out of date,
  // not a defect: it gets a sentence and a reload, not a bug report.
  const stale = isStaleChunkError(error);
  if (!stale) logger.error(error);

  return (
    <div
      data-testid="app-error"
      className="flex flex-col items-center justify-center min-h-screen bg-surface p-4 text-center"
    >
      <div className="bg-surface-card p-8 rounded-3xl shadow-md max-w-md w-full flex flex-col items-center">
        <div className="w-16 h-16 bg-red-100 text-red-600 rounded-full flex items-center justify-center mb-6">
          <AlertTriangle size={32} />
        </div>
        <h1 className="text-2xl font-semibold text-on mb-2">
          {t(stale ? "errors.newVersionTitle" : "errors.somethingWentWrong")}
        </h1>
        <p className="text-on-secondary mb-6">
          {stale
            ? t("errors.newVersionBody")
            : isRouteErrorResponse(error)
              ? `${error.status} ${error.statusText}`
              : t("errors.unexpectedError")}
        </p>
        <div className="flex flex-col gap-3 w-full">
          <Button
            size="lg"
            className="w-full"
            onClick={() => window.location.reload()}
          >
            {t("errors.reloadPage")}
          </Button>
          <Link
            to="/"
            className={cn(
              buttonVariants({ variant: "outline", size: "lg" }),
              "w-full",
            )}
          >
            {t("errors.goHome")}
          </Link>
        </div>
      </div>
      {!stale && <ErrorDetails error={error} />}
    </div>
  );
}
