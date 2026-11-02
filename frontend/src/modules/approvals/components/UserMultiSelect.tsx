import { useState, useMemo } from "react";
import * as PopoverPrimitive from "@radix-ui/react-popover";
import { Check, Plus, Search, X } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { InlineQueryError } from "@/components/ui/QueryResult";
import { cn } from "@/lib/utils";
import { useOrgMembers } from "@/modules/approvals/hooks/useOrgMembers";
import { roleLabel } from "@/modules/approvals/roleLabels";

/** What the picker calls its button, its popover and its remove control. */
export interface UserMultiSelectWording {
  add: string;
  title: string;
  remove: string;
}

interface UserMultiSelectProps {
  selectedUserIds: string[];
  onChange: (ids: string[]) => void;
  /** Defaults to picking approvers; a workflow's requesters are people too. */
  wording?: UserMultiSelectWording;
}

export function UserMultiSelect({
  selectedUserIds,
  onChange,
  wording,
}: UserMultiSelectProps) {
  const { t } = useTranslation("approvals");
  const words = wording ?? {
    add: t("workflows.addApprover"),
    title: t("workflows.selectApprovers"),
    remove: t("workflows.removeApprover"),
  };
  const [open, setOpen] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const { data: users = [], isError, error, refetch } = useOrgMembers();

  const selectedUsers = useMemo(
    () => users.filter((u) => selectedUserIds.includes(u.id)),
    [users, selectedUserIds],
  );

  // Detect duplicate full_name within the org. When two users share a
  // full_name (e.g. two "Jan Kowalski"), the selected-badge must include
  // the email so the approver can tell them apart.
  const duplicateNames = useMemo(() => {
    const counts = new Map<string, number>();
    for (const u of users) {
      const key = u.full_name?.trim();
      if (!key) continue;
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return new Set(
      Array.from(counts.entries())
        .filter(([, n]) => n > 1)
        .map(([name]) => name),
    );
  }, [users]);

  const availableUsers = useMemo(() => {
    const query = searchQuery.toLowerCase().trim();
    return users.filter(
      (u) =>
        !selectedUserIds.includes(u.id) &&
        (!query ||
          (u.full_name ?? "").toLowerCase().includes(query) ||
          u.email.toLowerCase().includes(query)),
    );
  }, [users, selectedUserIds, searchQuery]);

  const toggleUser = (userId: string) => {
    if (selectedUserIds.includes(userId)) {
      onChange(selectedUserIds.filter((id) => id !== userId));
    } else {
      onChange([...selectedUserIds, userId]);
    }
  };

  // The wire types full_name optional-nullable; a member record without one
  // is named by its email either way.
  const displayName = (u: { full_name?: string | null; email: string }) =>
    u.full_name ?? u.email;

  const badgeLabel = (u: {
    full_name?: string | null;
    email: string;
  }): string => {
    const name = displayName(u);
    if (u.full_name && duplicateNames.has(u.full_name.trim())) {
      return `${name} (${u.email})`;
    }
    return name;
  };

  const showEmailLine = (u: { full_name?: string | null }): boolean =>
    u.full_name != null && u.full_name !== "";

  return (
    <div className="space-y-1.5">
      {/* A badge never outgrows the column it stands in: on a phone the
          column is narrower than 180px of name, and the name, not the card's
          edge, is what gives way. */}
      <div className="flex flex-wrap gap-1.5">
        {selectedUsers.map((user) => (
          <Badge
            key={user.id}
            variant="secondary"
            title={user.email}
            className="flex max-w-full items-center gap-1 pr-1 cursor-default"
          >
            <span className="min-w-0 max-w-[180px] truncate">
              {badgeLabel(user)}
            </span>
            <Button
              type="button"
              variant="ghost"
              size="inline"
              onClick={() => toggleUser(user.id)}
              className="ml-0.5 shrink-0 p-0.5 rounded-full hover:bg-surface-inset"
              aria-label={words.remove}
            >
              <X size={12} />
            </Button>
          </Badge>
        ))}
      </div>

      {/* The chosen people cannot be named without the list, and a picker that
          shows none of them reads as "nobody is selected". */}
      {isError && selectedUserIds.length > 0 && (
        <InlineQueryError error={error} onRetry={() => void refetch()} />
      )}

      <PopoverPrimitive.Root open={open} onOpenChange={setOpen}>
        <PopoverPrimitive.Trigger asChild>
          <Button
            size="content"
            type="button"
            variant="ghost"
            data-state={open ? "open" : "closed"}
            onClick={() => setOpen((prev) => !prev)}
            className="border border-dashed border-border px-3 py-1.5 gap-1.5 text-on-muted hover:border-primary-400 hover:text-primary-600"
          >
            <Plus size={14} />
            {words.add}
          </Button>
        </PopoverPrimitive.Trigger>
        <PopoverPrimitive.Portal>
          <PopoverPrimitive.Content
            className="z-[var(--z-modal)] w-[320px] max-h-[85vh] bg-surface-card rounded-xl shadow-xl border border-border p-1 animate-in fade-in-0 zoom-in-95 duration-200"
            sideOffset={4}
          >
            <div className="flex flex-col max-h-[340px]">
              <div className="flex items-center justify-between p-3 border-b border-border">
                <h3 className="text-base font-semibold text-on">
                  {words.title}
                </h3>
                <Button
                  type="button"
                  variant="ghost"
                  size="iconSm"
                  onClick={() => setOpen(false)}
                  aria-label={t("common:actions.close")}
                  className="rounded-full text-on-muted hover:text-on-secondary"
                >
                  <X size={16} />
                </Button>
              </div>

              <div className="p-3 border-b border-border">
                <div className="relative">
                  <Input
                    leftIcon={<Search size={16} />}
                    aria-label={t("workflows.searchUsers", "Search users...")}
                    type="text"
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder={t("workflows.searchUsers", "Search users...")}
                    className="w-full pr-9 py-2 bg-surface border border-border rounded-lg outline-none focus:border-primary-500 focus:bg-surface-card transition-all text-sm"
                    autoFocus
                  />
                  {searchQuery && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="iconSm"
                      onClick={() => setSearchQuery("")}
                      aria-label={t("common:actions.clearSearch")}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-on-muted hover:text-on-secondary"
                    >
                      <X size={14} />
                    </Button>
                  )}
                </div>
              </div>

              <div className="overflow-y-auto flex-1 p-1 max-h-[240px]">
                {isError ? (
                  <div className="p-3">
                    <InlineQueryError
                      error={error}
                      onRetry={() => void refetch()}
                    />
                  </div>
                ) : availableUsers.length === 0 ? (
                  <div className="py-10 text-center">
                    <p className="text-sm text-on-muted font-medium">
                      {users.length > 0 && !searchQuery.trim()
                        ? t("workflows.allUsersSelected")
                        : t("workflows.noUsersFound")}
                    </p>
                  </div>
                ) : (
                  <div className="space-y-0.5">
                    {availableUsers.map((user) => (
                      <Button
                        size="content"
                        key={user.id}
                        type="button"
                        variant="ghost"
                        onClick={() => toggleUser(user.id)}
                        className="w-full justify-start gap-3 p-2.5 rounded-lg text-left"
                      >
                        <div className="w-8 h-8 rounded-full bg-surface-inset flex items-center justify-center shrink-0">
                          <span className="text-sm font-medium text-on-secondary">
                            {displayName(user).charAt(0).toUpperCase()}
                          </span>
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="font-medium text-sm truncate">
                            {displayName(user)}
                          </p>
                          <p className="text-xs text-on-muted truncate">
                            {showEmailLine(user) && `${user.email} · `}
                            {/* Naming someone hands them the decision, so the
                                list says what each person is — the offer was
                                silent about this when the promise was made. */}
                            {roleLabel(t, user.role)}
                          </p>
                        </div>
                        <div
                          className={cn(
                            "w-5 h-5 rounded border flex items-center justify-center shrink-0 transition-colors",
                            selectedUserIds.includes(user.id)
                              ? "bg-primary-600 border-primary-600"
                              : "border-border",
                          )}
                        >
                          {selectedUserIds.includes(user.id) && (
                            <Check
                              size={12}
                              className="text-white"
                              strokeWidth={3}
                            />
                          )}
                        </div>
                      </Button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </PopoverPrimitive.Content>
        </PopoverPrimitive.Portal>
      </PopoverPrimitive.Root>
    </div>
  );
}
