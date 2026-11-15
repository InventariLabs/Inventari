import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Camera, File, Loader2, Paperclip, Trash2, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { QueryFailure } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import { extractApiError } from "@/lib/errors";
import { formatBytes } from "@/utils/formatters";
import { ATTACHMENT_FILE_ACCEPT } from "@/module-sdk";
import { useRunAttachments } from "@/modules/maker/hooks/useBatches";
import type { ProductionAttachment } from "@/modules/maker/types/maker";

/** Only a path on this app's own origin is a link: `/uploads/...`. */
function ownHref(url: string): string | null {
  if (!url.startsWith("/")) return null;
  try {
    const here = window.location.origin;
    return new URL(url, here).origin === here ? url : null;
  } catch {
    return null;
  }
}

/**
 * The photos and files filed under a run — the filled jars, a thermometer
 * reading, a certificate — with the limits a product's attachments have.
 */
export function RunAttachmentsSection({ orderId }: { orderId: string }) {
  const { t } = useTranslation("maker");
  const canWrite = useCanWrite("maker");
  const { list, upload, remove } = useRunAttachments(orderId);
  const fileInput = useRef<HTMLInputElement>(null);
  const [doomed, setDoomed] = useState<ProductionAttachment | null>(null);
  const files = list.data ?? [];

  async function onPick(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (fileInput.current) fileInput.current.value = "";
    if (!file) return;
    try {
      await upload.mutateAsync(file);
      toast.success(t("attachments.uploaded"));
    } catch (error) {
      toast.error(extractApiError(error, t("attachments.uploadFailed")));
    }
  }

  async function onDelete(attachment: ProductionAttachment) {
    try {
      await remove.mutateAsync(attachment.id);
      toast.success(t("attachments.deleted"));
    } catch (error) {
      toast.error(extractApiError(error, t("attachments.deleteFailed")));
    }
  }

  return (
    <Card data-testid="maker-run-attachments">
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <CardTitle className="text-sm flex items-center gap-2">
          <Paperclip size={14} />
          {t("attachments.title")}
          {files.length > 0 && (
            <span className="text-xs text-on-muted font-normal">
              ({files.length})
            </span>
          )}
        </CardTitle>
        {canWrite && (
          <>
            <input
              ref={fileInput}
              type="file"
              className="hidden"
              accept={ATTACHMENT_FILE_ACCEPT}
              onChange={onPick}
              aria-label={t("attachments.upload")}
              data-testid="maker-run-attachment-input"
            />
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Upload size={14} />}
              onClick={() => fileInput.current?.click()}
              isLoading={upload.isPending}
            >
              {t("attachments.upload")}
            </Button>
          </>
        )}
      </CardHeader>
      <CardContent>
        {list.isError ? (
          <QueryFailure error={list.error} onRetry={() => list.refetch()} />
        ) : list.isLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="animate-spin text-on-muted" />
          </div>
        ) : files.length === 0 ? (
          <p className="text-xs text-on-muted text-center py-4">
            {t("attachments.empty")}
          </p>
        ) : (
          <ul className="space-y-2">
            {files.map((file) => {
              const href = ownHref(file.url);
              const icon = file.content_type.startsWith("image/") ? (
                <Camera size={16} className="text-on-muted" />
              ) : (
                <File size={16} className="text-on-muted" />
              );
              return (
                <li
                  key={file.id}
                  className="flex items-center gap-3 p-2 rounded-lg"
                >
                  {icon}
                  <div className="flex-1 min-w-0">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-sm font-medium text-primary-700 hover:underline truncate block"
                      >
                        {file.original_name}
                      </a>
                    ) : (
                      <p className="text-sm font-medium truncate">
                        {file.original_name}
                      </p>
                    )}
                    <p className="text-xs text-on-muted">
                      {formatBytes(file.size_bytes)}
                    </p>
                  </div>
                  {canWrite && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="iconSm"
                      onClick={() => setDoomed(file)}
                      disabled={remove.isPending}
                      aria-label={t("attachments.deleteFile", {
                        name: file.original_name,
                      })}
                      className="text-on-muted hover:text-red-600"
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </CardContent>
      <ConfirmDialog
        open={doomed !== null}
        title={t("attachments.confirmDeleteTitle")}
        message={t("attachments.confirmDeleteMessage", {
          name: doomed?.original_name ?? "",
        })}
        confirmLabel={t("attachments.delete")}
        cancelLabel={t("create.cancel")}
        variant="danger"
        onConfirm={() => {
          const file = doomed;
          setDoomed(null);
          if (file) void onDelete(file);
        }}
        onCancel={() => setDoomed(null)}
      />
    </Card>
  );
}
