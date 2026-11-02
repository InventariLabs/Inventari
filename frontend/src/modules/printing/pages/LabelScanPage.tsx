import { useParams, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  QrCode,
  Scan,
  Package,
  CheckCircle,
  AlertCircle,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { QueryError } from "@/components/ui/QueryResult";
import { apiErrorStatus, isNotFoundError } from "@/lib/errors";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { useLabelScan } from "@/modules/printing/hooks/useLabelScan";

export default function LabelScanPage() {
  const { code } = useParams<{ code: string }>();
  const navigate = useNavigate();
  const location = useLocation();
  const { t } = useTranslation(["labels", "common", "scan"]);
  // The line under the status arrives as a catalogue key and its values —
  // the server cannot know which language the reader holds in their hand.
  const tDynamic = makeTDynamic(t);
  // Assigning a label is creating the product it will name; the label pool
  // rides on `items:write` (a sticker is inventory data). The button used to
  // send a reader to the scan screen, which refuses before the form opens —
  // an offer whose only end is "you can view this, not change it".
  const canWrite = useCanWrite("items");

  const { data, isLoading, error, refetch } = useLabelScan(code!);
  // A printed QR code opens this screen in a fresh tab, as the first entry
  // of its history — popping it did nothing, and the one button on the dead
  // end did not move. With nothing to go back to, Back goes home.
  const goBack = () =>
    location.key !== "default"
      ? navigate(-1)
      : navigate("/", { replace: true });

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface">
        <div className="text-center">
          <Loader2
            className="animate-spin mx-auto mb-4 text-primary-600"
            size={40}
          />
          <p className="text-on-secondary">
            {t("common:messages.loading", { defaultValue: "Loading…" })}
          </p>
        </div>
      </div>
    );
  }

  // This is the one entry a printed QR code has. Telling its reader the label
  // does not exist — and offering to make a new one — when the request merely
  // failed puts a second sticker on a thing that already has one.
  if (error && !isNotFoundError(error)) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface p-6">
        <Card className="max-w-sm w-full p-8">
          <p className="text-on-secondary mb-4 text-center font-mono text-sm">
            {code}
          </p>
          {/* Past the per-minute allowance a retry right away is refused
              again: the reader is told to wait, in the scanner's words. */}
          <QueryError
            onRetry={refetch}
            message={
              apiErrorStatus(error) === 429 ? t("scan:tooManyScans") : undefined
            }
          />
          <div className="text-center">
            <Button variant="outline" onClick={goBack}>
              {t("common:actions.back", { defaultValue: "Go back" })}
            </Button>
          </div>
        </Card>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-surface p-6">
        <Card className="max-w-sm w-full p-8 text-center">
          <AlertCircle className="mx-auto mb-4 text-red-500" size={48} />
          <h2 className="text-xl font-semibold text-on tracking-tight">
            {t("labels:scanNotFound")}
          </h2>
          <p className="text-on-secondary mb-2 font-mono text-sm">{code}</p>
          <p className="text-on-muted text-sm mb-6">
            {t("labels:scanNotFoundDesc", {
              defaultValue:
                "This label code does not exist or belongs to another organization.",
            })}
          </p>
          <Button variant="outline" onClick={goBack}>
            {t("common:actions.back", { defaultValue: "Go back" })}
          </Button>
        </Card>
      </div>
    );
  }

  const isAssigned =
    data.status === "assigned" || data.status === "product_stock";
  const shortCode = data.label_code;

  return (
    <div className="min-h-screen bg-surface flex items-center justify-center p-6">
      <Card className="max-w-sm w-full p-8 text-center shadow-lg">
        <div
          className={`mx-auto mb-6 w-20 h-20 rounded-2xl flex items-center justify-center ${
            isAssigned
              ? "bg-accent-50 text-accent-600"
              : "bg-amber-50 text-amber-600"
          }`}
        >
          {isAssigned ? <Package size={40} /> : <QrCode size={40} />}
        </div>

        <div className="inline-flex items-center gap-2 mb-3">
          {isAssigned ? (
            <CheckCircle size={16} className="text-accent-500" />
          ) : (
            <AlertCircle size={16} className="text-amber-500" />
          )}
          <span
            className={`text-sm font-semibold uppercase tracking-wider ${
              isAssigned ? "text-accent-600" : "text-amber-600"
            }`}
          >
            {isAssigned
              ? t("labels:statusAssigned")
              : t("labels:statusUnassigned", { defaultValue: "Not assigned" })}
          </span>
        </div>

        <p
          className="font-mono text-2xl font-bold text-on mb-2"
          data-testid="label-short-code"
        >
          {shortCode}
        </p>

        {data.item && (
          <p className="text-on-secondary mb-1 font-medium">{data.item.name}</p>
        )}
        {data.message_key && (
          <p className="text-on-muted text-sm mb-6">
            {tDynamic(
              data.message_key,
              (data.message_params ?? {}) as Record<string, unknown>,
            )}
          </p>
        )}

        <div className="flex flex-col gap-3 mt-6">
          {/* "View / Actions" on an assigned label reads the item's quick
              actions; only the unassigned case is a write. */}
          {(isAssigned || canWrite) && (
            <Button
              data-testid="label-assign-btn"
              onClick={() =>
                navigate(
                  `/inventory/scan?code=${encodeURIComponent(shortCode)}`,
                )
              }
              leftIcon={<Scan size={18} />}
            >
              {isAssigned
                ? t("labels:openScanActions", {
                    defaultValue: "View / Actions",
                  })
                : t("labels:assignLabel", { defaultValue: "Assign to item" })}
            </Button>
          )}
          {!isAssigned && !canWrite && <ReadOnlyNotice module="items" />}
          <Button variant="ghost" onClick={() => navigate("/inventory/labels")}>
            {t("labels:viewPool", { defaultValue: "Label pool" })}
          </Button>
        </div>
      </Card>
    </div>
  );
}
