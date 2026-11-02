import { useEffect, useRef, useState } from "react";
import LoadingSpinner from "@/components/LoadingSpinner";
import { documentsApi } from "@/modules/warehouse/api/documents";
import type { WmsPickUncoveredDocument } from "@/modules/warehouse/api/documents_picking";
import WmsPickCoverageDialog from "./WmsPickCoverageDialog";

interface Props {
  /** The dispatches the person chose to pick. */
  documentIds: string[];
  /** The dispatches to start the session over — all of them, or those stock covers. */
  onReady: (documentIds: string[]) => void;
  /** Nothing is started: the sheet is closed, or nothing was left to pick. */
  onClose: () => void;
}

/**
 * Asks what stock cannot cover before a pick walk starts, and lets the
 * person decide while the walk is still free to change.
 *
 * Nothing short: the start goes ahead. A check that fails is no reason to
 * refuse it either — the session says what it must.
 */
export default function WmsPickCoverageGate({
  documentIds,
  onReady,
  onClose,
}: Props) {
  const [uncovered, setUncovered] = useState<WmsPickUncoveredDocument[] | null>(
    null,
  );
  // StrictMode runs the mount effect twice in dev; one question is enough.
  const askedRef = useRef(false);

  useEffect(() => {
    if (askedRef.current) return;
    askedRef.current = true;
    documentsApi
      .wmsPickingCoverage(documentIds)
      .catch(() => [] as WmsPickUncoveredDocument[])
      .then((found) => {
        if (found.length === 0) onReady(documentIds);
        else setUncovered(found);
      });
  }, [documentIds, onReady]);

  if (uncovered === null) {
    return (
      <div className="flex justify-center py-10">
        <LoadingSpinner />
      </div>
    );
  }

  const short = new Set(uncovered.map((doc) => doc.document_id));
  const covered = documentIds.filter((id) => !short.has(id));
  return (
    <WmsPickCoverageDialog
      documents={uncovered}
      canLeaveOut={covered.length > 0}
      onStartAnyway={() => onReady(documentIds)}
      onLeaveOut={() => onReady(covered)}
      onClose={onClose}
    />
  );
}
