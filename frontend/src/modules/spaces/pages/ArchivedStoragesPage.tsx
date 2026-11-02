import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { QueryResult } from "@/components/ui/QueryResult";
import { useArchiveTabs } from "@/hooks/useArchiveTabs";
import { useCanWrite } from "@/hooks/useCanWrite";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { storagesApi } from "@/lib/api/storages";
import { useShowModuleData } from "@/modules/settings/hooks/useOrganization";
import { queryKeys } from "@/hooks/queries/keys";
import { formatDate, locationPathBelowName } from "@/utils/helpers";
import type { ArchivedStorageLocation, StorageLocation } from "@/types";

/**
 * Archived locations, and the way back.
 *
 * Archiving is where the app sends anyone who may not delete a location, and
 * it hides the row from every list, tree and picker — so without this screen
 * a mistyped choice ("Cold Storage" instead of "Cold Storage 2") could only
 * be undone with an UPDATE against the database. The row shows its path and
 * archive date for the same reason: this is the one screen where a pick is
 * made between locations that may share a name, with nothing else on screen
 * to tell them apart — the path under the name is what the equipment
 * locations list already shows for the same choice.
 */
export default function ArchivedStoragesPage() {
  const { t } = useTranslation(["locations", "common"]);
  const { setHeader } = useModulePageHeader();
  const queryClient = useQueryClient();
  const navigate = useNavigate();

  // The same pair of tabs the active list carries: the way back has to be
  // where the way in was, now that neither state has a menu entry.
  const archiveTabs = useArchiveTabs("archived", (tab) => {
    if (tab === "active") navigate("/inventory/locations");
  });

  // The API checks `locations:write` before it puts a location back, so an
  // account without it was being offered a button that answers 403.
  const canRestore = useCanWrite("locations");

  useEffect(() => {
    setHeader({
      title: t("locations:archived.title"),
      subtitle: t("locations:archived.subtitle"),
      backTo: "/inventory/locations",
    });
  }, [setHeader, t]);

  // The same module-data scope the Active tab applies — the two tabs are one
  // list in two states, and a restore is confirmed on the tab the row must
  // reappear on. The flag is part of the cache identity: scoped and unscoped
  // archives are different answers to one endpoint.
  const excludeModuleContexts = !useShowModuleData();
  const query = useQuery({
    queryKey: [
      ...queryKeys.storages.all,
      "archived",
      { excludeModuleContexts },
    ],
    queryFn: () => storagesApi.listArchived({ excludeModuleContexts }),
  });

  const restoreMutation = useAppMutation<StorageLocation, string>(
    (id) => storagesApi.unarchive(id),
    (qc) => {
      qc.invalidateQueries({ queryKey: queryKeys.storages.all });
    },
    { errorFallback: t("locations:errors.cannotRestore") },
  );

  const handleRestore = (storage: ArchivedStorageLocation) => {
    restoreMutation.mutate(storage.id, {
      onSuccess: () => {
        toast.success(t("locations:messages.storageRestored"));
        queryClient.invalidateQueries({
          queryKey: [...queryKeys.storages.all, "archived"],
        });
      },
    });
  };

  return (
    <div className="space-y-4">
      <ListControlBar primaryTabs={archiveTabs} />
      <QueryResult query={query}>
        {(storages) =>
          storages.length === 0 ? (
            <EmptyState
              icon={Archive}
              title={t("locations:archived.emptyTitle")}
              description={t("locations:archived.emptyDescription")}
            />
          ) : (
            <Card>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border">
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-on-secondary">
                        {t("locations:archived.name")}
                      </th>
                      <th className="px-4 py-3 text-left text-xs font-medium uppercase tracking-wide text-on-secondary">
                        {t("locations:archived.archivedAt")}
                      </th>
                      {canRestore && (
                        <th className="px-4 py-3 text-right text-xs font-medium uppercase tracking-wide text-on-secondary">
                          {t("locations:archived.actions")}
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {storages.map((storage) => (
                      <tr
                        key={storage.id}
                        data-testid="archived-storage-row"
                        className="border-b border-border last:border-0 hover:bg-surface"
                      >
                        <td className="px-4 py-3">
                          <span className="font-medium text-on">
                            {storage.name}
                          </span>
                          {locationPathBelowName(storage) && (
                            <p className="text-xs text-on-muted mt-0.5 truncate">
                              {locationPathBelowName(storage)}
                            </p>
                          )}
                        </td>
                        <td className="px-4 py-3 text-on-secondary tabular-nums">
                          {storage.archived_at ? (
                            formatDate(storage.archived_at)
                          ) : (
                            <span className="text-on-muted">—</span>
                          )}
                        </td>
                        {canRestore && (
                          <td className="px-4 py-3 text-right">
                            <Button
                              variant="outline"
                              size="sm"
                              onClick={() => handleRestore(storage)}
                              disabled={restoreMutation.isPending}
                            >
                              <RotateCcw className="h-4 w-4 mr-2" />
                              {t("locations:archived.restore")}
                            </Button>
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )
        }
      </QueryResult>
    </div>
  );
}
