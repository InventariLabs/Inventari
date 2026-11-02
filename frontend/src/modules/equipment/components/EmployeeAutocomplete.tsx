import { useId, useRef, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, User, UserCircle, X } from "lucide-react";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { FIELD_LABEL_CLASS } from "@/components/ui/fieldLabel";
import { useModules } from "@/contexts/ModulesContext";
import { useEmployeeAutocomplete } from "@/modules/equipment/hooks/useEmployeeAutocomplete";
import { useOrganizationMembers } from "@/modules/settings/hooks/useOrganization";
import type { Partner } from "@/types";

/**
 * Someone an asset can be handed to.
 *
 * Two registers answer that question and only one of them was offered here.
 * "My Assets" matches an assignment to the signed-in reader by email, so
 * handing a laptop to a colleague who has an account — but no Partners entry
 * — left it invisible to them. Accounts are now offered alongside employees,
 * and picking one fills in the address that makes the rest work.
 */
export interface CheckoutPerson {
  name: string;
  email: string | null;
  /** Set only when the pick came from the Partners register. */
  partner: Partner | null;
}

interface EmployeeAutocompleteProps {
  selected: CheckoutPerson | null;
  onSelect: (person: CheckoutPerson) => void;
  onClear: () => void;
  /**
   * Names the field. Passed down to the search box so the label points at the
   * control; callers used to hand-roll a `<label>` above this component, which
   * left the input unnamed in the accessibility tree.
   */
  label?: string;
  /**
   * Offer organization accounts next to the Partners register. An account
   * pick carries no partner row — what connects the assignment to that
   * person is the email, and every caller now sends it.
   */
  includeAccounts?: boolean;
}

export function EmployeeAutocomplete({
  selected,
  onSelect,
  onClear,
  label,
  includeAccounts = false,
}: EmployeeAutocompleteProps) {
  const { t } = useTranslation("equipment");
  const { isModuleEnabled } = useModules();
  const partnersEnabled = isModuleEnabled("partners");

  const inputId = useId();
  const [search, setSearch] = useState("");
  const [dropdownOpen, setDropdownOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  const active = dropdownOpen || search.length > 0;

  const {
    data: employeesData,
    error: employeesError,
    refetch: refetchEmployees,
  } = useEmployeeAutocomplete({
    search,
    enabled: partnersEnabled && active,
  });
  const {
    data: membersData,
    error: membersError,
    refetch: refetchMembers,
  } = useOrganizationMembers(0, 10, search || undefined);

  const employees = employeesData?.items ?? [];
  const members = includeAccounts && active ? (membersData?.items ?? []) : [];

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (
        dropdownRef.current &&
        !dropdownRef.current.contains(e.target as Node)
      ) {
        setDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const pick = (person: CheckoutPerson) => {
    onSelect(person);
    setSearch("");
    setDropdownOpen(false);
  };

  if (selected) {
    return (
      <div className="w-full space-y-1.5">
        {/* A plain paragraph, not a field label: once someone is picked
            there is no control left for one to point at, only the summary
            and the button that clears it. */}
        {label && <p className={FIELD_LABEL_CLASS}>{label}</p>}
        <div className="flex items-center gap-2 rounded-lg border border-accent-500 bg-accent-500/10 px-3 py-2">
          <User size={14} className="text-accent-700 shrink-0" />
          <span className="flex-1 min-w-0">
            <span className="block text-sm text-on">{selected.name}</span>
            {selected.email && (
              <span className="block text-xs text-on-muted">
                {selected.email}
              </span>
            )}
          </span>
          <Button
            type="button"
            onClick={() => {
              onClear();
              setSearch("");
            }}
            variant="ghost"
            size="inline"
            aria-label={t("common:actions.clear")}
            className="p-0.5 text-on-muted hover:text-on"
          >
            <X size={14} />
          </Button>
        </div>
      </div>
    );
  }

  // A register that did not answer is not an empty one: "no matches" under a
  // name that exists in the register sends the reader to type it by hand.
  const lookupError =
    (partnersEnabled && employeesError) || (includeAccounts && membersError);
  const retryLookup = () => {
    if (partnersEnabled && employeesError) void refetchEmployees();
    if (includeAccounts && membersError) void refetchMembers();
  };
  const nothingFound = employees.length === 0 && members.length === 0;

  return (
    <div ref={dropdownRef} className="relative">
      <div className="relative">
        <Input
          label={label}
          id={inputId}
          value={search}
          onChange={(e) => {
            setSearch(e.target.value);
            setDropdownOpen(true);
          }}
          onFocus={() => setDropdownOpen(true)}
          placeholder={t("assignments.checkout_modal.employee_placeholder")}
          className="pr-8"
        />
        {/* Anchored to the field's own box rather than to the wrapper:
            with a label above, half of the wrapper is no longer half of
            the input. */}
        <span className="pointer-events-none absolute inset-x-0 bottom-0 flex h-11 items-center justify-end pr-3 md:h-10">
          <ChevronDown size={14} className="text-on-muted" />
        </span>
      </div>
      {dropdownOpen && (
        <div className="absolute z-10 mt-1 w-full rounded-lg border border-border bg-surface-card shadow-lg max-h-52 overflow-y-auto">
          {lookupError && (
            <div className="px-3 py-2">
              <InlineQueryError error={lookupError} onRetry={retryLookup} />
            </div>
          )}
          {nothingFound ? (
            !lookupError && (
              <p className="px-3 py-2 text-sm text-on-muted">
                {t("assignments.checkout_modal.employee_empty")}
              </p>
            )
          ) : (
            <>
              {employees.map((emp) => (
                <Button
                  key={`partner-${emp.id}`}
                  type="button"
                  onClick={() =>
                    pick({
                      name: emp.name,
                      email: emp.email ?? null,
                      partner: emp,
                    })
                  }
                  variant="ghost"
                  size="contentSm"
                  className="w-full px-3 py-2 justify-start text-left gap-2 text-sm text-on hover:bg-surface-hover"
                >
                  <User size={13} className="text-on-muted shrink-0" />
                  <span className="flex-1 min-w-0">
                    <span className="block">{emp.name}</span>
                    {emp.contact_person && (
                      <span className="block text-xs text-on-muted">
                        {emp.contact_person}
                      </span>
                    )}
                  </span>
                  {emp.email && (
                    <span className="text-xs text-on-muted shrink-0">
                      {emp.email}
                    </span>
                  )}
                </Button>
              ))}
              {members.length > 0 && (
                <p className="px-3 pt-2 pb-1 text-xs font-medium text-on-muted">
                  {t("assignments.checkout_modal.accounts_group")}
                </p>
              )}
              {members.map((member) => (
                <Button
                  key={`account-${member.id}`}
                  type="button"
                  onClick={() =>
                    pick({
                      name: member.full_name || member.email,
                      email: member.email,
                      partner: null,
                    })
                  }
                  variant="ghost"
                  size="contentSm"
                  className="w-full px-3 py-2 justify-start text-left gap-2 text-sm text-on hover:bg-surface-hover"
                >
                  <UserCircle size={13} className="text-on-muted shrink-0" />
                  <span className="flex-1 min-w-0">
                    <span className="block">
                      {member.full_name || member.email}
                    </span>
                  </span>
                  <span className="text-xs text-on-muted shrink-0">
                    {member.email}
                  </span>
                </Button>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
