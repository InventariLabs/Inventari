import { useTranslation } from "react-i18next";
import { Brain, Plus } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { AiConnectionCard } from "@/modules/settings/components/ai/AiConnectionCard";
import type { AiConnection } from "@/types/ai";

interface AiConnectionListProps {
  connections: AiConnection[];
  boundConnectionIds: Set<string>;
  onAdd: () => void;
  onEdit: (connection: AiConnection) => void;
  onDelete: (connection: AiConnection) => void;
  /** Some purpose runs on the server's default model with no connection. */
  serverDefaultServes?: boolean;
}

export function AiConnectionList({
  connections,
  boundConnectionIds,
  onAdd,
  onEdit,
  onDelete,
  serverDefaultServes = false,
}: AiConnectionListProps) {
  const { t } = useTranslation("modules");

  if (connections.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center gap-4 py-12 px-4 border border-dashed border-border rounded-xl text-center">
        <div className="w-12 h-12 bg-purple-100 text-purple-700 dark:bg-purple-500/15 dark:text-purple-300 rounded-xl flex items-center justify-center">
          <Brain size={22} />
        </div>
        <div>
          <p className="font-medium text-on">{t("config.noConnections")}</p>
          <p className="text-sm text-on-muted mt-1">
            {t(
              serverDefaultServes
                ? "config.noConnectionsServerDefaultHint"
                : "config.noConnectionsHint",
            )}
          </p>
        </div>
        <Button onClick={onAdd}>
          <Plus size={16} className="mr-2" />
          {t("config.addConnection")}
        </Button>
      </div>
    );
  }

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {connections.map((connection) => (
        <AiConnectionCard
          key={connection.id}
          connection={connection}
          isBoundHere={boundConnectionIds.has(connection.id)}
          onEdit={onEdit}
          onDelete={onDelete}
        />
      ))}
    </div>
  );
}
