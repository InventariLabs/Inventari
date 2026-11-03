import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Plus, Brain } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { TypedSlot } from "@/components/Slot";
import { useModules } from "@/contexts/ModulesContext";
import { AiConnectionList } from "@/modules/settings/components/ai/AiConnectionList";
import { AiConnectionFormModal } from "@/modules/settings/components/ai/AiConnectionFormModal";
import { PurposeBindingSelect } from "@/modules/settings/components/ai/PurposeBindingSelect";
import {
  useAiConnections,
  useAiPurposes,
  useDeleteAiConnection,
} from "@/modules/settings/hooks/useAiConnections";
import type { AiConnection } from "@/types/ai";

const EMPTY_DATA = {};

export default function AiConnectionsTab() {
  const { t } = useTranslation("modules");
  const { enabledModules } = useModules();

  const {
    data: connections = [],
    isLoading,
    isError,
    error,
    refetch,
  } = useAiConnections();
  const {
    data: purposes = [],
    isError: purposesFailed,
    error: purposesError,
    refetch: refetchPurposes,
  } = useAiPurposes();
  const deleteConn = useDeleteAiConnection(t("config.deleteFailed"));

  const [editing, setEditing] = useState<AiConnection | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<AiConnection | null>(null);

  const boundIds = useMemo(() => {
    const set = new Set<string>();
    purposes.forEach((p) => {
      if (p.bound_connection_id) set.add(p.bound_connection_id);
    });
    return set;
  }, [purposes]);

  const onAdd = () => {
    setEditing(null);
    setFormOpen(true);
  };

  const onEdit = (connection: AiConnection) => {
    setEditing(connection);
    setFormOpen(true);
  };

  const onDelete = (connection: AiConnection) => {
    if (boundIds.has(connection.id)) {
      toast.error(t("config.cannotDeleteBound"));
      return;
    }
    setConfirmDelete(connection);
  };

  const confirmAndDelete = () => {
    if (!confirmDelete) return;
    deleteConn.mutate(confirmDelete.id, {
      onSuccess: () => {
        setConfirmDelete(null);
        toast.success(t("config.deleteSuccess"));
      },
    });
  };

  // The empty state here invites the reader to add the first connection.
  // Offered after a failed read, that invitation produces a duplicate of a
  // connection that is already there — with the API key typed again.
  if (isError) {
    return <QueryFailure error={error} onRetry={() => refetch()} />;
  }

  if (isLoading) {
    return <p className="text-on-muted">{t("config.loading")}</p>;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300 rounded-lg flex items-center justify-center">
            <Brain size={20} />
          </div>
          <div>
            {/* No title of its own: the shell header above carries the page's
                h1 with these exact words, and the same name twice on one
                screen read as two sections that are one. */}
            <p className="text-xs text-on-muted">
              {t("config.connectionsDescription")}
            </p>
          </div>
        </div>
        {/* One way in at a time: the empty state carries its own call to
            action, and two buttons with the same words on one screen read as
            two different things. */}
        {connections.length > 0 && (
          <Button onClick={onAdd}>
            <Plus size={16} className="mr-2" />
            {t("config.addConnection")}
          </Button>
        )}
      </div>

      <AiConnectionList
        connections={connections}
        boundConnectionIds={boundIds}
        // Only a purpose whose module is on can run: a served purpose of a
        // module that is switched off must not make the list say AI works.
        serverDefaultServes={purposes.some(
          (p) =>
            p.bound_connection_id == null &&
            p.usable &&
            enabledModules.includes(p.owner_module),
        )}
        onAdd={onAdd}
        onEdit={onEdit}
        onDelete={onDelete}
      />

      {/* Without the purposes no binding shows, and the delete guard cannot
          tell a bound connection from a free one. */}
      {purposesFailed && (
        <InlineQueryError
          error={purposesError}
          onRetry={() => void refetchPurposes()}
        />
      )}
      {purposes.length > 0 && (
        <div className="flex flex-col gap-4">
          {/* h2, not h3: the card heading above it left the heading tree, so
              this is the page's second level, not its third. */}
          <h2 className="text-sm font-semibold text-on uppercase tracking-wide">
            {t("config.bindingsTitle")}
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {purposes.map((purpose) => (
              <PurposeBindingSelect
                key={purpose.key}
                purpose={purpose}
                connections={connections}
                // A purpose belongs to a module. With that module switched
                // off, binding a connection to it changes nothing that runs
                // — so the row says so rather than pretending otherwise.
                available={enabledModules.includes(purpose.owner_module)}
              />
            ))}
          </div>
        </div>
      )}

      <TypedSlot name="settings_ai_module_config" data={EMPTY_DATA} />

      <AiConnectionFormModal
        open={formOpen}
        editing={editing}
        connections={connections}
        onClose={() => setFormOpen(false)}
      />

      <ConfirmDialog
        open={Boolean(confirmDelete)}
        title={t("config.deleteConnection")}
        message={t("config.deleteConfirm", {
          name: confirmDelete?.name ?? "",
        })}
        confirmLabel={t("config.delete")}
        cancelLabel={t("config.cancel")}
        variant="danger"
        onConfirm={confirmAndDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  );
}
