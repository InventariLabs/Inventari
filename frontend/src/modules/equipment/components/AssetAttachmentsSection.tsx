import { extractApiError } from "@/lib/errors";
import { useState, useRef } from "react";
import { useTranslation } from "react-i18next";
import {
  Paperclip,
  Upload,
  FileText,
  Shield,
  Camera,
  BookOpen,
  File,
  Trash2,
  Download,
  Loader2,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { useCanWrite } from "@/hooks/useCanWrite";
import { Select } from "@/components/ui/Select";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useConfirm } from "@/hooks/useConfirm";
import {
  useEquipmentAttachments,
  useUploadAttachment,
  useDeleteAttachment,
} from "@/modules/equipment/hooks/useEquipmentAttachments";
import { toast } from "sonner";
import type { EquipmentAttachment } from "@/modules/equipment/api/equipment";
import { formatBytes } from "@/utils/formatters";
import { webLinkOrNull } from "@/lib/utils";
import { QueryFailure } from "@/components/ui/QueryResult";

const FILE_TYPE_ICONS: Record<string, React.ReactNode> = {
  INVOICE: <FileText size={16} className="text-primary-500" />,
  WARRANTY: <Shield size={16} className="text-success-500" />,
  PHOTO: <Camera size={16} className="text-purple-500" />,
  MANUAL: <BookOpen size={16} className="text-amber-500" />,
  OTHER: <File size={16} className="text-on-secondary" />,
};

/**
 * Local storage hands out root-relative `/uploads/...` paths, S3 absolute
 * http(s) URLs. Anything else (`javascript:`, `data:`, protocol-relative
 * `//host`) is not rendered as a link.
 *
 * A path is put to the browser's own URL parser, not to a pattern: the
 * parser drops tabs and newlines and reads `\` as `/` before it resolves,
 * so `/<tab>/host` begins with a single slash and still opens another site.
 * Only a path that lands on this origin stays a link.
 */
function attachmentHrefOrNull(url: string): string | null {
  if (!url.startsWith("/")) return webLinkOrNull(url);
  const here = window.location.origin;
  try {
    return new URL(url, here).origin === here ? url : null;
  } catch {
    return null; // `/<tab>/[` and the like: no host the parser accepts
  }
}

function isImageContentType(ct: string): boolean {
  return ct.startsWith("image/");
}

interface AssetAttachmentsSectionProps {
  itemId: string;
  /**
   * An archived record keeps its papers and they stay removable, but an
   * upload needs the live record — the API refuses it, so it is not offered.
   */
  archived?: boolean;
}

export function AssetAttachmentsSection({
  itemId,
  archived = false,
}: AssetAttachmentsSectionProps) {
  const { t } = useTranslation("equipment");
  const canWrite = useCanWrite("equipment");
  const {
    data: attachments = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useEquipmentAttachments(itemId);
  const uploadMutation = useUploadAttachment(itemId);
  const deleteMutation = useDeleteAttachment(itemId);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [fileType, setFileType] = useState<string>("OTHER");

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    try {
      await uploadMutation.mutateAsync({ file, fileType });
      toast.success(t("attachments.uploaded", "File uploaded"));
    } catch (error) {
      toast.error(
        extractApiError(error, t("attachments.upload_error", "Upload failed")),
      );
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const { confirm, confirmDialogProps } = useConfirm();

  const handleDelete = async (attachment: EquipmentAttachment) => {
    // Confirm before deleting an attachment (file is gone
    // from object storage once the row is removed).
    const ok = await confirm({
      title: t("attachments.confirmDeleteTitle"),
      message: t("attachments.confirmDeleteMessage", {
        name: attachment.original_name,
      }),
      variant: "danger",
      confirmLabel: t("common:actions.delete"),
    });
    if (!ok) {
      return;
    }
    try {
      await deleteMutation.mutateAsync(attachment.id);
      toast.success(t("attachments.deleted", "File deleted"));
    } catch (error) {
      toast.error(
        extractApiError(error, t("attachments.delete_error", "Delete failed")),
      );
    }
  };

  return (
    <Card>
      <CardHeader className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2 sm:gap-4">
        <CardTitle className="text-sm flex items-center gap-2">
          <Paperclip size={14} />
          {t("attachments.title", "Attachments")}
          {attachments.length > 0 && (
            <span className="text-xs text-on-muted font-normal">
              ({attachments.length})
            </span>
          )}
        </CardTitle>
        {canWrite && !archived && (
          <div className="flex items-center gap-2 self-end sm:self-auto">
            <Select
              value={fileType}
              onChange={setFileType}
              size="sm"
              // No visible label in this header row — the type chooses what
              // the upload button next to it will attach.
              aria-label={t("attachments.type_label", "Attachment type")}
              options={[
                { id: "OTHER", name: t("attachments.type_other", "Other") },
                {
                  id: "INVOICE",
                  name: t("attachments.type_invoice", "Invoice"),
                },
                {
                  id: "WARRANTY",
                  name: t("attachments.type_warranty", "Warranty"),
                },
                { id: "PHOTO", name: t("attachments.type_photo", "Photo") },
                { id: "MANUAL", name: t("attachments.type_manual", "Manual") },
              ]}
            />
            <input
              ref={fileInputRef}
              type="file"
              className="hidden"
              onChange={handleFileSelect}
              accept="image/*,.pdf,.doc,.docx,.xls,.xlsx,.txt"
            />
            <Button
              variant="outline"
              size="sm"
              leftIcon={<Upload size={14} />}
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadMutation.isPending}
            >
              {uploadMutation.isPending ? (
                <Loader2 size={14} className="animate-spin" />
              ) : null}
              {t("attachments.upload", "Upload")}
            </Button>
          </div>
        )}
      </CardHeader>
      <CardContent>
        {isError ? (
          <QueryFailure error={error} onRetry={() => refetch()} />
        ) : isLoading ? (
          <div className="flex justify-center py-4">
            <Loader2 size={20} className="animate-spin text-on-muted" />
          </div>
        ) : attachments.length === 0 ? (
          <p className="text-xs text-on-muted text-center py-4">
            {t("attachments.empty", "No attachments yet")}
          </p>
        ) : (
          <div className="space-y-2">
            {attachments.map((att) => (
              <div
                key={att.id}
                className="flex items-center gap-3 p-2 rounded-lg hover:bg-surface-secondary group"
              >
                <div className="flex-shrink-0">
                  {FILE_TYPE_ICONS[att.file_type] ?? FILE_TYPE_ICONS.OTHER}
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium truncate">
                    {att.original_name}
                  </p>
                  <p className="text-xs text-on-muted">
                    {formatBytes(att.size_bytes)} &middot;{" "}
                    {t(
                      `attachments.type_${att.file_type.toLowerCase()}`,
                      att.file_type,
                    )}
                  </p>
                </div>
                <div className="flex items-center gap-1 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
                  {attachmentHrefOrNull(att.url) && (
                    <a
                      href={attachmentHrefOrNull(att.url)!}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 hover:bg-surface rounded"
                    >
                      {isImageContentType(att.content_type) ? (
                        <Camera size={14} className="text-on-muted" />
                      ) : (
                        <Download size={14} className="text-on-muted" />
                      )}
                    </a>
                  )}
                  {canWrite && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="iconSm"
                      onClick={() => handleDelete(att)}
                      disabled={deleteMutation.isPending}
                      aria-label={t("attachments.deleteFile", {
                        name: att.original_name,
                      })}
                      className="rounded text-on-muted hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                    >
                      <Trash2 size={14} />
                    </Button>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </CardContent>
      <ConfirmDialog {...confirmDialogProps} />
    </Card>
  );
}
