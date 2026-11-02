import React from "react";
import { AlertTriangle, Zap, X, Info } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/Button";
import { useActiveAnnouncements } from "@/modules/announcements/hooks/useAnnouncements";
import { useLocalStorage } from "@/hooks/useLocalStorage";

const AnnouncementBanner: React.FC = () => {
  const { t } = useTranslation("announcements");
  const [dismissedIds, setDismissedIds] = useLocalStorage<string[]>(
    "dismissed_announcements",
    [],
  );

  const { data: announcements } = useActiveAnnouncements();

  const handleDismiss = (id: string) => {
    setDismissedIds([...dismissedIds, id]);
  };

  const activeAnnouncements =
    announcements?.filter((a) => !dismissedIds.includes(a.id)) || [];

  if (activeAnnouncements.length === 0) return null;

  // Each theme also carried a `border` — `border-l-red-500 border-b-gray-100`
  // and two siblings — that the banner never rendered and that named a palette
  // value rather than a token, so in the dark theme it would have drawn a pale
  // line. Gone rather than fixed: nothing read it.
  const getTheme = (type: string) => {
    switch (type) {
      case "critical":
      case "downtime":
        return {
          color: "text-on-danger",
          bg: "bg-surface-card",
          iconBg: "bg-red-500/10",
        };
      case "warning":
        return {
          color: "text-on-warning",
          bg: "bg-surface-card",
          iconBg: "bg-amber-500/10",
        };
      default:
        return {
          color: "text-on-info",
          bg: "bg-surface-card",
          iconBg: "bg-primary-500/10",
        };
    }
  };

  const getIcon = (type: string) => {
    switch (type) {
      case "critical":
      case "downtime":
        return <Zap size={14} className="fill-current" />;
      case "warning":
        return <AlertTriangle size={14} className="fill-current" />;
      default:
        return <Info size={14} className="fill-current" />;
    }
  };

  return (
    <div
      role="region"
      aria-label={t("region")}
      className="w-full flex flex-col items-center pointer-events-none py-2 gap-2"
    >
      {activeAnnouncements.map((a, idx) => {
        const theme = getTheme(a.type);
        return (
          <div
            key={a.id}
            className={`
              pointer-events-auto
              relative
              flex items-center justify-center gap-4
              max-w-[90%] md:max-w-2xl px-6 py-1.5
              ${theme.bg} border border-border rounded-full
              animate-in slide-in-from-top-4 duration-500
              shadow-sm
            `}
            style={{ animationDelay: `${idx * 100}ms` }}
          >
            <div
              className={`shrink-0 w-6 h-6 rounded-full flex items-center justify-center ${theme.iconBg} ${theme.color}`}
            >
              {getIcon(a.type)}
            </div>

            <div className="flex items-center gap-3 min-w-0">
              <span
                className={`text-[10px] font-medium uppercase tracking-[0.15em] ${theme.color} hidden sm:inline`}
              >
                {/* The type used to render raw — `warning`, `critical`,
                    `downtime` — in English, on a screen with five catalogs. */}
                {t(`types.${a.type}` as "types.info", {
                  defaultValue: a.type,
                })}
              </span>
              <div className="w-[1px] h-3 bg-surface-inset hidden sm:block" />
              <div className="flex items-center gap-2 truncate">
                <span className="text-xs font-medium text-on truncate">
                  {a.title}
                </span>
                <span className="text-xs text-on-secondary truncate">
                  {a.content}
                </span>
              </div>
            </div>

            {/* `iconSm` is the 24 px touch floor with room to spare; the
                negative margins keep the pill as slim as the 14 px glyph made
                it. */}
            <Button
              variant="ghost"
              size="iconSm"
              onClick={() => handleDismiss(a.id)}
              className="shrink-0 -my-1.5 -mr-4 text-on-muted hover:text-on transition-colors"
              aria-label={t("actions.dismiss")}
            >
              <X size={14} />
            </Button>
          </div>
        );
      })}
    </div>
  );
};

export default AnnouncementBanner;
