import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { BookOpen, Info, Settings, UserRound } from "lucide-react";
import { ThemeToggle } from "../ThemeToggle";
import { LanguageSelector } from "../LanguageSelector";
import { Button } from "@/components/ui/Button";
import { USER_GUIDE_URL } from "@/lib/userGuide";
import type { User } from "@/types";

interface UserMenuProps {
  user: User | null;
  onLogout: () => void;
}

/** Avatar button + dropdown menu with account settings + logout. */
export function UserMenu({ user, onLogout }: UserMenuProps) {
  const { t } = useTranslation("common");
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as Element;
      if (!target.closest("[data-user-menu]")) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div className="relative" data-user-menu>
      <Button
        type="button"
        onClick={() => setOpen((v) => !v)}
        variant="ghost"
        size="sm"
        // The initial is brand-tinted, but the letter itself stays on the
        // neutral text token: `primary-700` on `primary-100` measured 1.7:1 in
        // dark mode, because both steps flip to the ramp's dark end there.
        className="h-11 w-11 md:h-8 md:w-8 p-0 bg-primary-100 text-on font-semibold text-sm hover:bg-primary-200"
        aria-label={user?.full_name ?? user?.email ?? "User"}
        aria-expanded={open}
        aria-haspopup="menu"
      >
        {user?.full_name?.[0] ?? user?.email?.[0]?.toUpperCase() ?? "?"}
      </Button>

      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full mt-1 w-56 rounded-xl border border-border bg-surface-card shadow-2xl py-1 z-[var(--z-module-nav)]"
        >
          <div className="px-4 py-2.5 border-b border-border">
            <p className="text-sm font-semibold text-on truncate">
              {user?.full_name ?? "User"}
            </p>
            <p className="text-xs text-on-muted truncate">{user?.email}</p>
          </div>

          <div className="border-b border-border py-1">
            <Link
              to="/settings/profile"
              onClick={() => setOpen(false)}
              role="menuitem"
              className="flex items-center gap-2.5 px-4 py-2 text-sm text-on-secondary hover:bg-surface-raised transition-colors"
            >
              <UserRound size={15} />
              {t("settings.tabs.profile")}
            </Link>
          </div>

          <div className="sm:hidden border-b border-border py-1">
            <Link
              to="/settings"
              onClick={() => setOpen(false)}
              role="menuitem"
              className="flex items-center gap-2.5 px-4 py-2 text-sm text-on-secondary hover:bg-surface-raised transition-colors"
            >
              <Settings size={15} />
              {t("navigation.settings", "Settings")}
            </Link>
            <div className="flex items-center justify-between px-4 py-1.5">
              <span className="text-sm text-on-secondary">
                {t("settings.appearance", "Appearance")}
              </span>
              <ThemeToggle />
            </div>
            <div className="flex items-center justify-between px-4 py-1.5">
              <span className="text-sm text-on-secondary">
                {t("settings.language", "Language")}
              </span>
              <LanguageSelector align="right" />
            </div>
          </div>

          <div className="border-b border-border py-1">
            <Link
              to="/settings/about"
              onClick={() => setOpen(false)}
              role="menuitem"
              className="flex items-center gap-2.5 px-4 py-2 text-sm text-on-secondary hover:bg-surface-raised transition-colors"
            >
              <Info size={15} />
              {t("settings.tabs.about")}
            </Link>
            <a
              href={USER_GUIDE_URL}
              target="_blank"
              rel="noopener noreferrer"
              onClick={() => setOpen(false)}
              role="menuitem"
              className="flex items-center gap-2.5 px-4 py-2 text-sm text-on-secondary hover:bg-surface-raised transition-colors"
            >
              <BookOpen size={15} />
              {t("navigation.userGuide")}
            </a>
          </div>

          <Button
            type="button"
            role="menuitem"
            onClick={onLogout}
            variant="ghost"
            size="contentSm"
            className="flex w-full px-4 py-2 justify-start text-left gap-2 text-sm text-red-600 hover:text-red-700 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20"
          >
            {t("actions.logout", "Log out")}
          </Button>
        </div>
      )}
    </div>
  );
}
