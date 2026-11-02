import { lazy } from "react";
import { FileCheck } from "lucide-react";
import { moduleRegistry, slotComponent } from "@/module-sdk";
import { MODULE, certificateNumbers, fileCertificates } from "./certificates";

// Translations need no registration: the module's `i18n/<lang>.json` is
// picked up as the `lot_certificates` namespace.
moduleRegistry.register({
  name: MODULE,
  // No screen of its own: everything this module shows is on the
  // warehouse's screens, through the seams below.
  routes: [],
  slots: [
    {
      slot: "document_line_form_extra",
      component: slotComponent(
        lazy(() => import("./components/CertificateField")),
      ),
    },
    {
      slot: "document_detail_line_extra",
      component: slotComponent(
        lazy(() => import("./components/CertificateOnLine")),
      ),
    },
  ],
  documentColumnContributors: [
    {
      key: "certificate",
      label: `${MODULE}:column.certificate`,
      hasValue: (doc) => certificateNumbers(doc).length > 0,
      render: (doc) => certificateNumbers(doc).join(", "),
    },
  ],
  // Answered on the server by the filter `seams.py` registers as `certified`.
  documentFilterContributors: [
    { key: "certified", label: `${MODULE}:filter.certified` },
  ],
  documentActionContributors: [
    {
      key: "file",
      label: `${MODULE}:action.file`,
      icon: FileCheck,
      // A receipt not yet booked that names certificates: what the
      // receiving rule waits for before the goods are booked.
      isAvailable: (doc) =>
        doc.type === "IN" &&
        ["DRAFT", "CONFIRMED"].includes(doc.status) &&
        certificateNumbers(doc).length > 0,
      run: async (doc) => {
        const filed = await fileCertificates(certificateNumbers(doc));
        return filed.length > 0
          ? `${MODULE}:action.filed`
          : `${MODULE}:action.alreadyOnFile`;
      },
    },
  ],
});
