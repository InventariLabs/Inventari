import { useCallback, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

/**
 * Says the work is kept when a scan session's screen goes away with the
 * session still open — the close button, Escape, the browser's back arrow or
 * any route change alike — and calls *onLeave*, which pauses the session so
 * it stops holding its document. Nothing is put back by leaving; the next
 * start hands the session back, to whoever opens the document.
 *
 * `phase` is the session's phase and `openPhases` those in which it is in
 * progress. Resetting to "idle" is how the screen's own close tidies up, so it
 * says nothing about whether the session ended; the phases that did end it
 * (completed, cancelled) disarm the notice, and so does the returned function,
 * which the exit that discards the scans calls before it resets.
 */
export function useLeftOpenNotice(
  phase: string,
  openPhases: readonly string[],
  onLeave?: () => void,
) {
  const { t } = useTranslation("warehouse");
  const armed = useRef(false);
  const message = useRef("");
  const leave = useRef(onLeave);
  useEffect(() => {
    leave.current = onLeave;
  }, [onLeave]);
  useEffect(() => {
    if (phase !== "idle") armed.current = openPhases.includes(phase);
  }, [phase, openPhases]);
  useEffect(() => {
    message.current = t("scanSession.leftOpen");
  }, [t]);
  useEffect(
    () => () => {
      if (!armed.current) return;
      toast(message.current);
      leave.current?.();
    },
    [],
  );
  return useCallback(() => {
    armed.current = false;
  }, []);
}
