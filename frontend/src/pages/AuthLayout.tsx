import { type ReactNode } from "react";
import { NavLink } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { PackageSearch } from "lucide-react";
import { LanguageSelector } from "@/components/LanguageSelector";

interface AuthLayoutProps {
  children: ReactNode;
}

/**
 * Shared layout for authentication pages (login, register, forgot, reset).
 *
 * Left panel: branding (bg-accent-800, AA for the white h1 and the tagline) —
 * hidden on mobile.
 * Right panel: centered form slot with LanguageSelector, and a footer with
 * the privacy link and the copyright line.
 *
 * Replaces 4 copies of the same layout markup across auth pages.
 */
export function AuthLayout({ children }: AuthLayoutProps) {
  const { t } = useTranslation("auth");

  return (
    <div className="min-h-screen flex bg-surface">
      {/* Left panel — branding (hidden on mobile). accent-800, not -600/-700:
          both are unusable in dark — index.css remaps accent-700 to bright
          emerald-500 there (2.54:1 under the white h1) and leaves accent-600
          at 3.77:1 (too dim for the 20px tagline). accent-800 is not remapped
          (6 95 70 in both themes): white h1 7.7:1, tagline 7.3:1 light and
          7.7:1 dark (accent-50 flips dark in dark mode, hence dark:text-white). */}
      <div className="hidden lg:flex lg:w-1/2 bg-accent-800 relative overflow-hidden flex-col items-center justify-center p-12">
        <div className="absolute inset-0 opacity-20">
          <div className="absolute top-[-10%] left-[-10%] w-[60%] h-[60%] bg-surface-card rounded-full blur-[120px]" />
          <div className="absolute bottom-[-20%] right-[-10%] w-[70%] h-[70%] bg-accent-400 rounded-full blur-[100px]" />
        </div>

        <div className="relative z-10 text-center max-w-md animate-in fade-in zoom-in-95 duration-1000">
          <div className="w-24 h-24 bg-surface-card rounded-2xl flex items-center justify-center mx-auto mb-10 shadow-md rotate-3 group hover:rotate-0 transition-transform duration-500">
            <PackageSearch
              className="text-accent-600"
              size={48}
              strokeWidth={1.5}
            />
          </div>
          {/* p with a heading role, not an h1 tag: the mobile logo block below
              carries the page's one real h1 (it is the only brand on screen
              below 1024px), and two h1 tags in the markup read as a duplicate
              first-level heading to every DOM scanner. Exactly one of the two
              is in the accessibility tree at any width — the tag count is one,
              the tree count is one, both measured (tests/e2e/auth-heading.spec.ts). */}
          <p
            role="heading"
            aria-level={1}
            className="text-5xl font-semibold text-white mb-6 tracking-tight"
          >
            Inventari
          </p>
          <p className="text-accent-50 dark:text-white text-xl leading-relaxed font-medium">
            {t("login.tagline", {
              defaultValue: "You know what you have. And where.",
            })}
          </p>
        </div>
      </div>

      {/* Right panel — form */}
      <div className="flex-1 flex items-center justify-center p-6 sm:p-8 relative">
        <div className="absolute top-6 right-6">
          <LanguageSelector align="right" />
        </div>

        <div className="w-full max-w-sm animate-in fade-in slide-in-from-bottom-4 duration-700">
          {/* Mobile logo */}
          <div className="lg:hidden text-center mb-12">
            <div className="w-20 h-20 bg-accent-600 rounded-3xl flex items-center justify-center mx-auto mb-4 shadow-md">
              <PackageSearch
                className="text-white"
                size={40}
                strokeWidth={1.5}
              />
            </div>
            {/* The page's one real h1: below 1024px this block is the only
                brand on screen, so the heading lives here and the desktop
                panel's brand carries the heading role instead of the tag. */}
            <h1 className="text-lg font-semibold text-on tracking-tight">
              Inventari
            </h1>
          </div>

          {children}

          <footer className="mt-10 flex flex-col items-center gap-2">
            {/* Every screen a visitor without an account can reach — sign-in,
                the demo's way in above it, the access request — says where
                to read what this installation keeps about them. */}
            <NavLink
              to="/privacy"
              className="inline-flex min-h-11 items-center md:min-h-0 text-xs font-medium text-on-muted hover:text-on underline decoration-2 underline-offset-4 transition-colors"
            >
              {t("privacy.link")}
            </NavLink>
            {/* "Inventari Ecosystem" was hard-coded; the catalogue carries it
                in five languages, and the Polish screen no longer shows the
                English words. */}
            <p className="text-center text-[10px] font-medium uppercase tracking-[0.3em] text-on-muted">
              {t("brandEcosystem")}
            </p>
          </footer>
        </div>
      </div>
    </div>
  );
}
