import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { useParams } from "react-router-dom";
import { Printer } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { QueryError } from "@/components/ui/QueryResult";
import { RecordNotFound } from "@/components/ui/RecordNotFound";
import { useModulePageHeader } from "@/hooks/useModulePageHeader";
import { extractApiError, isNotFoundError } from "@/lib/errors";
import { BatchRecordSheet } from "@/modules/maker/components/BatchRecordSheet";
import { useBatchRecord } from "@/modules/maker/hooks/useBatches";

/**
 * The batch record of a completed run, ready to print on A4 or to read on a
 * phone at the bench. The print keeps the record and leaves the app around it.
 */
export default function BatchRecordPage() {
  const { t } = useTranslation("maker");
  const { orderId } = useParams<{ orderId: string }>();
  const { setHeader } = useModulePageHeader();
  const { data: record, isLoading, error, refetch } = useBatchRecord(orderId);
  const batchNames = record?.output_batches?.length
    ? record.output_batches.map((batch) => batch.lot_name).join(", ")
    : record?.output_lot_name;

  useEffect(() => {
    setHeader({
      title: t("record.title"),
      subtitle: batchNames
        ? t("record.subtitle", { batch: batchNames })
        : undefined,
      backTo: orderId ? `/maker/production/${orderId}` : "/maker/production",
    });
  }, [batchNames, orderId, t, setHeader]);

  if (error && isNotFoundError(error)) {
    return (
      <RecordNotFound
        title={t("detail.notFound")}
        backTo="/maker/production"
        backLabel={t("detail.back")}
      />
    );
  }
  if (error) {
    // A draft has no record yet: the server says so in words worth showing.
    return (
      <div className="space-y-4">
        <p className="text-sm text-on-secondary">
          {extractApiError(error, t("record.failed"))}
        </p>
        <QueryError onRetry={() => void refetch()} />
      </div>
    );
  }
  if (isLoading || !record) {
    return (
      <div className="flex justify-center py-16">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-accent-600" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex justify-end print:hidden">
        <Button
          leftIcon={<Printer size={16} />}
          onClick={() => window.print()}
          data-testid="maker-print-batch-record"
        >
          {t("record.print")}
        </Button>
      </div>
      <BatchRecordSheet record={record} />
    </div>
  );
}
