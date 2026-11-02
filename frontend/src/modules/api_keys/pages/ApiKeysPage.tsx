import { useState, useEffect, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { KeyRound, Plus, Trash2 } from "lucide-react";
import { formatDateMedium } from "@/utils/formatters";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { QueryFailure } from "@/components/ui/QueryResult";
import LoadingSpinner from "@/components/LoadingSpinner";
import { extractApiError } from "@/lib/errors";
import {
  useApiKeys,
  useCreateApiKey,
  useRevokeApiKey,
} from "../hooks/useApiKeys";
import { isKeyExpired, liveKeysFirst } from "../expiry";
import ApiKeyCapabilitiesCard from "../components/ApiKeyCapabilitiesCard";
import CreateApiKeyModal from "../components/CreateApiKeyModal";
import {
  ApiKeyBadges,
  ApiKeyPermissionsLine,
} from "../components/ApiKeyBadges";
import CopyKeyDialog from "../components/CopyKeyDialog";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useHasPermission } from "@/hooks/useHasPermission";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import type { ApiKeyCreated } from "../types";

type ModalState =
  | { type: "none" }
  | { type: "create" }
  | { type: "copy"; key: ApiKeyCreated }
  | { type: "revoke"; id: string; name: string };

export default function ApiKeysPage() {
  const { t } = useTranslation("api_keys");
  const [modal, setModal] = useState<ModalState>({ type: "none" });

  const { data: keys = [], isLoading, isError, error, refetch } = useApiKeys();
  const createMutation = useCreateApiKey();
  const revokeMutation = useRevokeApiKey();

  const { setHeader } = useModulePageHeader();
  // Not `api_keys:write`: the module mounts `require_permission` with the
  // system key instead of the usual read/write pair, because issuing a key
  // that can act as the organization is an organization setting.
  const canWrite = useHasPermission("org:settings:write");

  // A key that has lapsed is not a key any more, and the list said so with
  // one date cell the reader had to compare against today.
  const ordered = useMemo(() => liveKeysFirst(keys), [keys]);

  useEffect(() => {
    setHeader({
      title: t("title"),
      subtitle: t("subtitle"),
      actions: canWrite ? (
        <div className="ml-auto">
          {/* On a phone the label is hidden and only the icon remains, so
              the button carries the name itself — otherwise the one way to
              issue a key there is nameless to a screen reader. */}
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => setModal({ type: "create" })}
            className="shrink-0"
            aria-label={t("generateKey")}
            title={t("generateKey")}
          >
            <span className="hidden sm:inline">{t("generateKey")}</span>
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  const handleCreate = async (
    name: string,
    expiresAt: string | null,
    scopes: string[],
    permissions: string[],
  ) => {
    try {
      const created = await createMutation.mutateAsync({
        name,
        expires_at: expiresAt,
        scopes,
        permissions,
      });
      setModal({ type: "copy", key: created });
    } catch (err) {
      toast.error(extractApiError(err, t("form.generate")));
    }
  };

  const handleRevoke = async () => {
    if (modal.type !== "revoke") return;
    try {
      await revokeMutation.mutateAsync(modal.id);
      toast.success(t("revokedToast"));
      setModal({ type: "none" });
    } catch (err) {
      toast.error(extractApiError(err, t("revoke")));
    }
  };

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="api_keys" permission="org:settings:write" />
      <ApiKeyCapabilitiesCard />

      {/* Content */}
      {/* A key that exists and a key that could not be read are not the
          same thing to say to somebody deciding whether to issue another. */}
      {isError ? (
        <QueryFailure error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <LoadingSpinner />
      ) : keys.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          title={t("noKeys")}
          description={t("noKeysDescription")}
          primaryAction={
            canWrite ? (
              <EmptyStateAction
                // Outline: the header's generate is the view's one filled
                // action, and the same label filled twice read as two
                // competing first moves.
                variant="outline"
                label={t("generateKey")}
                onClick={() => setModal({ type: "create" })}
                leftIcon={Plus}
              />
            ) : undefined
          }
        />
      ) : (
        <>
          {/* Mobile: card list */}
          <div className="flex flex-col gap-3 sm:hidden">
            {ordered.map((key) => (
              <Card
                key={key.id}
                data-testid="api-key-row"
                className="p-4 space-y-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="font-medium text-on truncate">
                      {key.name}
                    </span>
                    <ApiKeyBadges apiKey={key} />
                  </span>
                  <span className="text-xs text-on-muted text-right">
                    {key.created_by_email ?? t("table.issuedByUnknown")}
                  </span>
                </div>
                <code className="block text-xs bg-surface-raised rounded px-2 py-1.5 font-mono break-all text-on-secondary">
                  {key.key_prefix}…
                </code>
                <ApiKeyPermissionsLine apiKey={key} titled />
                <div className="grid grid-cols-3 gap-2 text-xs text-on-secondary">
                  <div>
                    <p className="font-medium text-on-muted uppercase tracking-wide text-[10px] mb-0.5">
                      {t("table.created")}
                    </p>
                    <p>{formatDateMedium(key.created_at)}</p>
                  </div>
                  <div>
                    <p className="font-medium text-on-muted uppercase tracking-wide text-[10px] mb-0.5">
                      {t("table.lastUsed")}
                    </p>
                    <p>
                      {key.last_used_at
                        ? formatDateMedium(key.last_used_at)
                        : t("table.notUsedYet")}
                    </p>
                  </div>
                  <div>
                    <p className="font-medium text-on-muted uppercase tracking-wide text-[10px] mb-0.5">
                      {key.expires_at && isKeyExpired(key.expires_at)
                        ? t("table.expiredOn")
                        : t("table.expires")}
                    </p>
                    <p>
                      {key.expires_at
                        ? formatDateMedium(key.expires_at)
                        : t("table.noExpiry")}
                    </p>
                  </div>
                </div>
                {canWrite && (
                  <Button
                    data-testid="api-key-revoke-btn"
                    variant="ghostDanger"
                    size="sm"
                    leftIcon={<Trash2 size={14} />}
                    className="w-full justify-center"
                    onClick={() =>
                      setModal({ type: "revoke", id: key.id, name: key.name })
                    }
                  >
                    {t("revoke")}
                  </Button>
                )}
              </Card>
            ))}
          </div>

          {/* Desktop: table */}
          <Card className="hidden sm:block">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border">
                    {(
                      [
                        "name",
                        "key",
                        "permissions",
                        "issuedBy",
                        "created",
                        "lastUsed",
                        "expires",
                      ] as const
                    ).map((col) => (
                      <th
                        key={col}
                        className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-on-secondary"
                      >
                        {t(`table.${col}`)}
                      </th>
                    ))}
                    <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-on-secondary">
                      {t("table.actions")}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {ordered.map((key) => (
                    <tr
                      key={key.id}
                      data-testid="api-key-row"
                      className="border-b border-border last:border-0 hover:bg-surface"
                    >
                      <td className="px-4 py-3 font-medium text-on">
                        <span className="flex items-center gap-2">
                          {key.name}
                          <ApiKeyBadges apiKey={key} />
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <code className="text-xs bg-surface-raised rounded px-2 py-0.5 font-mono">
                          {key.key_prefix}…
                        </code>
                      </td>
                      <td className="px-4 py-3 min-w-64">
                        <ApiKeyPermissionsLine apiKey={key} />
                      </td>
                      <td className="px-4 py-3 text-on-secondary">
                        {key.created_by_email ?? t("table.issuedByUnknown")}
                      </td>
                      <td className="px-4 py-3 text-on-secondary">
                        {formatDateMedium(key.created_at)}
                      </td>
                      <td className="px-4 py-3 text-on-secondary">
                        {key.last_used_at
                          ? formatDateMedium(key.last_used_at)
                          : t("table.notUsedYet")}
                      </td>
                      <td
                        className={
                          isKeyExpired(key.expires_at)
                            ? "px-4 py-3 text-on-muted"
                            : "px-4 py-3 text-on-secondary"
                        }
                      >
                        {key.expires_at
                          ? formatDateMedium(key.expires_at)
                          : t("table.noExpiry")}
                      </td>
                      <td className="px-4 py-3 text-right">
                        {canWrite && (
                          <Button
                            data-testid="api-key-revoke-btn"
                            variant="ghostDanger"
                            size="sm"
                            leftIcon={<Trash2 size={14} />}
                            onClick={() =>
                              setModal({
                                type: "revoke",
                                id: key.id,
                                name: key.name,
                              })
                            }
                          >
                            {t("revoke")}
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          {/* The list holds active keys only, so a status column could say
              one thing and a revoked key vanished without a word. The trace
              lives in one place, and the screen says where. */}
          <p className="text-xs text-on-muted">
            {t("table.revokedTrace")}{" "}
            <Link
              to="/settings/audit-log"
              className="underline hover:text-on-secondary"
            >
              {t("table.revokedTraceLink")}
            </Link>
          </p>
        </>
      )}

      {/* Modals */}
      {modal.type === "create" && (
        <CreateApiKeyModal
          isLoading={createMutation.isPending}
          onSubmit={handleCreate}
          onCancel={() => setModal({ type: "none" })}
        />
      )}

      {modal.type === "copy" && (
        <CopyKeyDialog
          apiKey={modal.key}
          onClose={() => setModal({ type: "none" })}
        />
      )}

      {modal.type === "revoke" && (
        <ConfirmDialog
          open
          title={t("revokeConfirm.title")}
          message={t("revokeConfirm.message", { name: modal.name })}
          confirmLabel={t("revokeConfirm.confirm")}
          cancelLabel={t("revokeConfirm.cancel")}
          variant="danger"
          onConfirm={handleRevoke}
          onCancel={() => setModal({ type: "none" })}
        />
      )}
    </div>
  );
}
