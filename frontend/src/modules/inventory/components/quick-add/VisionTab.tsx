import { useState } from "react";
import { Link } from "react-router-dom";
import { Camera, Edit, ImageOff, Plus, RefreshCw, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import {
  isVisionConfigured,
  useAiPurposes,
} from "@/modules/settings/hooks/useAiConnections";

interface VisionTabProps {
  /** Resolves true when the reading found nothing on the photos. */
  onAnalyze: (files: File[]) => Promise<boolean>;
  /** Leaves the camera for the form. */
  onEnterManually: () => void;
  isAnalyzing: boolean;
}

export function VisionTab({
  onAnalyze,
  onEnterManually,
  isAnalyzing,
}: VisionTabProps) {
  // Only a registry that ANSWERED rules the sentences — the same rule the
  // recipe import tab states over its own registry read: answered and
  // bound, the promise; answered and unbound, the how-to, a door to
  // Settings and a camera that does not lead into the backend's refusal;
  // unanswered, neither sentence, because a promise would be a guess and
  // a refusal a lie.
  const { data: purposes, isSuccess: registryAnswered } = useAiPurposes();
  const visionConfigured = registryAnswered && isVisionConfigured(purposes);
  const { t } = useTranslation(["labels", "scan", "common"]);
  const [selectedFiles, setSelectedFiles] = useState<File[]>([]);
  const [imagePreviews, setImagePreviews] = useState<string[]>([]);
  // The very photos a reading found nothing on. Adding, removing or clearing
  // one makes a new list, so the sentence about them retires by itself.
  const [readNothingOn, setReadNothingOn] = useState<File[] | null>(null);
  const readNothing = readNothingOn === selectedFiles;

  const analyze = async () => {
    const files = selectedFiles;
    if (await onAnalyze(files)) setReadNothingOn(files);
  };

  const clearPhotos = () => {
    setSelectedFiles([]);
    setImagePreviews([]);
  };

  const addPhoto = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = "image/*";
    input.capture = "environment";
    input.onchange = (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (file) {
        setSelectedFiles((p) => [...p, file]);
        const reader = new FileReader();
        reader.onload = (ev) => {
          if (typeof ev.target?.result === "string") {
            setImagePreviews((p) => [...p, ev.target?.result as string]);
          }
        };
        reader.readAsDataURL(file);
      }
    };
    input.click();
  };

  return (
    <div className="space-y-6 py-2">
      {imagePreviews.length === 0 ? (
        <div className="space-y-6">
          {/* A camera, not a QR code: this feature photographs the product.
              The app has a separate barcode scanner in the bottom navigation,
              and the QR illustration pointed at that one. */}
          <div className="w-20 h-20 bg-primary-50 rounded-full flex items-center justify-center mx-auto text-primary-600">
            <Camera size={40} />
          </div>
          <div className="text-center">
            <h4 className="font-semibold text-on">
              {t("labels:quickAdd.visionTitle")}
            </h4>
            {registryAnswered && (
              <p className="text-sm text-on-secondary mt-2">
                {visionConfigured
                  ? t("labels:quickAdd.visionHelp")
                  : t("labels:quickAdd.visionHelpNoAi")}
              </p>
            )}
            {registryAnswered && !visionConfigured && (
              <Link
                to="/settings/ai"
                className="inline-flex items-center gap-1 text-sm font-medium text-on-primary hover:underline mt-1"
              >
                {t("labels:quickAdd.visionSettingsLink")}
              </Link>
            )}
          </div>
          <Button
            size="content"
            type="button"
            variant="default"
            onClick={addPhoto}
            // An answered-but-unbound registry means every read ends in the
            // backend's refusal — the invitation stops here, next to the
            // sentence that says why. An unanswered registry leaves the
            // camera alone: the backend may well work.
            disabled={registryAnswered && !visionConfigured}
            className="w-full gap-3 px-6 py-4 rounded-2xl font-semibold"
          >
            <Camera size={24} />
            {t("labels:quickAdd.takePhoto")}
          </Button>
        </div>
      ) : (
        <div className="space-y-6">
          <div className="grid grid-cols-3 gap-2">
            {imagePreviews.map((preview, idx) => (
              <div key={idx} className="relative">
                <img
                  src={preview}
                  className="aspect-square w-full object-cover rounded-xl border border-border shadow-sm"
                  alt={t("common:a11y.imagePreview")}
                  loading="lazy"
                />
                {/* ui-pattern: filled-destructive — a remove chip sitting on
                    the photo itself, where a ghost button would disappear
                    into whichever picture the user happened to take */}
                <Button
                  variant="destructive"
                  size="inline"
                  onClick={() => {
                    setSelectedFiles((p) => p.filter((_, i) => i !== idx));
                    setImagePreviews((p) => p.filter((_, i) => i !== idx));
                  }}
                  aria-label={t("common:actions.remove")}
                  className="absolute -top-1 -right-1 h-5 w-5 p-0 rounded-full border border-white shadow-lg"
                >
                  <X size={10} />
                </Button>
              </div>
            ))}
            {imagePreviews.length < 5 && (
              <Button
                size="content"
                type="button"
                variant="outline"
                onClick={addPhoto}
                className="aspect-square w-full flex-col rounded-xl border border-dashed border-border bg-transparent text-on-muted hover:bg-surface min-h-11 md:min-h-0 min-w-11 md:min-w-0"
              >
                <Plus size={20} />
                <span className="text-[10px] font-medium uppercase mt-1">
                  {t("common:actions.add", { defaultValue: "Add" })}
                </span>
              </Button>
            )}
          </div>

          {readNothing && (
            <div
              role="status"
              className="flex items-start gap-2 rounded-xl bg-surface-inset px-4 py-3 text-on-secondary"
            >
              <ImageOff
                size={18}
                className="mt-0.5 shrink-0"
                aria-hidden="true"
              />
              <div className="space-y-3">
                <div>
                  <p className="text-sm font-medium text-on">
                    {t("labels:quickAdd.visionReadNothing")}
                  </p>
                  <p className="text-sm">
                    {t("labels:quickAdd.visionReadNothingHint")}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    leftIcon={<Camera size={16} />}
                    onClick={() => {
                      clearPhotos();
                      addPhoto();
                    }}
                  >
                    {t("labels:quickAdd.retakePhoto")}
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    leftIcon={<Edit size={16} />}
                    onClick={onEnterManually}
                  >
                    {t("labels:quickAdd.enterManually")}
                  </Button>
                </div>
              </div>
            </div>
          )}

          <div className="flex gap-3">
            <Button
              size="content"
              type="button"
              variant="outline"
              onClick={clearPhotos}
              className="flex-1 border py-4 rounded-2xl font-semibold bg-transparent hover:bg-surface"
            >
              {t("common:actions.clear")}
            </Button>
            <Button
              size="content"
              type="button"
              variant="default"
              onClick={analyze}
              disabled={isAnalyzing || selectedFiles.length === 0}
              className="flex-[2] gap-3 py-4 rounded-2xl font-semibold"
            >
              {isAnalyzing ? (
                <RefreshCw size={24} className="animate-spin" />
              ) : (
                <Camera size={24} />
              )}
              {isAnalyzing
                ? t("labels:quickAdd.analyzing")
                : `${t("scan:analyze", { defaultValue: "Analyze" })} (${imagePreviews.length})`}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
