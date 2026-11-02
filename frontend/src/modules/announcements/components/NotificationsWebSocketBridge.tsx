/**
 * NotificationsWebSocketBridge — mount-once component that owns the
 * notification WebSocket lifetime. Rendered next to <NotificationTray />
 * in AppShell so the socket stays open across SPA route changes.
 *
 * Renders nothing — the side-effect is opening the WebSocket via
 * ``useNotificationsWebSocket``.
 */
import { useNotificationsWebSocket } from "@/modules/announcements/hooks/useNotificationsWebSocket";

export default function NotificationsWebSocketBridge(): null {
  useNotificationsWebSocket();
  return null;
}
