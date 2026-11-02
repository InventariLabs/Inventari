import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft } from "lucide-react";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import type { PageHeaderData } from "@/hooks/useModulePageHeader";

interface PageHeaderProps extends PageHeaderData {
  className?: string;
}

export function PageHeader({
  title,
  subtitle,
  actions,
  backTo,
  statusBadge,
  className = "",
}: PageHeaderProps) {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const location = useLocation();
  // The back arrow is one of the exits a dirty form must ask about
  // — and it navigates by hand (history pop), so a click-capture
  // guard on a link container does not reach it.
  const { guardNavigate, confirmDialogProps } = useNavLeaveGuard();

  // Use browser history (-1) when possible so the in-page back arrow behaves
  // like the browser back button. Fall back to the explicit `backTo` path
  // (with `replace`) when there is no in-app history to pop — e.g. deep-link
  // entry where location.key is the router's initial "default".
  const handleBack = () => {
    guardNavigate(() => {
      if (location.key !== "default") {
        navigate(-1);
      } else if (backTo) {
        navigate(backTo, { replace: true });
      }
    });
  };

  if (!title && !actions && !backTo) return null;

  return (
    <div className={className}>
      {/* The action bar never shrinks, so on a half-width desktop window a
          wide set of actions used to squeeze the title down to a couple of
          characters. Let the row wrap instead: the title keeps at least 20rem
          and the actions drop to a line of their own when they no longer fit
          beside it. */}
      <div className="flex flex-col sm:flex-row sm:flex-wrap sm:items-center justify-between gap-3 sm:gap-4">
        <div className="flex items-center gap-2 min-w-0 sm:flex-1 sm:basis-80">
          {backTo && (
            <button
              type="button"
              onClick={handleBack}
              // on mobile the AppShell bar already renders the back
              // button — showing a second identical arrow here doubles the
              // control. Desktop keeps this one (shell back is mobile-only).
              className="hidden sm:inline-flex p-1.5 -ml-1.5 rounded-lg text-on-muted hover:text-on hover:bg-surface-raised transition-colors shrink-0"
              aria-label={t("actions.back")}
            >
              <ArrowLeft size={18} />
            </button>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              {title && (
                <h1 className="text-lg md:text-xl font-semibold text-on tracking-tight text-balance">
                  {title}
                </h1>
              )}
              {statusBadge}
            </div>
            {subtitle && (
              <p className="text-sm text-on-muted mt-0.5 hidden sm:block">
                {subtitle}
              </p>
            )}
          </div>
        </div>
        {actions && (
          // Callers build the action group as one `flex … shrink-0` div of
          // their own, and below `sm` this wrapper is full-width: a group
          // wider than a phone then ran past the root's overflow-x-hidden
          // and was cut off unreachable (measured on /recipes at 320px in
          // DE: the group was 331px in a 296px row). The wrapper lends every
          // direct child shrink and wrap, so a group that does not fit folds
          // its buttons instead of leaving the screen — the same class fix
          // the ListControlBar row got.
          <div className="flex items-center gap-2 shrink-0 max-w-full w-full sm:w-auto flex-wrap [&>*]:shrink [&>*]:flex-wrap">
            {actions}
          </div>
        )}
      </div>

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
