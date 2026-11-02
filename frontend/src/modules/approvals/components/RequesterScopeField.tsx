import { useMemo } from "react";
import { useTranslation } from "react-i18next";

import { Checkbox } from "@/components/ui/Checkbox";
import { Select } from "@/components/ui/Select";
import { UserMultiSelect } from "@/modules/approvals/components/UserMultiSelect";
import { useOrgRoles } from "@/modules/approvals/hooks/useOrgRoles";
import { roleLabel } from "@/modules/approvals/roleLabels";
import {
  requesterScopeNamesSomebody,
  type RequesterScope,
} from "@/modules/approvals/workflowRequesters";

interface RequesterScopeFieldProps {
  /** `null` until the administrator has chosen: there is no default. */
  value: RequesterScope | null;
  onChange: (scope: RequesterScope) => void;
}

/**
 * Whose submissions the workflow holds: everyone, or chosen people and roles.
 *
 * Nothing is preselected. "Everyone" used to be the only answer, implied, and
 * it held the administrator's receipts like the warehouse staff's — so the
 * form asks, and the save waits for an answer. Roles come from the roles
 * listing, which answers 403 to a reader without the configuration grant;
 * people can still be chosen then.
 */
export function RequesterScopeField({
  value,
  onChange,
}: RequesterScopeFieldProps) {
  const { t } = useTranslation("approvals");
  const { data: roles = [], isError } = useOrgRoles();

  // The organization's own roles first — "Storeman" is what a scope is
  // usually about — then the built-in levels.
  const roleOptions = useMemo(
    () =>
      [...roles].sort(
        (a, b) =>
          Number(a.is_system) - Number(b.is_system) ||
          a.name.localeCompare(b.name),
      ),
    [roles],
  );

  const chosen = value !== null && !value.everyone ? value : null;
  const userIds = chosen?.user_ids ?? [];
  const roleIds = chosen?.role_ids ?? [];
  const choose = (next: { user_ids?: string[]; role_ids?: string[] }) =>
    onChange({
      everyone: false,
      user_ids: next.user_ids ?? userIds,
      role_ids: next.role_ids ?? roleIds,
    });
  const toggleRole = (id: string) =>
    choose({
      role_ids: roleIds.includes(id)
        ? roleIds.filter((r) => r !== id)
        : [...roleIds, id],
    });

  return (
    <div className="space-y-3" data-testid="workflow-requester-scope">
      <Select
        label={t("workflows.requesters.label")}
        required
        value={value === null ? "" : value.everyone ? "everyone" : "chosen"}
        placeholder={t("workflows.requesters.choose")}
        onChange={(id) =>
          id === "everyone"
            ? onChange({ everyone: true, user_ids: [], role_ids: [] })
            : choose({})
        }
        options={[
          { id: "everyone", name: t("workflows.requesters.everyone") },
          { id: "chosen", name: t("workflows.requesters.chosen") },
        ]}
      />
      {chosen && (
        <div className="space-y-3">
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-on-secondary">
              {t("workflows.requesters.roles")}
            </legend>
            {isError ? (
              <p className="text-xs text-on-muted">
                {t("workflows.requesters.rolesUnavailable")}
              </p>
            ) : (
              <div className="flex flex-wrap gap-x-4 gap-y-2">
                {roleOptions.map((role) => (
                  <Checkbox
                    key={role.id}
                    label={role.is_system ? roleLabel(t, role.name) : role.name}
                    checked={roleIds.includes(role.id)}
                    onChange={() => toggleRole(role.id)}
                  />
                ))}
              </div>
            )}
          </fieldset>
          <fieldset className="space-y-1.5">
            <legend className="text-xs font-medium text-on-secondary">
              {t("workflows.requesters.people")}
            </legend>
            <UserMultiSelect
              selectedUserIds={userIds}
              onChange={(ids) => choose({ user_ids: ids })}
              wording={{
                add: t("workflows.requesters.addPerson"),
                title: t("workflows.requesters.selectPeople"),
                remove: t("workflows.requesters.removePerson"),
              }}
            />
          </fieldset>
          {!requesterScopeNamesSomebody(chosen) && (
            <p className="text-xs text-amber-600" role="note">
              {t("workflows.requesters.nameSomebody")}
            </p>
          )}
        </div>
      )}
      <p className="text-xs text-on-muted">
        {value === null
          ? t("workflows.requesters.notChosen")
          : value.everyone
            ? t("workflows.requesters.everyoneHint")
            : t("workflows.requesters.hint")}
      </p>
    </div>
  );
}
