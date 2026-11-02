import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { notificationsApi } from "@/modules/announcements/api/announcements";
import { invalidation } from "@/lib/api/invalidation";
import { queryKeys } from "@/hooks/queries/keys";
import type { UserNotification } from "@/modules/announcements/types/notifications";

// ─── Queries ─────────────────────────────────────────────────────────────────

export function useNotifications(unreadOnly = false) {
  // The NotificationsWebSocketBridge (<AppShell/>) opens a WebSocket that
  // invalidates this query whenever the BE publishes a new notification,
  // so polling is no longer the primary refresh path. We keep a long
  // staleTime + a low-frequency interval as a safety net for sessions
  // where the WS is unavailable (dev tooling, browser quirks, network
  // policy blocking ws://). When WS works the user gets sub-second pushes.
  return useQuery<UserNotification[]>({
    queryKey: queryKeys.notifications.all,
    queryFn: () => notificationsApi.getAll(unreadOnly),
    staleTime: 5 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000,
    refetchOnWindowFocus: true,
  });
}

// ─── Mutations ───────────────────────────────────────────────────────────────

export function useMarkNotificationRead() {
  return useAppMutation(
    (id: string) => notificationsApi.markRead(id),
    (qc) => invalidation.notifications(qc),
  );
}

export function useMarkAllNotificationsRead() {
  return useAppMutation(
    () => notificationsApi.markAllRead(),
    (qc) => invalidation.notifications(qc),
  );
}

export function useDeleteNotification() {
  return useAppMutation(
    (id: string) => notificationsApi.delete(id),
    (qc) => invalidation.notifications(qc),
  );
}
