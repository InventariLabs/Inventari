import { useCallback } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useFormGuardStore } from "@/store/formGuardStore";
import { useConfirm } from "@/hooks/useConfirm";

/**
 * The shared gate between a form holding unsaved work and the navigation
 * that would throw it away.
 *
 * A form registers itself in {@link formGuardStore} while dirty; every
 * persistent exit — the module tabs, the mobile bar, the page header's back
 * arrow — routes its navigation through here and asks first. The browser's
 * own back button is the known residual: react-router's `useBlocker` needs a
 * data router, and this gate was written while the application mounted a
 * plain `BrowserRouter`. The route tree mounts a data router now, so the
 * residual can be closed separately rather than being a dead end.
 */
export function useNavLeaveGuard() {
  const { t } = useTranslation("common");
  const navigate = useNavigate();
  const location = useLocation();
  const dirtyForm = useFormGuardStore((s) => s.dirtyForm);
  const { confirm, confirmDialogProps } = useConfirm();

  /** Runs `go` (a navigation) unless a dirty form is registered and the
   * reader declines to leave. */
  const guardNavigate = useCallback(
    (go: () => void) => {
      if (!dirtyForm) {
        go();
        return;
      }
      void confirm({
        title: t("form.unsavedTitle", "Unsaved changes"),
        message: t("form.unsavedLeave", {
          form: dirtyForm,
          defaultValue: "{{form}} holds unsaved changes. Leave anyway?",
        }),
        confirmLabel: t("form.leaveAnyway", "Leave anyway"),
        cancelLabel: t("actions.cancel", "Cancel"),
      }).then((ok) => {
        if (ok) go();
      });
    },
    [dirtyForm, confirm, t],
  );

  /**
   * Capture handler for a container of router `<Link>`s: a click on a link
   * to a different page is stopped before the router sees it and turned
   * into a guarded navigation.
   */
  const guardClick = useCallback(
    (e: React.MouseEvent) => {
      if (!dirtyForm) return;
      const link = (e.target as HTMLElement).closest("a");
      if (!link) return;
      const href = link.getAttribute("href");
      // A link to the page the reader is already on is not an exit.
      if (!href || href === location.pathname) return;
      e.preventDefault();
      e.stopPropagation();
      guardNavigate(() => navigate(href));
    },
    [dirtyForm, location.pathname, guardNavigate, navigate],
  );

  return { guardClick, guardNavigate, confirmDialogProps };
}
