import { useState, useEffect } from "react";
import { createPortal } from "react-dom";
import {
  Bell,
  BellOff,
  Check,
  Trash2,
  X,
  Info,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
} from "lucide-react";
import { formatDate } from "@/utils/helpers";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import {
  useNotifications,
  useMarkNotificationRead,
  useMarkAllNotificationsRead,
  useDeleteNotification,
} from "@/modules/announcements/hooks/useNotifications";
import { Button } from "@/components/ui/Button";
import { useFocusTrap } from "@/hooks/useFocusTrap";

export default function NotificationTray() {
  const { t } = useTranslation(["common"]);
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useFocusTrap(isOpen);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === "Escape") setIsOpen(false);
    };
    document.addEventListener("keydown", handleEscape);
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", handleEscape);
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const { data: notifications, isLoading } = useNotifications();
  const markReadMutation = useMarkNotificationRead();
  const markAllReadMutation = useMarkAllNotificationsRead();
  const deleteMutation = useDeleteNotification();

  const unreadCount = notifications?.filter((n) => !n.is_read).length || 0;

  const getIcon = (type: string) => {
    switch (type) {
      case "success":
        return <CheckCircle2 className="text-accent-500" size={18} />;
      case "warning":
        return <AlertTriangle className="text-amber-500" size={18} />;
      case "error":
        return <AlertCircle className="text-red-500" size={18} />;
      default:
        return <Info className="text-blue-500" size={18} />;
    }
  };

  return (
    <>
      <Button
        onClick={() => setIsOpen(true)}
        variant="ghost"
        size="icon"
        className="relative rounded-xl active:scale-95"
        aria-label={
          unreadCount > 0
            ? `${t("notifications.title")}, ${t("notifications.unreadCount", { count: unreadCount })}`
            : t("notifications.title")
        }
      >
        <Bell
          size={22}
          className={unreadCount > 0 ? "animate-swing origin-top" : ""}
        />
        {unreadCount > 0 && (
          // The name above carries the count. The badge shows the same
          // number, uncapped: a "9+" on screen against "10 unread" in the
          // name fails WCAG 2.5.3 (label in name), which axe counts even
          // when the badge is hidden from assistive tech.
          <span
            aria-hidden="true"
            className="absolute top-1 right-1 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-red-700 text-[10px] font-medium text-white ring-2 ring-white"
          >
            {unreadCount}
          </span>
        )}
      </Button>

      {/* Drawer Overlay & Backdrop */}
      {isOpen &&
        createPortal(
          <div className="fixed inset-0 z-[var(--z-notification)] flex justify-end overflow-hidden">
            <div
              className="absolute inset-0 bg-black/50 backdrop-blur-sm animate-in fade-in duration-300"
              onClick={() => setIsOpen(false)}
            />

            {/* Drawer Content */}
            <div
              ref={containerRef}
              role="dialog"
              aria-modal="true"
              aria-labelledby="notification-tray-title"
              className="relative w-full max-w-md bg-surface-card h-full shadow-lg flex flex-col animate-in slide-in-from-right duration-500 ease-out"
            >
              <div className="p-6 border-b flex items-center justify-between bg-surface-card sticky top-0 z-10">
                <div className="flex items-center gap-3">
                  <div className="w-10 h-10 bg-primary-100 text-primary-600 rounded-xl flex items-center justify-center">
                    <Bell size={24} />
                  </div>
                  <div>
                    <h3
                      id="notification-tray-title"
                      className="font-semibold text-xl text-on leading-none mb-1"
                    >
                      {t("notifications.title")}
                    </h3>
                    <p className="text-xs text-on-secondary font-medium uppercase tracking-wider">
                      {t("notifications.unreadCount", { count: unreadCount })}
                    </p>
                  </div>
                </div>
                <div className="flex items-center gap-2">
                  {unreadCount > 0 && (
                    <Button
                      onClick={() => markAllReadMutation.mutate()}
                      variant="ghost"
                      className="p-3 rounded-xl"
                      title={t("notifications.markAllRead")}
                      aria-label={t("notifications.markAllRead")}
                    >
                      <Check size={20} />
                    </Button>
                  )}
                  <Button
                    onClick={() => setIsOpen(false)}
                    variant="ghost"
                    className="p-3 rounded-xl"
                    aria-label={t("notifications.close")}
                  >
                    <X size={20} />
                  </Button>
                </div>
              </div>

              <div className="overflow-y-auto flex-1 overscroll-contain">
                {isLoading ? (
                  <div className="flex flex-col items-center justify-center py-20 gap-4">
                    <div className="w-8 h-8 border-4 border-primary-200 border-t-primary-600 rounded-full animate-spin" />
                    <p className="text-sm text-on-muted font-medium">
                      {t("notifications.loading")}
                    </p>
                  </div>
                ) : notifications?.length === 0 ? (
                  <div className="flex flex-col items-center justify-center py-20 px-10 text-center">
                    <div className="w-20 h-20 bg-surface text-on-muted rounded-3xl flex items-center justify-center mb-6">
                      <BellOff size={40} />
                    </div>
                    <h4 className="text-lg font-semibold text-on mb-2">
                      {t("notifications.allCaughtUp")}
                    </h4>
                    <p className="text-sm text-on-secondary leading-relaxed">
                      {t("notifications.emptyMessage")}
                    </p>
                  </div>
                ) : (
                  <div className="divide-y divide-border pb-20">
                    {notifications?.map((n) => (
                      <div
                        key={n.id}
                        className={`group p-6 flex gap-4 transition-all hover:bg-surface/50 ${n.is_read ? "opacity-60 grayscale-[0.5]" : "bg-primary-50/20"}`}
                      >
                        <div className="shrink-0 mt-1">
                          <div
                            className={`w-10 h-10 rounded-2xl flex items-center justify-center bg-surface-card shadow-sm border border-border group-hover:scale-110 transition-transform`}
                          >
                            {getIcon(n.type)}
                          </div>
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex justify-between items-start gap-2 mb-1">
                            <p
                              className={`text-sm leading-tight ${n.is_read ? "text-on-secondary font-medium" : "font-semibold text-on"}`}
                            >
                              {n.title}
                            </p>
                            <div className="flex shrink-0 transition-opacity md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100">
                              {!n.is_read && (
                                <Button
                                  onClick={() => markReadMutation.mutate(n.id)}
                                  variant="ghost"
                                  className="p-2 rounded-lg"
                                  title={t("notifications.markAsRead")}
                                  aria-label={t("notifications.markAsRead")}
                                >
                                  <Check size={16} />
                                </Button>
                              )}
                              <Button
                                onClick={() => deleteMutation.mutate(n.id)}
                                variant="ghostDanger"
                                className="p-2 rounded-lg"
                                title={t("actions.delete")}
                                aria-label={t(
                                  "notifications.deleteNotification",
                                )}
                              >
                                <Trash2 size={16} />
                              </Button>
                            </div>
                          </div>
                          <p className="text-sm text-on-secondary leading-relaxed mb-3">
                            {n.content}
                          </p>
                          <div className="flex items-center justify-between">
                            <p className="text-[10px] text-on-muted font-medium uppercase tracking-wider">
                              {formatDate(n.created_at, t)}
                            </p>
                            {n.link && (
                              <Link
                                to={n.link}
                                onClick={() => {
                                  setIsOpen(false);
                                  if (!n.is_read) markReadMutation.mutate(n.id);
                                }}
                                className="text-[10px] font-medium text-on-primary uppercase underline underline-offset-4 decoration-2"
                              >
                                {t("notifications.details")} →
                              </Link>
                            )}
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              {unreadCount > 1 && (
                <div className="p-4 bg-surface/80 backdrop-blur-md border-t sticky bottom-0 z-10">
                  <Button
                    onClick={() => markAllReadMutation.mutate()}
                    variant="outline"
                    className="w-full py-4 rounded-2xl font-semibold"
                  >
                    {t("notifications.markAllRead")}
                  </Button>
                </div>
              )}
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
