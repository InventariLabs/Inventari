import { lazy, Suspense, useState } from "react";
import { useTranslation } from "react-i18next";
import { Sparkles } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import LoadingSpinner from "@/components/LoadingSpinner";
import { useConfirm } from "@/hooks/useConfirm";
import { useInitStatus } from "@/hooks/useInitStatus";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { authApi } from "@/lib/api/auth";
import {
  demoSandboxFailure,
  type DemoSandboxFailure,
} from "@/lib/demoSandboxFailure";
import { useScanStore } from "@/store/scanStore";
import { DemoSandboxFailureText } from "./DemoSandboxFailureText";

/** Opened only when the banner's button is pressed, so the sheet's code
 *  stays out of the entry chunk the bundle budget guards — the click pays
 *  for its own chunk, the signed-out visitor pays nothing. */
const DemoLabelSheet = lazy(() =>
  import("./DemoLabelSheet").then((m) => ({ default: m.DemoLabelSheet })),
);

/**
 * The public demo, said once above every screen: what the visitor is in, how
 * long it lasts, where its mail lands, the sheet of labels the visitor
 * prints and scans, and the way to a fresh copy. The strip sits above the
 * welcome and above the warehouse alike, so the sheet is one click away
 * from either, in focus mode included — which is what makes it a way in
 * rather than a place to find.
 *
 * Starting over takes a new organization off the pool and loads the app
 * again on it — a full load rather than a route change, so nothing cached in
 * memory for the organization being left behind survives into the new one.
 * What the browser keeps on disk is cleared in `startOver` itself.
 */
export function DemoSandboxNotice() {
  const { t, i18n } = useTranslation("auth");
  const { data: initStatus } = useInitStatus();
  const { confirm, confirmDialogProps } = useConfirm();
  const [isStarting, setIsStarting] = useState(false);
  const [failure, setFailure] = useState<DemoSandboxFailure | null>(null);
  const [labelSheet, setLabelSheet] = useState(false);
  // On a phone the strip is two lines — a sentence and the three actions —
  // because three lines of it above every screen pushed the launcher's first
  // row of tiles off an 844px viewport.
  const isPhone = useMediaQuery("(max-width: 639px)");

  if (!initStatus?.is_demo) return null;

  const demoInboxUrl = initStatus.demo_inbox_url;

  const startOver = async () => {
    const confirmed = await confirm({
      title: t("demo.startOverTitle"),
      message: t("demo.startOverMessage"),
      confirmLabel: t("demo.startOverConfirm"),
    });
    if (!confirmed) return;
    setIsStarting(true);
    setFailure(null);
    try {
      await authApi.openDemoSandbox(true, i18n.language.substring(0, 2));
      // The sandbox just opened is another organization, and the reload
      // below never runs the sign-out teardown that takes the scanner's
      // remembered shelf with the identity: without this the fresh copy
      // opens still showing the shelf of the one left behind.
      useScanStore.getState().clear();
      window.location.assign("/launcher");
    } catch (error: unknown) {
      setFailure(demoSandboxFailure(error));
      setIsStarting(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 bg-blue-50 px-3 py-1 text-xs text-on-info">
      <Sparkles size={14} className="shrink-0" aria-hidden="true" />
      <p role="status" className="min-w-0 grow basis-64">
        {failure ? (
          <DemoSandboxFailureText failure={failure} />
        ) : isPhone ? (
          t("demo.noticeShort")
        ) : (
          <>
            {t("demo.notice")} {demoInboxUrl && t("demo.inboxNotice")}
          </>
        )}
      </p>
      {demoInboxUrl && !failure && (
        <a
          href={demoInboxUrl}
          target="_blank"
          rel="noopener noreferrer"
          className="whitespace-nowrap font-medium underline decoration-2 underline-offset-4"
        >
          {isPhone ? t("demo.inboxLinkShort") : t("demo.inboxLink")}
        </a>
      )}
      <Button
        variant="ghost"
        size="sm"
        onClick={() => setLabelSheet(true)}
        className="px-1.5 text-on-info underline decoration-2 underline-offset-4 sm:px-3"
      >
        {t("demo.labelSheet")}
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={startOver}
        isLoading={isStarting}
        disabled={isStarting}
        className="px-1.5 text-on-info underline decoration-2 underline-offset-4 sm:px-3"
      >
        {t("demo.startOver")}
      </Button>
      {labelSheet && (
        <Suspense fallback={<LoadingSpinner fullScreen />}>
          <DemoLabelSheet onClose={() => setLabelSheet(false)} />
        </Suspense>
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
