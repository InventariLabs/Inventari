import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { Link } from "react-router-dom";
import type { StorageLocationBreadcrumb } from "@/types";

interface StoragePathProps {
  /** Root first, the selected location last. */
  path: StorageLocationBreadcrumb[];
  onSelect: (id: string) => void;
  /** Where "All storages" goes — the screen without a selection. */
  allHref?: string;
  onAll?: () => void;
}

/**
 * The full path of the selected location, every segment a way back up.
 *
 * The owner's note on the old screens was one line long: "nowhere shows the
 * full path of where one stands". A name alone does not say which "Shelf 1"
 * this is, and the back arrow only ever went one step.
 */
export function StoragePath({
  path,
  onSelect,
  allHref = "/inventory/locations",
  onAll,
}: StoragePathProps) {
  const { t } = useTranslation("locations");
  return (
    <nav aria-label={t("path.label")} className="min-w-0">
      <ol className="flex flex-wrap items-center gap-x-1 gap-y-0.5 text-sm text-on-muted">
        <li className="flex items-center gap-1">
          {onAll ? (
            <Button
              variant="ghost"
              size="inline"
              onClick={onAll}
              className="min-h-6 rounded text-sm text-on-muted hover:text-on hover:underline"
            >
              {t("path.all")}
            </Button>
          ) : (
            <Link
              to={allHref}
              className="inline-flex min-h-6 items-center rounded hover:text-on hover:underline"
            >
              {t("path.all")}
            </Link>
          )}
        </li>
        {path.map((node, index) => {
          const current = index === path.length - 1;
          return (
            <li key={node.id} className="flex min-w-0 items-center gap-1">
              <span aria-hidden="true">/</span>
              {current ? (
                <span
                  aria-current="page"
                  className="truncate font-medium text-on"
                >
                  {node.name}
                </span>
              ) : (
                <Button
                  variant="ghost"
                  size="inline"
                  onClick={() => onSelect(node.id)}
                  className="min-h-6 truncate rounded text-sm text-on-muted hover:text-on hover:underline"
                >
                  {node.name}
                </Button>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
