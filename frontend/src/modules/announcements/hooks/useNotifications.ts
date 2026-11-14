import { useQuery } from "@tanstack/react-query";
import { useAppMutation } from "@/lib/api/mutationFactory";
import { notificationsApi } from "@/modules/announcements/api/announcements";
import { invalidation } from "@/lib/api/invalidation";
import { useNotificationsSocketLive } from "@/modules/announcements/hooks/useNotificationsWebSocket";
import { queryKeys } from "@/hooks/queries/keys";
import type { UserNotification } from "@/modules/announcements/types/notifications";

// ─── Queries ─────────────────────────────────────────────────────────────────

export function useNotifications(unreadOnly = false) {
  // The NotificationsWebSocketBridge (<AppShell/>) opens a WebSocket that
  // invalidates this query whenever the BE publishes a new notification.
  // While that socket is open nothing else needs to ask; the low-frequency
  // poll is the safety net for the time it is not (dev tooling, a network
  // policy blocking ws://, a reconnect in progress).
  const socketLive = useNotificationsSocketLive();
  return useQuery<UserNotification[]>({
    queryKey: queryKeys.notifications.all,
    queryFn: () => notificationsApi.getAll(unreadOnly),
    staleTime: 5 * 60 * 1000,
    refetchInterval: socketLive ? false : 5 * 60 * 1000,
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
