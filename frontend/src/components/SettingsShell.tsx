import { Suspense, useState } from "react";
import { Outlet, NavLink, useNavigate, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import LoadingSpinner from "@/components/LoadingSpinner";
import {
  Settings,
  Boxes,
  Brain,
  Mail,
  History,
  LayoutGrid,
  ChevronLeft,
  ChevronDown,
  ShieldAlert,
  ShieldCheck,
  Info,
  UserRound,
  UsersRound,
  type LucideIcon,
} from "lucide-react";
import { holdsPermission } from "@/hooks/useHasPermission";
import { useAuthStore } from "@/store/authStore";
import { useModules } from "@/contexts/ModulesContext";
import { useNavLeaveGuard } from "@/hooks/useNavLeaveGuard";
import { moduleRegistry, type SettingsSection } from "@/lib/moduleRegistry";
import { makeTDynamic } from "@/lib/i18nHelpers";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/Button";
import { ConfirmDialog } from "@/components/ui/ConfirmDialog";
import { EmptyState } from "@/components/ui/EmptyState";
import { PageHeader } from "@/components/ui/PageHeader";
import { Sheet, SheetBody, SheetHeader } from "@/components/ui/Sheet";
import { settingsRoutePermission } from "@/components/settingsAccess";
import {
  PageHeaderContext,
  type PageHeaderData,
} from "@/hooks/useModulePageHeader";

type SidebarItem = {
  label: string;
  to: string;
  exact?: boolean;
  /** A section of the page `to` names, e.g. `#people`; it stands on its own in the list. */
  hash?: string;
  icon: LucideIcon;
};

/** The section of /settings that holds the members and the invitations. */
const PEOPLE_HASH = "#people";

/** Where an entry leads: its page, and the section of it when it names one. */
const destination = (item: SidebarItem) => item.to + (item.hash ?? "");

/**
 * Whether `item` is the current entry. A section entry and the page that
 * contains it share a path, so the hash tells them apart.
 */
function isCurrent(
  item: SidebarItem,
  pathActive: boolean,
  location: { pathname: string; hash: string },
): boolean {
  if (item.hash) return pathActive && location.hash === item.hash;
  const onPeople =
    location.pathname === "/settings" && location.hash === PEOPLE_HASH;
  return pathActive && !(item.to === "/settings" && onPeople);
}

type SidebarGroup = {
  label: string | null;
  items: SidebarItem[];
};

function SettingsSidebarItem({ item }: { item: SidebarItem }) {
  const Icon = item.icon;
  const location = useLocation();
  return (
    <NavLink
      to={destination(item)}
      end={item.exact}
      // NavLink matches the path only; a section entry and its page share one.
      aria-current={isCurrent(item, true, location) ? "page" : "false"}
      className={({ isActive }) =>
        cn(
          "flex items-center gap-2.5 px-3 py-2 rounded-lg text-sm font-medium transition-colors w-full",
          // Brand tint carries the active state; the label stays neutral so it
          // survives both themes and every product profile's palette.
          isCurrent(item, isActive, location)
            ? "bg-primary-50 text-on font-semibold"
            : "text-on-secondary hover:bg-surface-raised hover:text-on",
        )
      }
    >
      <Icon size={16} className="shrink-0" />
      <span className="truncate">{item.label}</span>
    </NavLink>
  );
}

/**
 * SettingsShell — sidebar layout for /settings/*.
 * Provides left sidebar navigation with static sections (General, Modules, Developer)
 * plus dynamic sections contributed by modules via `settingsSections`.
 */
export default function SettingsShell() {
  const { t } = useTranslation("common");
  const tDyn = makeTDynamic(t);
  const { enabledModules } = useModules();
  const navigate = useNavigate();
  const [headerData, setHeaderData] = useState<PageHeaderData>({});

  // The sidebar is a persistent exit from every settings form — the same
  // class of click as the module tabs, which ask before throwing unsaved
  // work away. Without this capture the tabs walked out in silence: the
  // organization's renamed name sat in a text field one tab away from
  // Poczta, and one click erased it.
  const { guardClick, guardNavigate, confirmDialogProps } = useNavLeaveGuard();

  const user = useAuthStore((s) => s.user);
  const location = useLocation();
  const [mobileNavOpen, setMobileNavOpen] = useState(false);

  const moduleSections: Array<SettingsSection & { moduleName: string }> =
    moduleRegistry.getSettingsSections(enabledModules);

  // One answer for the sidebar and the content (see settingsAccess.ts): an
  // entry is listed exactly when the screen behind it would open.
  const opens = (to: string) => {
    const key = settingsRoutePermission(to, moduleSections);
    return key === null || holdsPermission(user, key);
  };
  const isAdmin = holdsPermission(user, "admin:access");
  // A screen keyed to something narrower than `admin:access` names that key
  // when it stays shut: "for administrators" is false to a custom role that
  // holds `admin:access` and still lacks it.
  const deniedKey = settingsRoutePermission(location.pathname, moduleSections);
  const denial =
    deniedKey === null || deniedKey === "admin:access"
      ? {
          title: t("settings.access.denied"),
          hint: t("settings.access.deniedHint"),
        }
      : {
          title: t("settings.access.deniedKey"),
          hint: t("settings.access.deniedKeyHint", {
            permission: tDyn(
              `permissions:system.${deniedKey.replace(/:/g, "_")}`,
              { defaultValue: deniedKey },
            ),
          }),
        };
  // The module store lives outside /settings and guards itself.
  const listed = (item: SidebarItem) =>
    item.to.startsWith("/settings") ? opens(item.to) : isAdmin;

  const allGroups: SidebarGroup[] = [
    {
      label: null,
      items: [
        {
          label: t("settings.tabs.general"),
          to: "/settings",
          exact: true,
          icon: Settings,
        },
        // Inviting a colleague is the first thing a new administrator looks
        // for, and it sat at the foot of General, below the currency and the
        // time-zone list, with no way in from here.
        {
          label: t("settings.tabs.people"),
          to: "/settings",
          hash: PEOPLE_HASH,
          exact: true,
          icon: UsersRound,
        },
        {
          label: t("settings.tabs.profile"),
          to: "/settings/profile",
          icon: UserRound,
        },
        {
          label: t("settings.tabs.myModules"),
          to: "/settings/my-modules",
          icon: LayoutGrid,
        },
        {
          label: t("settings.tabs.about"),
          to: "/settings/about",
          icon: Info,
        },
      ],
    },
    {
      label: t("settings.shell.groupAdmin"),
      items: [
        {
          label: t("settings.tabs.modules"),
          to: "/apps",
          icon: Boxes,
        },
        {
          label: t("settings.tabs.email"),
          to: "/settings/email",
          icon: Mail,
        },
        {
          label: t("settings.tabs.ai"),
          to: "/settings/ai",
          icon: Brain,
        },
        {
          label: t("settings.tabs.auditLog"),
          to: "/settings/audit-log",
          icon: History,
        },
        {
          label: t("settings.tabs.roles"),
          to: "/settings/roles",
          icon: ShieldCheck,
        },
      ],
    },
    {
      label: t("settings.shell.groupModuleSettings"),
      items: moduleSections.map((s) => ({
        label: tDyn(s.title),
        to: `/settings/${s.path}`,
        icon: s.icon ?? Settings,
      })),
    },
  ];
  const groups = allGroups
    .map((group) => ({ ...group, items: group.items.filter(listed) }))
    .filter((group) => group.items.length > 0);

  return (
    <div className="flex flex-col md:flex-row min-h-[calc(100dvh-3.5rem)]">
      {/* Desktop sidebar */}
      <aside
        className="hidden md:flex flex-col w-52 shrink-0 border-r border-border bg-surface-card sticky top-[calc(3.5rem+var(--app-notice-height,0px))] h-[calc(100dvh-3.5rem-var(--app-notice-height,0px))] overflow-y-auto"
        onClickCapture={guardClick}
      >
        <div className="p-3 space-y-4">
          {/* Back + title */}
          <div className="flex items-center gap-1.5 px-1 pt-1">
            <Button
              variant="ghost"
              onClick={() => guardNavigate(() => navigate("/"))}
              aria-label={t("actions.back")}
              className="p-1.5 rounded-lg shrink-0"
            >
              <ChevronLeft size={16} />
            </Button>
            <span className="text-sm font-semibold text-on truncate">
              {t("settings.title")}
            </span>
          </div>

          {/* Navigation groups */}
          {groups.map((group, gi) => (
            <div key={gi} className="space-y-0.5">
              {group.label && (
                <p className="px-3 pb-0.5 text-[10px] font-medium uppercase tracking-widest text-on-muted select-none">
                  {group.label}
                </p>
              )}
              {group.items.map((item) => (
                <SettingsSidebarItem key={destination(item)} item={item} />
              ))}
            </div>
          ))}
        </div>
      </aside>

      {/* Mobile top bar — shows current section + opens nav sheet */}
      {(() => {
        const allItems = groups.flatMap((g) => g.items);
        const active =
          allItems.find((item) =>
            isCurrent(
              item,
              item.exact
                ? location.pathname === item.to
                : location.pathname.startsWith(item.to) &&
                    item.to !== "/settings",
              location,
            ),
          ) ?? allItems[0];
        const ActiveIcon = active?.icon ?? Settings;

        return (
          <>
            <div className="md:hidden flex items-center gap-2 px-3 h-11 border-b border-border bg-surface-card sticky top-[calc(3.5rem+var(--app-notice-height,0px))] z-[var(--z-module-nav)] w-full shrink-0">
              {/* `size="icon"` and not a `p-1.5` on the default size: that left a
                  16px chevron in a 28px box, which measured 28x44 on a phone.
                  The bar is 44px tall either way, so the button takes its full
                  44x44 from the variant and the glyph keeps its size. */}
              <Button
                variant="ghost"
                size="icon"
                onClick={() => guardNavigate(() => navigate("/"))}
                aria-label={t("actions.back")}
                className="shrink-0"
              >
                <ChevronLeft size={16} />
              </Button>

              <Button
                size="content"
                variant="ghost"
                onClick={() => setMobileNavOpen(true)}
                className="flex-1 justify-start gap-2 min-w-0 px-2 py-1.5 rounded-lg transition-colors"
                aria-haspopup="dialog"
              >
                <ActiveIcon size={15} className="shrink-0 text-primary-600" />
                <span className="text-sm font-semibold text-on truncate flex-1 text-left">
                  {active?.label ?? t("settings.title")}
                </span>
                <ChevronDown size={14} className="shrink-0 text-on-muted" />
              </Button>
            </div>

            {/* Mobile nav bottom sheet — the shared primitive, so the sheet
                inherits the role, the focus trap, the scroll lock and Escape
                (whose press used to land on nothing at all). */}
            <Sheet
              open={mobileNavOpen}
              onClose={() => setMobileNavOpen(false)}
              zIndex="modal-nested"
              aria-label={t("settings.title")}
            >
              <SheetHeader
                title={t("settings.title")}
                onClose={() => setMobileNavOpen(false)}
              />

              {/* Nav groups */}
              <SheetBody className="p-3 space-y-4 pb-8">
                {groups.map((group, gi) => (
                  <div key={gi} className="space-y-0.5">
                    {group.label && (
                      <p className="px-3 pb-1 text-[10px] font-medium uppercase tracking-widest text-on-muted select-none">
                        {group.label}
                      </p>
                    )}
                    {group.items.map((item) => {
                      const Icon = item.icon;
                      const isActive = isCurrent(
                        item,
                        item.exact
                          ? location.pathname === item.to
                          : location.pathname.startsWith(item.to),
                        location,
                      );
                      return (
                        <NavLink
                          key={destination(item)}
                          to={destination(item)}
                          end={item.exact}
                          // NavLink matches the path only; see the sidebar.
                          aria-current={isActive ? "page" : "false"}
                          onClick={(e) => {
                            e.preventDefault();
                            // The sheet must close whichever way the
                            // question lands — leaving for the new tab,
                            // or staying to keep typing.
                            setMobileNavOpen(false);
                            // A section of the page the reader is on is not
                            // an exit, as for the sidebar's links.
                            if (item.to === location.pathname) {
                              navigate(destination(item));
                              return;
                            }
                            guardNavigate(() => navigate(destination(item)));
                          }}
                          className={cn(
                            "flex items-center gap-3 px-3 py-3 rounded-xl text-sm font-medium transition-colors",
                            isActive
                              ? "bg-primary-50 text-on font-semibold"
                              : "text-on-secondary hover:bg-surface-raised hover:text-on",
                          )}
                        >
                          <Icon size={17} className="shrink-0" />
                          <span>{item.label}</span>
                        </NavLink>
                      );
                    })}
                  </div>
                ))}
              </SheetBody>
            </Sheet>
          </>
        );
      })()}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <PageHeaderContext.Provider
          value={{ data: headerData, setHeader: setHeaderData }}
        >
          {/* Page header — rendered by SettingsShell, consistent across all sub-pages */}
          <PageHeader
            title={headerData.title}
            subtitle={headerData.subtitle}
            actions={headerData.actions}
            backTo={headerData.backTo}
            statusBadge={headerData.statusBadge}
            className="px-4 lg:px-6 pt-6 pb-2"
          />
          <div className="px-0 sm:px-4 lg:px-6 pb-8 max-w-[1920px]">
            {/* One decision for the whole group (see settingsAccess.ts). The
                answer is a sentence, not a redirect that leaves the reader
                wondering why the address bounced. */}
            {!opens(location.pathname) ? (
              <EmptyState
                icon={ShieldAlert}
                title={denial.title}
                description={denial.hint}
              />
            ) : (
              <Suspense fallback={<LoadingSpinner />}>
                <Outlet />
              </Suspense>
            )}
          </div>
        </PageHeaderContext.Provider>
      </div>

      <ConfirmDialog {...confirmDialogProps} />
    </div>
  );
}
