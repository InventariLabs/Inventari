import { useState } from "react";
import { useDebounce } from "@/hooks/useDebounce";
import { usePartner, usePartners } from "@/hooks/usePartners";
import type { PartnerType } from "@/types";

/** Rows one lookup returns — enough to read, the search narrows the rest. */
const PICKER_PAGE_SIZE = 50;
const SEARCH_DEBOUNCE_MS = 300;

export interface PartnerOption {
  id: string;
  name: string;
}

/** Whether the chosen partner is one the picker offers; `undefined` while unknown. */
function isOffered({
  selectedId,
  onPage,
  selected,
  failed,
  types,
}: {
  selectedId?: string;
  onPage: boolean;
  selected?: { is_active: boolean; type: string };
  failed: boolean;
  types: readonly PartnerType[];
}): boolean | undefined {
  if (!selectedId) return undefined;
  if (onPage) return true;
  if (selected) {
    return selected.is_active && types.includes(selected.type as PartnerType);
  }
  return failed ? false : undefined;
}

/**
 * The partner field of a document or an order: active partners of the given
 * role set, looked up on the server by name, tax ID or code as the reader
 * types. The list is one page, never the register, so an organization with a
 * thousand partners finds the last of them the same way as the first.
 *
 * A partner already chosen may not be on that page. It is read on its own,
 * so the field can show its name and a form can tell whether the role set
 * and the active flag still allow it (`selectedOffered`) — `undefined` while
 * that is not yet known, so a form does not call a loading field empty.
 */
export function usePartnerPicker(
  types: readonly PartnerType[],
  selectedId?: string,
  /**
   * Name the chosen partner even when the role set does not offer it. A form
   * reads such a partner as an empty field and asks again; a saved record
   * has to keep saying who it is for (a return of a delivery is a receipt
   * whose partner is a customer).
   */
  keepSelected = false,
) {
  const [search, setSearch] = useState("");
  const typed = search.trim();
  const debounced = useDebounce(typed, SEARCH_DEBOUNCE_MS);
  const listQuery = usePartners({
    types: [...types],
    is_active: true,
    search: debounced || undefined,
    limit: PICKER_PAGE_SIZE,
  });
  const listed = listQuery.data?.items;
  const onPage = listed?.some((p) => p.id === selectedId) ?? false;
  const selectedQuery = usePartner(onPage ? null : selectedId);
  const selected = selectedQuery.data;

  // The partner is named from the page it was picked on. Once the panel
  // closes that page is gone and the by-id read has not landed yet, so
  // without this the field reads the placeholder for one round trip.
  const [remembered, setRemembered] = useState<PartnerOption | null>(null);
  const seen = listed?.find((p) => p.id === selectedId) ?? selected;
  if (seen && (remembered?.id !== seen.id || remembered.name !== seen.name)) {
    setRemembered({ id: seen.id, name: seen.name });
  }
  const named = remembered?.id === selectedId ? remembered : undefined;

  const selectedOffered = isOffered({
    selectedId,
    onPage,
    selected,
    failed: selectedQuery.isError,
    types,
  });

  const options: PartnerOption[] = listed ?? [];
  // The chosen partner leads the list while nothing is typed, so the field
  // can name it. Under a typed query it would be an answer to nothing.
  const pinned =
    !onPage && !search && (keepSelected || selectedOffered !== false)
      ? (selected ?? named)
      : undefined;

  return {
    options: pinned ? [pinned, ...options] : options,
    setSearch,
    // Typed text the server has not been asked about yet is also "on its
    // way": the rows on screen answer the previous query.
    loading: listQuery.isLoading || typed !== debounced,
    // A list that failed says nothing about whether the partner exists, and
    // the picker would read as "no partners". Set only when the read failed.
    error: listQuery.isError ? listQuery.error : null,
    retry: () => void listQuery.refetch(),
    selectedOffered,
  };
}
