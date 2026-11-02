import { Navigate, useLocation } from "react-router-dom";
import { FILTER_PARAMS } from "@/modules/warehouse/hooks/useDocumentsList";

/**
 * The warehouse addresses that outlived their screens.
 *
 * The document list this module used to open on is now History, which tells
 * the same records in plain words; the old profile tab was folded into the
 * settings screen that is now Configuration. A bookmark, a link from a
 * partner card or an old email keeps working, with its query string and hash
 * carried over.
 *
 * History reads no filter, so an old address that narrowed the list — a
 * partner's documents, a type, a status, a date range — goes to the document
 * list, which still reads them. Sent to History it would open every
 * movement of the warehouse under a link that promised one partner's.
 */
const NEW_ADDRESS: Readonly<Record<string, string>> = {
  "/warehouse": "/warehouse/history",
  "/warehouse/profile": "/warehouse/settings",
};

function landingFor(pathname: string, search: string): string {
  const params = new URLSearchParams(search);
  if (pathname === "/warehouse" && FILTER_PARAMS.some((p) => params.has(p))) {
    return "/warehouse/all";
  }
  return NEW_ADDRESS[pathname] ?? "/warehouse/todo";
}

export default function DocumentsLegacyRedirect() {
  const { pathname, search, hash } = useLocation();
  return (
    <Navigate to={`${landingFor(pathname, search)}${search}${hash}`} replace />
  );
}
