import { Camera, CameraOff } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { ScanCameraPanel } from "@/components/ui/ScanCameraPanel";
import { cn } from "@/lib/utils";
import type { TFunction } from "i18next";

interface ScanModeSectionProps {
  scanMode: boolean;
  cameraOpen: boolean;
  scanValue: string;
  scanFeedback: string | null;
  scanFeedbackTone: "neutral" | "error";
  lineStatusCounts: {
    PENDING: number;
    DONE: number;
    PARTIAL: number;
    EXCEPTION: number;
  };
  scanTargetLine: {
    id: string;
    name?: string | null;
    barcode?: string | null;
  } | null;
  nextIncompleteLine: {
    id: string;
    name?: string | null;
    barcode?: string | null;
  } | null;
  scannerError: string | null;
  isCameraActive: boolean;
  isTorchOn: boolean;
  onToggleScanMode: () => void;
  onCameraToggle: () => void;
  onScanValueChange: (value: string) => void;
  onApplyScan: () => void;
  onToggleTorch: () => void;
  onRetryCamera: () => void;
  t: TFunction;
}

function getLineDisplayName(line: {
  name?: string | null;
  barcode?: string | null;
  id: string;
}): string {
  return line.name?.trim() || line.barcode || line.id;
}

export function ScanModeSection({
  scanMode,
  cameraOpen,
  scanValue,
  scanFeedback,
  scanFeedbackTone,
  lineStatusCounts,
  scanTargetLine,
  nextIncompleteLine,
  scannerError,
  isCameraActive,
  isTorchOn,
  onToggleScanMode,
  onCameraToggle,
  onScanValueChange,
  onApplyScan,
  onToggleTorch,
  onRetryCamera,
  t,
}: ScanModeSectionProps) {
  return (
    <div className="rounded-xl border border-border bg-surface-card p-4 space-y-3">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <div className="text-sm font-medium text-on">
            {t("warehouse:detail.scanModeTitle")}
          </div>
          <p className="text-xs text-on-secondary">
            {scanMode
              ? t("warehouse:detail.scanModeHelpActive")
              : t("warehouse:detail.scanModeHelpIdle")}
          </p>
        </div>
        <Button
          type="button"
          className="self-end sm:self-auto"
          variant={scanMode ? "primary" : "outline"}
          size="sm"
          onClick={onToggleScanMode}
        >
          {scanMode
            ? t("warehouse:detail.scanModeExit")
            : t("warehouse:detail.scanMode")}
        </Button>
      </div>

      {scanMode && (
        <div className="space-y-3">
          {/* On a phone the bar pins under the app bar (56 px), and not while
              the camera is open: the camera pins there instead, and two boxes
              on one spot would cover each other. */}
          <div
            className={cn(
              "z-10 -mx-1 rounded-xl border border-border bg-surface-card/95 p-3 shadow-sm backdrop-blur supports-[backdrop-filter]:bg-surface-card/85 sm:static sm:mx-0 sm:border-0 sm:bg-transparent sm:p-0 sm:shadow-none sm:backdrop-blur-0",
              !cameraOpen && "sticky top-16",
            )}
          >
            <div className="flex flex-col gap-2 sm:flex-row sm:items-end">
              <Input
                id="document-execution-scan"
                type="text"
                label={t("warehouse:detail.scanInputLabel")}
                placeholder={t("warehouse:detail.scanInputPlaceholder")}
                value={scanValue}
                onChange={(event) => onScanValueChange(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    onApplyScan();
                  }
                }}
                autoComplete="off"
                wrapperClassName="sm:flex-1"
              />
              <Button type="button" onClick={onApplyScan} className="sm:mb-px">
                {t("warehouse:detail.scanApply")}
              </Button>
              <Button
                type="button"
                variant={cameraOpen ? "primary" : "outline"}
                onClick={onCameraToggle}
                className="sm:mb-px"
                leftIcon={
                  cameraOpen ? <CameraOff size={16} /> : <Camera size={16} />
                }
              >
                {cameraOpen
                  ? t("warehouse:detail.cameraClose")
                  : t("warehouse:detail.cameraOpen")}
              </Button>
            </div>

            {scanFeedback && (
              <p
                role="status"
                aria-live="polite"
                className={
                  scanFeedbackTone === "error"
                    ? "mt-3 text-sm font-medium text-red-600"
                    : "mt-3 text-sm text-on-secondary"
                }
              >
                {scanFeedback}
              </p>
            )}

            <div className="mt-3 flex flex-wrap gap-2">
              <Badge variant="success">
                {t("warehouse:detail.summaryDone", {
                  count: lineStatusCounts.DONE,
                })}
              </Badge>
              {lineStatusCounts.PENDING > 0 && (
                <Badge variant="secondary">
                  {t("warehouse:detail.summaryPending", {
                    count: lineStatusCounts.PENDING,
                  })}
                </Badge>
              )}
              {lineStatusCounts.PARTIAL > 0 && (
                <Badge variant="info">
                  {t("warehouse:detail.summaryPartial", {
                    count: lineStatusCounts.PARTIAL,
                  })}
                </Badge>
              )}
              {lineStatusCounts.EXCEPTION > 0 && (
                <Badge variant="warning">
                  {t("warehouse:detail.summaryExceptions", {
                    count: lineStatusCounts.EXCEPTION,
                  })}
                </Badge>
              )}
            </div>

            {scanTargetLine && nextIncompleteLine && (
              <div className="mt-3 rounded-lg border border-primary-200 bg-primary-50 px-3 py-2 text-sm text-primary-900">
                {nextIncompleteLine.id === scanTargetLine.id
                  ? t("warehouse:detail.scanContinueLine", {
                      name: getLineDisplayName(scanTargetLine),
                    })
                  : t("warehouse:detail.scanNextLine", {
                      name: getLineDisplayName(nextIncompleteLine),
                    })}
              </div>
            )}

            {scanTargetLine && !nextIncompleteLine && (
              <div className="mt-3 rounded-lg border border-accent-200 bg-accent-50 px-3 py-2 text-sm text-accent-900">
                {t("warehouse:detail.scanAllDone")}
              </div>
            )}
          </div>

          <ScanCameraPanel
            open={cameraOpen}
            pinned
            scannerError={scannerError}
            isCameraActive={isCameraActive}
            isTorchOn={isTorchOn}
            onRetry={onRetryCamera}
            onToggleTorch={onToggleTorch}
            onClose={onCameraToggle}
          />
        </div>
      )}
    </div>
  );
}
