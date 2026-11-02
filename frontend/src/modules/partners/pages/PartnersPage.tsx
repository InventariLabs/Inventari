import { useState, useEffect, useRef } from "react";
import { useSearchParams } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Building2, Plus, Upload } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { useConfirm } from "@/hooks/useConfirm";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { ListControlBar } from "@/components/ui/ListControlBar";
import { QueryResult } from "@/components/ui/QueryResult";
import Pagination from "@/components/ui/Pagination";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { useCanWrite } from "@/hooks/useCanWrite";
import { ReadOnlyNotice } from "@/components/ui/ReadOnlyNotice";
import { extractApiError } from "@/lib/errors";
import {
  usePartners,
  useDeactivatePartner,
  useActivatePartner,
  usePartner,
} from "@/modules/partners/hooks/usePartners";
import type { Partner } from "@/types";
import PartnerFormModal from "@/modules/partners/components/PartnerFormModal";
import { PartnerList } from "@/modules/partners/components/PartnerList";
import PartnerImportModal from "@/modules/partners/components/PartnerImportModal";
import { PartnerDetailSheet } from "@/modules/partners/components/PartnerDetailSheet";

type Filter = "all" | "active" | "inactive";

export default function PartnersPage() {
  const { t } = useTranslation("partners");
  const { setHeader } = useModulePageHeader();
  const canWrite = useCanWrite("partners");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("active");
  const [page, setPage] = useState(1);
  const [editingPartner, setEditingPartner] = useState<Partner | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [viewingPartner, setViewingPartner] = useState<Partner | null>(null);

  // A link from another screen (a receipt refused for a missing tax ID) opens
  // the partner's form straight away, once.
  const [params] = useSearchParams();
  const editId = canWrite ? params.get("edit") : null;
  const { data: linkedPartner } = usePartner(editId);
  const openedFromLink = useRef<string | null>(null);
  useEffect(() => {
    if (!editId || !linkedPartner || openedFromLink.current === editId) return;
    openedFromLink.current = editId;
    setEditingPartner(linkedPartner);
  }, [editId, linkedPartner]);

  const PAGE_LIMIT = 25;
  const isActive = filter === "all" ? undefined : filter === "active";

  const partnersQuery = usePartners({
    search: search || undefined,
    is_active: isActive,
    limit: PAGE_LIMIT,
    offset: (page - 1) * PAGE_LIMIT,
  });
  const { data } = partnersQuery;

  // Reset to the first page whenever search or filter changes.
  useEffect(() => {
    setPage(1);
  }, [search, filter]);

  const deactivate = useDeactivatePartner();
  const activate = useActivatePartner();
  const { confirm, confirmDialogProps } = useConfirm();

  useEffect(() => {
    setHeader({
      actions: canWrite ? (
        <div className="ml-auto flex items-center gap-2">
          <Button
            variant="outline"
            leftIcon={<Upload size={16} />}
            onClick={() => setShowImportModal(true)}
          >
            {t("import.button")}
          </Button>
          <Button
            leftIcon={<Plus size={16} />}
            onClick={() => setShowCreateModal(true)}
          >
            {t("newPartner")}
          </Button>
        </div>
      ) : undefined,
    });
  }, [t, setHeader, canWrite]);

  const handleToggleActive = async (partner: Partner) => {
    if (partner.is_active) {
      const ok = await confirm({
        title: t("confirmDeactivateTitle"),
        message: t("confirmDeactivate"),
        variant: "danger",
        confirmLabel: t("actions.deactivate"),
      });
      if (!ok) return;
      deactivate.mutate(partner.id, {
        onSuccess: () => toast.success(t("toasts.deactivated")),
        onError: (err) =>
          toast.error(extractApiError(err, t("errors.deactivateFailed"))),
      });
    } else {
      activate.mutate(partner.id, {
        onSuccess: () => toast.success(t("toasts.activated")),
        onError: (err) =>
          toast.error(extractApiError(err, t("errors.activateFailed"))),
      });
    }
  };

  const partners = data?.items ?? [];

  return (
    <div className="space-y-6">
      <ReadOnlyNotice module="partners" />
      <ListControlBar
        search={{
          value: search,
          onChange: setSearch,
          placeholder: t("searchPlaceholder"),
        }}
        resultCount={data?.total}
        primaryTabs={{
          value: filter,
          onChange: (v) => setFilter(v as Filter),
          options: (["active", "inactive", "all"] as Filter[]).map((f) => ({
            value: f,
            label: t(`filter${f.charAt(0).toUpperCase() + f.slice(1)}`),
          })),
        }}
      />

      {/* Partner list */}
      <QueryResult query={partnersQuery}>
        {(data) => {
          const list = data?.items ?? [];
          if (list.length === 0) {
            return (
              <EmptyState
                icon={Building2}
                title={t("noPartners")}
                description={t("noPartnersDesc")}
                primaryAction={
                  canWrite ? (
                    <Button
                      variant="primary"
                      leftIcon={<Plus size={16} />}
                      onClick={() => setShowCreateModal(true)}
                    >
                      {t("newPartner")}
                    </Button>
                  ) : undefined
                }
              />
            );
          }
          return (
            <PartnerList
              partners={list}
              canWrite={canWrite}
              onOpen={setViewingPartner}
              onEdit={setEditingPartner}
              onToggleActive={handleToggleActive}
            />
          );
        }}
      </QueryResult>

      {partners.length > 0 && data && data.total > PAGE_LIMIT && (
        <Pagination
          skip={(page - 1) * PAGE_LIMIT}
          limit={PAGE_LIMIT}
          total={data.total}
          onPrev={() => setPage((p) => Math.max(1, p - 1))}
          onNext={() => setPage((p) => p + 1)}
        />
      )}

      {/* Modals */}
      {showCreateModal && (
        <PartnerFormModal onClose={() => setShowCreateModal(false)} />
      )}
      {showImportModal && (
        <PartnerImportModal onClose={() => setShowImportModal(false)} />
      )}
      {editingPartner && (
        <PartnerFormModal
          partner={editingPartner}
          onClose={() => setEditingPartner(null)}
        />
      )}
      {viewingPartner && !editingPartner && (
        <PartnerDetailSheet
          canWrite={canWrite}
          partner={viewingPartner}
          onClose={() => setViewingPartner(null)}
          onEdit={(partner) => {
            // Editing from the sheet keeps it open underneath: after the form
            // saves or cancels, `editingPartner` clears and the sheet re-renders
            // with refreshed data.
            setEditingPartner(partner);
          }}
          onToggleActive={(partner) => {
            setViewingPartner(null);
            handleToggleActive(partner);
          }}
        />
      )}
      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
