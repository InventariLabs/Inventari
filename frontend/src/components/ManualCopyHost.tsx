import { useEffect, useRef, useSyncExternalStore } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Sheet } from "@/components/ui/Sheet";
import { manualCopyStore } from "@/lib/clipboard";

/**
 * Where a copy the browser refused ends up: the text, selected, in a field
 * the reader can copy from with Ctrl+C.
 *
 * Mounted once at the root, because `copyTextOrExplain` is called from
 * components, hooks and module registrations alike and none of them owns a
 * place on the screen for a value they do not otherwise show.
 */
export default function ManualCopyHost() {
  const { t } = useTranslation("common");
  const pending = useSyncExternalStore(
    manualCopyStore.subscribe,
    manualCopyStore.get,
  );
  const field = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    field.current?.select();
  }, [pending]);

  return (
    <Sheet
      open={pending !== null}
      onClose={manualCopyStore.dismiss}
      maxWidth="md"
      zIndex="confirm"
      aria-label={t("copy.manualTitle")}
    >
      <div className="p-5 space-y-3">
        <h2 className="text-base font-semibold text-on">
          {t("copy.manualTitle")}
        </h2>
        <p className="text-sm text-on-secondary">{pending?.message}</p>
        <textarea
          ref={field}
          readOnly
          rows={Math.min(10, (pending?.text.split("\n").length ?? 1) + 1)}
          aria-label={t("copy.manualTitle")}
          data-testid="manual-copy-value"
          value={pending?.text ?? ""}
          onFocus={(e) => e.currentTarget.select()}
          className="w-full rounded-xl bg-surface-inset border border-border px-3 py-2 text-sm font-mono text-on break-all"
        />
        <Button
          variant="primary"
          className="w-full"
          onClick={manualCopyStore.dismiss}
        >
          {t("copy.manualDone")}
        </Button>
      </div>
    </Sheet>
  );
}
