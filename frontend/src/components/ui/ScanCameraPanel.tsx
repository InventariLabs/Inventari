import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { RefreshCcw, X } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/utils";

interface ScanCameraPanelProps {
  /** Whether the panel is on screen. The camera itself is the caller's hook. */
  open: boolean;
  scannerError: string | null;
  isCameraActive: boolean;
  isTorchOn: boolean;
  onRetry: () => void;
  onToggleTorch: () => void;
  onClose: () => void;
  /**
   * On a phone, keep the viewfinder in view under the app bar while the page
   * scrolls. For a camera that sits in the page flow; one in a sheet that
   * does not scroll with the page needs nothing.
   */
  pinned?: boolean;
  className?: string;
}

/** The app bar is `h-14` and fixed; the camera pins half a rem under it. */
const PIN_TOP_PX = 64;
const PHONE_QUERY = "(max-width: 767px)";

interface PinBox {
  left: number;
  width: number;
}

/**
 * Where the camera pins once the page has scrolled it up to the bar. A
 * `sticky` box would stop at the end of its parent, which on most screens is
 * a card shorter than the list the worker scans into; so the box is `fixed`
 * instead, and a slot of the same height keeps its place in the flow. Phone
 * only: the notice strip scrolls away there, so the bar is all that covers it
 * (`AppShell`).
 */
function usePinnedBox(enabled: boolean) {
  const slotRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLDivElement>(null);
  const [pin, setPin] = useState<PinBox | null>(null);
  const [height, setHeight] = useState(0);

  useEffect(() => {
    const slot = slotRef.current;
    const box = boxRef.current;
    const phone = window.matchMedia?.(PHONE_QUERY);
    if (!enabled || !slot || !box || !phone) return;
    const measure = () => {
      const rect = slot.getBoundingClientRect();
      setPin(
        phone.matches && rect.top < PIN_TOP_PX
          ? { left: rect.left, width: rect.width }
          : null,
      );
    };
    measure();
    window.addEventListener("scroll", measure, { passive: true });
    window.addEventListener("resize", measure);
    phone.addEventListener?.("change", measure);
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => setHeight(box.offsetHeight));
    observer?.observe(box);
    return () => {
      window.removeEventListener("scroll", measure);
      window.removeEventListener("resize", measure);
      phone.removeEventListener?.("change", measure);
      observer?.disconnect();
      setPin(null);
    };
  }, [enabled]);

  return { slotRef, boxRef, pin, height };
}

/**
 * The drawn camera of every in-page scanner: the reader area, the torch, the
 * refusal and the way back out of it. A caller owns its own `useScanCamera`
 * and its own button; this is only what goes under it, so the stock take, the
 * picking session and the receiving session read the same code the same way.
 */
export function ScanCameraPanel({
  open,
  scannerError,
  isCameraActive,
  isTorchOn,
  onRetry,
  onToggleTorch,
  onClose,
  pinned = false,
  className,
}: ScanCameraPanelProps) {
  const { t } = useTranslation(["scan", "common"]);
  const { slotRef, boxRef, pin, height } = usePinnedBox(pinned && open);

  if (!open) return null;

  const panel = (
    <div
      ref={boxRef}
      style={pin ? { left: pin.left, width: pin.width } : undefined}
      className={cn(
        "relative overflow-hidden rounded-lg border border-border bg-black",
        pin && "fixed top-16 z-[var(--z-sticky)] shadow-lg",
        className,
      )}
    >
      {scannerError ? (
        <div className="space-y-2 px-12 py-4 text-center text-sm text-red-400">
          <p className="break-words">{scannerError}</p>
          <Button variant="secondary" size="sm" onClick={onRetry}>
            <RefreshCcw size={16} className="mr-1" />
            {t("scan:retry")}
          </Button>
        </div>
      ) : (
        <>
          {/* The torch is positioned against the video's own box, not the
              panel: on a wide screen the panel is wider than the square video
              and the button would land on the black beside it. */}
          <div className="relative mx-auto w-full max-w-sm">
            <div id="qr-reader" className="w-full" />
            {isCameraActive && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onToggleTorch}
                className="absolute bottom-2 right-2 bg-black/60 text-white hover:bg-black/70"
              >
                {isTorchOn ? t("scan:torchOff") : t("scan:torchOn")}
              </Button>
            )}
          </div>
          <p className="bg-black py-1.5 text-center text-xs text-gray-400">
            {t("scan:aimAtCode")}
          </p>
        </>
      )}
      <Button
        type="button"
        variant="ghost"
        size="iconSm"
        onClick={onClose}
        aria-label={t("scan:closeCamera")}
        className="absolute top-2 right-2 bg-black/60 text-white hover:bg-black/70"
      >
        <X size={16} />
      </Button>
    </div>
  );

  // The slot is always there when pinned: the box changes class, not place in
  // the tree, so the reader the camera hook draws into is never remounted.
  return pinned ? (
    <div ref={slotRef} style={pin ? { minHeight: height } : undefined}>
      {panel}
    </div>
  ) : (
    panel
  );
}

export default ScanCameraPanel;
