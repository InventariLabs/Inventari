import { useState, useEffect } from "react";
import { useTranslation } from "react-i18next";
import {
  useWebhooks,
  useCreateWebhook,
  useUpdateWebhook,
  useDeleteWebhook,
  useTestWebhook,
  useReactivateWebhook,
} from "@/modules/webhooks/hooks/useWebhooks";
import { Webhook, Plus, X } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Sheet, SheetHeader } from "@/components/ui/Sheet";
import LoadingSpinner from "@/components/LoadingSpinner";
import { extractApiError } from "@/lib/errors";
import { QueryFailure } from "@/components/ui/QueryResult";
import WebhookForm from "../components/WebhookForm";
import WebhookDeliveryLogs from "../components/WebhookDeliveryLogs";
import { WebhookCard } from "../components/WebhookCard";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useHasPermission } from "@/hooks/useHasPermission";
import type {
  WebhookEndpoint,
  WebhookEndpointCreate,
} from "@/modules/webhooks/types/webhooks";

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "edit"; webhook: WebhookEndpoint }
  | { type: "logs"; webhook: WebhookEndpoint }
  | { type: "delete"; webhook: WebhookEndpoint };

export default function WebhooksPage() {
  const { t } = useTranslation(["webhooks", "common"]);

  const [modal, setModal] = useState<ModalState>({ type: "none" });

  const {
    data: webhooks = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useWebhooks();

  const createMutation = useCreateWebhook();
  const updateMutation = useUpdateWebhook();
  const deleteMutation = useDeleteWebhook();
  const testMutation = useTestWebhook();
  const reactivateMutation = useReactivateWebhook();

  const isAdmin = useHasPermission("admin:access");

  const reactivateWebhook = (id: string) =>
    reactivateMutation.mutate(id, {
      onSuccess: () => toast.success(t("reactivateSuccess")),
      onError: (err: unknown) =>
        toast.error(extractApiError(err, t("unknownError"))),
    });

  const { setHeader } = useModulePageHeader();

  useEffect(() => {
    setHeader({
      title: t("title"),
      subtitle: t("subtitle"),
      actions: isAdmin ? (
        <div className="ml-auto">
          <Button
            data-testid="webhooks-add-btn"
            variant="primary"
            onClick={() => setModal({ type: "create" })}
            leftIcon={<Plus size={16} />}
          >
            {t("addWebhook")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, isAdmin, setHeader]);

  // "No webhooks configured" is a claim about the installation. When the
  // list could not be read it is a guess, and the reader's next move — wiring
  // the integration again — is the expensive one.
  if (isError) {
    return <QueryFailure error={error} onRetry={() => refetch()} />;
  }
  if (isLoading) return <LoadingSpinner />;

  return (
    <div className="space-y-6">
      {/* Empty state */}
      {webhooks.length === 0 && (
        <Card className="p-12 text-center">
          <Webhook className="w-12 h-12 text-on-muted/40 mx-auto mb-4" />
          <p className="text-on-secondary font-medium">{t("noWebhooks")}</p>
          <p className="text-sm text-on-muted mt-1">
            {t("noWebhooksDescription")}
          </p>
          {isAdmin && (
            <Button
              data-testid="webhooks-add-btn"
              variant="primary"
              className="mt-5"
              onClick={() => setModal({ type: "create" })}
              leftIcon={<Plus size={16} />}
            >
              {t("addWebhook")}
            </Button>
          )}
        </Card>
      )}

      {/* Webhook list */}
      <div className="space-y-3">
        {webhooks.map((wh) => (
          <WebhookCard
            key={wh.id}
            webhook={wh}
            isAdmin={isAdmin}
            onEdit={() => setModal({ type: "edit", webhook: wh })}
            onDelete={() => setModal({ type: "delete", webhook: wh })}
            onTest={() =>
              testMutation.mutate(wh.id, {
                onSuccess: (result) => {
                  if (result.success && !wh.is_active) {
                    // A test is not a switch: the receiver answers, the
                    // endpoint stays off, and the toast must not let the
                    // reader think deliveries resumed.
                    toast.success(
                      t("testResult.successStillOff", {
                        status: result.status_code,
                      }),
                      {
                        action: {
                          label: t("reactivate"),
                          onClick: () => reactivateWebhook(wh.id),
                        },
                      },
                    );
                  } else if (result.success) {
                    toast.success(
                      t("testResult.success", { status: result.status_code }),
                    );
                  } else {
                    // A receiver that answered is named by its status, in the
                    // reader's language; the page it sent back is in the
                    // delivery log. No status means it never answered, and
                    // the reason (a timeout, a refused connection) says so.
                    toast.error(
                      result.status_code
                        ? t("testResult.rejected", {
                            status: result.status_code,
                          })
                        : t("testResult.failure", {
                            error: result.error ?? t("unknownError"),
                          }),
                    );
                  }
                },
                onError: (err: unknown) =>
                  toast.error(extractApiError(err, t("unknownError"))),
              })
            }
            onReactivate={() => reactivateWebhook(wh.id)}
            onLogs={() => setModal({ type: "logs", webhook: wh })}
          />
        ))}
      </div>

      {/* Create / Edit modal */}
      {(modal.type === "create" || modal.type === "edit") && (
        <Sheet
          open
          onClose={() => setModal({ type: "none" })}
          maxWidth="xl"
          aria-label={
            modal.type === "create"
              ? t("form.titleCreate")
              : t("form.titleEdit")
          }
        >
          <SheetHeader
            title={
              modal.type === "create"
                ? t("form.titleCreate")
                : t("form.titleEdit")
            }
            onClose={() => setModal({ type: "none" })}
          />
          <WebhookForm
            key={modal.type === "edit" ? modal.webhook?.id : "new"}
            webhook={modal.type === "edit" ? modal.webhook : null}
            isSaving={createMutation.isPending || updateMutation.isPending}
            onCancel={() => setModal({ type: "none" })}
            onSave={async (data) => {
              if (modal.type === "create") {
                await createMutation.mutateAsync(data as WebhookEndpointCreate);
                setModal({ type: "none" });
                toast.success(t("createSuccess"));
              } else {
                await updateMutation.mutateAsync({
                  id: modal.webhook.id,
                  data,
                });
                setModal({ type: "none" });
                toast.success(t("updateSuccess"));
              }
            }}
          />
        </Sheet>
      )}

      {/* Delivery logs modal */}
      {modal.type === "logs" && (
        <Sheet
          open
          onClose={() => setModal({ type: "none" })}
          maxWidth="2xl"
          aria-label={t("delivery.title")}
        >
          <div className="flex items-center justify-between px-5 py-4 border-b border-border shrink-0">
            <div>
              <h2 className="text-base font-semibold text-on">
                {t("delivery.title")}
              </h2>
              <p className="text-sm text-on-secondary">{modal.webhook.name}</p>
            </div>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => setModal({ type: "none" })}
              aria-label={t("common:actions.close")}
            >
              <X size={18} />
            </Button>
          </div>
          <div className="p-5 overflow-y-auto">
            <WebhookDeliveryLogs
              webhookId={modal.webhook.id}
              isActive={modal.webhook.is_active}
            />
          </div>
          <div className="px-5 py-3 border-t border-border flex justify-end shrink-0">
            <Button
              variant="secondary"
              onClick={() => setModal({ type: "none" })}
            >
              {t("delivery.close")}
            </Button>
          </div>
        </Sheet>
      )}

      {/* Delete confirm */}
      <ConfirmDialog
        open={modal.type === "delete"}
        title={
          modal.type === "delete"
            ? t("confirmDelete", { name: modal.webhook.name })
            : ""
        }
        message={modal.type === "delete" ? t("confirmDeleteDescription") : ""}
        variant="danger"
        confirmLabel={t("delete")}
        cancelLabel={t("common:form.cancel")}
        onConfirm={() => {
          if (modal.type === "delete")
            deleteMutation.mutate(modal.webhook.id, {
              onSuccess: () => {
                setModal({ type: "none" });
                toast.success(t("deleteSuccess"));
              },
              onError: (err: unknown) =>
                toast.error(extractApiError(err, t("unknownError"))),
            });
        }}
        onCancel={() => setModal({ type: "none" })}
      />
    </div>
  );
}
