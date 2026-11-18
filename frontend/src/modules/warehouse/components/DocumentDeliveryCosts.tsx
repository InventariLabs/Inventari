import { DocumentCostVariancesSection } from "@/modules/warehouse/components/DocumentCostVariancesSection";
import { DocumentExtraCostsSection } from "@/modules/warehouse/components/DocumentExtraCostsSection";

/**
 * What a receipt cost beyond its price, in the order a person meets it:
 * freight, duty and insurance that go into the value of the goods while the
 * receipt is open, and — once it is posted — the cost that arrived too late
 * for any product and is recorded as a variance.
 */
export function DocumentDeliveryCosts({ documentId }: { documentId: string }) {
  return (
    <>
      <DocumentExtraCostsSection documentId={documentId} />
      <DocumentCostVariancesSection documentId={documentId} />
    </>
  );
}
