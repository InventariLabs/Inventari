import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Loader2, Search, Shield, Trash2, User } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { Input } from "@/components/ui/Input";
import { NativeSelect } from "@/components/ui/NativeSelect";
import Pagination from "@/components/ui/Pagination";
import { InlineQueryError, QueryFailure } from "@/components/ui/QueryResult";
import { useDebounce } from "@/hooks/useDebounce";
import { useHasPermission } from "@/hooks/useHasPermission";
import { extractApiError } from "@/lib/errors";
import {
  useChangeMemberRole,
  useOrganizationMembers,
  useRemoveMember,
} from "@/modules/settings/hooks/useOrganization";
import { MEMBER_ROLES } from "@/modules/settings/memberRoles";
import {
  builtinRoleAccess,
  customRoleAccess,
} from "@/modules/settings/memberRoleAccess";
import { useRoles } from "@/modules/settings/hooks/useRoles";
import { useAuthStore } from "@/store/authStore";

/**
 * Who belongs to this organization, and what each of them may do.
 *
 * Split out of OrganizationSettings: the member list carries its own search,
 * paging, role editing and removal dialog, which is a second responsibility
 * next to the organization's own name and currency.
 */
export default function OrganizationMembers() {
  const { t } = useTranslation("common");
  const { user } = useAuthStore();
  const isAdmin = useHasPermission("admin:access");

  const [memberToRemove, setMemberToRemove] = useState<string | null>(null);
  const pageSize = 20;
  const [memberPage, setMemberPage] = useState(1);
  const [memberSearch, setMemberSearch] = useState("");
  const debouncedMemberSearch = useDebounce(memberSearch, 300);
  const memberOffset = (memberPage - 1) * pageSize;

  useEffect(() => {
    setMemberPage(1);
  }, [debouncedMemberSearch]);

  const {
    data: membersData,
    isLoading: isLoadingMembers,
    isError: membersFailed,
    error: membersError,
    refetch: refetchMembers,
  } = useOrganizationMembers(
    memberOffset,
    pageSize,
    debouncedMemberSearch || undefined,
  );
  const members = membersData?.items;
  const totalMembers = membersData?.total ?? 0;
  const memberTotalPages = Math.max(Math.ceil(totalMembers / pageSize), 1);

  const removeMemberMutation = useRemoveMember();
  const changeMemberRoleMutation = useChangeMemberRole();
  // Custom roles are admin-only data (the endpoint requires
  // SYSTEM_CONFIG_WRITE), so the query stays disabled for everyone else.
  const {
    data: rolesData,
    isError: rolesFailed,
    error: rolesError,
    refetch: refetchRoles,
  } = useRoles(isAdmin);
  const customRoles = (rolesData ?? []).filter((r) => !r.is_system);

  return (
    <>
      {/* Members */}
      <div className="px-4 py-3.5 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <div className="min-w-0">
            <p className="text-xs font-medium text-on-muted">
              {t("settings.organization.members", { defaultValue: "Members" })}
            </p>
            {/* The role dropdown offers a "custom roles" group that is empty
                until somebody creates one, and an empty group says nothing
                about where to go. */}
            {isAdmin && rolesFailed && (
              <InlineQueryError
                error={rolesError}
                onRetry={() => void refetchRoles()}
              />
            )}
            {isAdmin && !rolesFailed && customRoles.length === 0 && (
              <Link
                to="/settings/roles"
                // A 15px-tall line of text is below the 24px touch floor on a phone;
                // the row grows there and stays one line of text above it.
                className="inline-flex min-h-6 items-center text-xs text-on-primary hover:underline md:min-h-0"
              >
                {t("settings.organization.manageRolesLink")}
              </Link>
            )}
          </div>
          <Input
            aria-label={t("settings.organization.searchMembers", {
              defaultValue: "Search members...",
            })}
            placeholder={t("settings.organization.searchMembers", {
              defaultValue: "Search members...",
            })}
            value={memberSearch}
            onChange={(e) => setMemberSearch(e.target.value)}
            leftIcon={<Search size={16} />}
            wrapperClassName="flex-1 max-w-xs"
          />
        </div>
        {isLoadingMembers ? (
          <div className="py-4 flex justify-center">
            <Loader2 size={18} className="animate-spin text-on-muted" />
          </div>
        ) : membersFailed ? (
          <QueryFailure error={membersError} onRetry={() => refetchMembers()} />
        ) : (
          <div className="space-y-1">
            {members?.map((member) => (
              <div
                key={member.id}
                className="flex flex-col gap-2 py-2.5 px-3 rounded-lg hover:bg-surface-raised transition-colors group lg:flex-row lg:items-center lg:justify-between lg:gap-2"
              >
                <div className="flex items-center gap-3 min-w-0">
                  <div
                    className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${member.role === "admin" ? "bg-primary-50 text-primary-700 dark:bg-primary-500/10 dark:text-primary-500" : "bg-surface-card text-on-muted border border-border"}`}
                  >
                    {member.role === "admin" ? (
                      <Shield size={14} strokeWidth={2.5} />
                    ) : (
                      <User size={14} />
                    )}
                  </div>
                  <div className="min-w-0">
                    <p className="text-sm font-medium text-on truncate leading-tight">
                      {member.full_name || member.email}
                    </p>
                    {/* Wraps below lg, where the identity column is under ~300 px (768 px still clipped at md, the side navigation takes the width):
                        two company addresses that differ only in their last
                        label clipped to the same text. From lg up the row is
                        wide and keeps the single clipped line. */}
                    <p className="text-xs text-on-muted break-words lg:truncate">
                      {member.email}
                    </p>
                    {/* What the person may do, spelled out — the role name
                        alone ("Manager") says nothing about the powers. A
                        custom role names itself; its summary comes from the
                        permission set, not the built-in map. */}
                    <p className="text-xs text-on-muted truncate">
                      {member.custom_role
                        ? member.custom_role.name
                        : t(
                            `settings.organization.memberRoles.${member.role}`,
                            {
                              defaultValue: member.role,
                            },
                          )}
                      {" · "}
                      {t(
                        `settings.organization.memberRoleAccess.${
                          member.custom_role
                            ? customRoleAccess(member.custom_role.permissions)
                            : builtinRoleAccess(member.role)
                        }`,
                      )}
                    </p>
                  </div>
                </div>
                {isAdmin && member.id === user?.id && (
                  /* The row used to end here with nothing said, so the one
                     account whose role cannot be changed looked like a
                     rendering slip. The server refuses the change (an admin
                     demoting themselves can lock the organization out of its
                     own settings), and now the row says so. */
                  <p className="text-xs text-on-muted lg:max-w-xs lg:text-right lg:shrink-0">
                    {t("settings.organization.ownRoleFixed")}
                  </p>
                )}
                {isAdmin && member.id !== user?.id && (
                  <div className="flex items-center gap-1 w-full lg:w-auto lg:shrink-0">
                    {/* Below lg the actions drop under the identity instead
                        of squeezing it: a role select fixed at 176 px left a
                        390 px row ~52 px for the name, the address and the
                        role — three truncated values, two accounts looking
                        alike. */}
                    <NativeSelect
                      wrapperClassName="w-full lg:w-44"
                      className="text-xs"
                      aria-label={t("settings.organization.memberRoleLabel", {
                        name: member.full_name || member.email,
                      })}
                      value={
                        member.custom_role
                          ? `custom:${member.custom_role.id}`
                          : member.role
                      }
                      disabled={changeMemberRoleMutation.isPending}
                      onChange={(e) => {
                        const value = e.target.value;
                        changeMemberRoleMutation.mutate(
                          value.startsWith("custom:")
                            ? { userId: member.id, roleId: value.slice(7) }
                            : { userId: member.id, role: value },
                          {
                            onSuccess: () =>
                              toast.success(
                                t("settings.organization.memberRoleChanged"),
                              ),
                            onError: (error) =>
                              toast.error(
                                extractApiError(error, t("messages.error")),
                              ),
                          },
                        );
                      }}
                    >
                      <optgroup
                        label={t(
                          "settings.organization.memberRoleGroups.builtin",
                        )}
                      >
                        {MEMBER_ROLES.map((role) => (
                          <option key={role} value={role}>
                            {t(`settings.organization.memberRoles.${role}`)}
                          </option>
                        ))}
                      </optgroup>
                      {customRoles.length > 0 && (
                        <optgroup
                          label={t(
                            "settings.organization.memberRoleGroups.custom",
                          )}
                        >
                          {customRoles.map((r) => (
                            <option key={r.id} value={`custom:${r.id}`}>
                              {r.name}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </NativeSelect>
                    <Button
                      variant="ghost"
                      size="iconSm"
                      onClick={() => setMemberToRemove(member.id)}
                      className="text-on-muted transition-all hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-500/10 md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100"
                      aria-label={t("a11y.removeMember", {
                        name: member.full_name || member.email,
                      })}
                    >
                      <Trash2 size={14} />
                    </Button>
                  </div>
                )}
              </div>
            ))}
            {totalMembers > pageSize && (
              <Pagination
                skip={memberOffset}
                limit={pageSize}
                total={totalMembers}
                onPrev={() => setMemberPage((p) => Math.max(p - 1, 1))}
                onNext={() =>
                  setMemberPage((p) => (p < memberTotalPages ? p + 1 : p))
                }
              />
            )}
          </div>
        )}
      </div>

      <ConfirmDialog
        open={!!memberToRemove}
        title={t("settings.organization.removeMemberTitle", {
          defaultValue: "Remove Member?",
        })}
        message={t("settings.organization.removeMemberConfirm", {
          defaultValue: "Are you sure you want to remove this member?",
        })}
        confirmLabel={t("actions.remove", { defaultValue: "Remove" })}
        variant="danger"
        onConfirm={() => {
          if (memberToRemove)
            removeMemberMutation.mutate(memberToRemove, {
              onSuccess: () => {
                toast.success(t("settings.organization.memberRemoved"));
                setMemberToRemove(null);
              },
              onError: (error) =>
                toast.error(extractApiError(error, t("messages.error"))),
            });
          setMemberToRemove(null);
        }}
        onCancel={() => setMemberToRemove(null)}
      />
    </>
  );
}
