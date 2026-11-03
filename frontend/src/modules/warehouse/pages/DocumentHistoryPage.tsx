import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { History, SearchX, X } from "lucide-react";
import { Card } from "@/components/ui/Card";
import { EmptyState, EmptyStateAction } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { Pagination } from "@/module-sdk";
import { QueryError } from "@/components/ui/QueryResult";
import { useCanWrite } from "@/hooks/useCanWrite";
import DocumentFormModal from "@/modules/warehouse/components/DocumentFormModal";
import { HistoryOfficePanel } from "@/modules/warehouse/components/HistoryOfficePanel";
import { HistoryRow } from "@/modules/warehouse/components/HistoryRow";
import { useDocumentHistory } from "@/modules/warehouse/hooks/useDocumentHistory";
import { useDocumentProfile } from "@/modules/warehouse/hooks/useDocumentProfile";
import { HISTORY_CHIPS } from "@/modules/warehouse/historyEntry";
import type { DocumentType } from "@/modules/warehouse/types";

/**
 * Everything that moved goods, in plain words, with the document that proves
 * it. The floor's actions write their documents in the background; this is
 * where a person finds one again — and where the office finds its register,
 * the month's close and the document it has to write by hand.
 */
export default function DocumentHistoryPage() {
  const { t } = useTranslation("warehouse");
  const navigate = useNavigate();
  const canWrite = useCanWrite("warehouse");
  const { data: profile } = useDocumentProfile();
  const history = useDocumentHistory();
  const [newDocType, setNewDocType] = useState<DocumentType | null>(null);

  // Money in a row follows two rules: the organization tracks value, and
  // the document is one whose lines carry a price.
  const tracksValue = profile?.value_tracking_enabled ?? false;

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start gap-6">
        <div className="min-w-0 flex-[999_1_40rem] space-y-4">
          <ListControlBar
            search={{
              value: history.search,
              onChange: history.setSearch,
              placeholder: t("warehouse:history.searchPlaceholder"),
            }}
            primaryTabs={{
              value: history.chip,
              onChange: (value) =>
                history.setChip(value as typeof history.chip),
              label: t("warehouse:history.filterLabel"),
              options: HISTORY_CHIPS.map((chip) => ({
                value: chip.key,
                label: t(`history.chips.${chip.key}`),
              })),
            }}
            secondaryFilters={[
              {
                key: "planned",
                label: t("warehouse:history.plannedFilter"),
                active: history.planned,
                onToggle: history.togglePlanned,
              },
              // A module's chip narrows the list on the server.
              ...history.moduleFilters,
            ]}
          />

          {history.isLoading ? (
            <div className="flex justify-center py-12">
              <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary-600" />
            </div>
          ) : history.isError ? (
            <QueryError
              message={t("errors.loadDocumentsFailed")}
              onRetry={() => void history.refetch()}
            />
          ) : history.entries.length === 0 && history.isNarrowed ? (
            <EmptyState
              icon={SearchX}
              title={t("empty.noResultsTitle")}
              description={t("empty.noResultsSubtitle")}
              primaryAction={
                <EmptyStateAction
                  label={t("empty.clearFilters")}
                  onClick={history.clearFilters}
                  leftIcon={X}
                />
              }
            />
          ) : history.entries.length === 0 ? (
            <EmptyState
              icon={History}
              title={t(
                history.planned
                  ? "warehouse:history.emptyPlannedTitle"
                  : "warehouse:history.emptyTitle",
              )}
              description={t(
                history.planned
                  ? "warehouse:history.emptyPlannedDescription"
                  : "warehouse:history.emptyDescription",
              )}
            />
          ) : (
            <Card className="p-0 overflow-hidden">
              <ul className="divide-y divide-border">
                {history.entries.map((doc) => (
                  <HistoryRow
                    key={doc.id}
                    doc={doc}
                    tracksValue={tracksValue}
                    columns={history.moduleColumns}
                  />
                ))}
              </ul>
            </Card>
          )}

          <Pagination
            skip={history.skip}
            limit={history.limit}
            total={history.total}
            onPrev={history.onPrev}
            onNext={history.onNext}
            onPageChange={history.onPageChange}
          />
        </div>

        <div className="min-w-0 flex-[1_1_18rem]">
          <HistoryOfficePanel
            canWrite={canWrite}
            onNewDocument={setNewDocType}
          />
        </div>
      </div>

      {newDocType && (
        <DocumentFormModal
          initialType={newDocType}
          onClose={() => setNewDocType(null)}
          onCreated={(created) =>
            navigate(`/warehouse/documents/${created.id}`)
          }
        />
      )}
    </div>
  );
}
