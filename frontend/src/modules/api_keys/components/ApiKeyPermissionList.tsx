import { Check, X } from "lucide-react";
import { usePermissionLabel } from "@/modules/shared/hooks/permissionLabel";
import type { ApiKeyPermissionOption } from "../types";

/**
 * Permissions named in words, each marked as held or as never held.
 *
 * Three readers: the page's card (what no key may carry), the form that
 * issues a key (what a scoped key gets), and nothing else should need to say
 * a permission any other way.
 */
export default function ApiKeyPermissionList({
  permissions,
  catalog,
  withheld = false,
}: {
  permissions: string[];
  catalog: ApiKeyPermissionOption[] | undefined;
  withheld?: boolean;
}) {
  const label = usePermissionLabel(catalog);
  const Icon = withheld ? X : Check;

  return (
    <ul className="space-y-1">
      {permissions.map((permission) => (
        <li
          key={permission}
          className="flex items-start gap-2 text-sm text-on-secondary"
        >
          <Icon
            size={14}
            className={
              withheld
                ? "mt-0.5 shrink-0 text-on-muted"
                : "mt-0.5 shrink-0 text-accent-600"
            }
            aria-hidden="true"
          />
          {label(permission)}
        </li>
      ))}
    </ul>
  );
}
