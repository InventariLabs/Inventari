import { useMemo } from "react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Select } from "@/components/ui/Select";
import { rolesApi } from "@/lib/api/admin";
import { useOrgMembers } from "@/modules/approvals/hooks/useOrgMembers";
import { useOrgRoles } from "@/modules/approvals/hooks/useOrgRoles";
import { roleLabel } from "@/modules/approvals/roleLabels";

interface RoleMembersPickerProps {
  selectedUserIds: string[];
  onAdd: (userIds: string[]) => void;
}

/**
 * "Add everyone with a role": the people who hold it now, added as names.
 *
 * A shortcut, not a link. The stage keeps the people and never the role, so
 * somebody who joins the role later is not added, and anyone added can be
 * taken off on their own. A built-in level lives on the member's `role`; an
 * organization's own role is asked for its holders. The roles listing answers
 * 403 to a reader without the configuration grant, and then there is nothing
 * to offer — people can still be picked one by one. Nor is there while the
 * member list failed to load.
 */
export function RoleMembersPicker({
  selectedUserIds,
  onAdd,
}: RoleMembersPickerProps) {
  const { t } = useTranslation("approvals");
  const { data: roles = [], isError } = useOrgRoles();
  const { data: members = [], isError: membersFailed } = useOrgMembers();

  // The organization's own roles first, then the built-in levels, the order
  // the requester picker uses.
  const options = useMemo(
    () =>
      [...roles]
        .sort(
          (a, b) =>
            Number(a.is_system) - Number(b.is_system) ||
            a.name.localeCompare(b.name),
        )
        .map((role) => ({
          id: role.id,
          name: role.is_system ? roleLabel(t, role.name) : role.name,
        })),
    [roles, t],
  );

  // Without the member list nobody can be matched to a role, and an empty
  // list would answer "nobody new to add" for a role that has people.
  if (isError || membersFailed || options.length === 0) return null;

  const addRole = async (roleId: string) => {
    const role = roles.find((r) => r.id === roleId);
    if (!role) return;
    const name = role.is_system ? roleLabel(t, role.name) : role.name;
    try {
      const holders = new Set(
        role.is_system
          ? members.filter((m) => m.role === role.name).map((m) => m.id)
          : (await rolesApi.members(role.id)).map((holder) => holder.id),
      );
      const added = members
        .filter(
          (m) =>
            m.is_active !== false &&
            holders.has(m.id) &&
            !selectedUserIds.includes(m.id),
        )
        .map((m) => m.id);
      if (added.length === 0) {
        toast.info(t("workflows.roleAddsNobody", { role: name }));
        return;
      }
      onAdd(added);
    } catch {
      toast.error(t("workflows.roleMembersFailed"));
    }
  };

  return (
    <Select
      label={t("workflows.addRole")}
      value=""
      placeholder={t("workflows.addRolePlaceholder")}
      options={options}
      onChange={(id) => void addRole(id)}
    />
  );
}
