/**
 * useNotificationsWebSocket — opens a WebSocket to
 * ``/api/v1/ws/notifications``, offering the access token as a subprotocol,
 * and invalidates the TanStack Query notifications cache whenever the BE
 * broadcasts a new notification for the authenticated user.
 *
 * Lifecycle
 * ----------
 * - Connects on mount when an access token is present.
 * - Reconnects with exponential backoff (1s, 2s, 4s, ..., capped at 30s)
 *   on any close except an explicit client-side close or 4xx auth errors.
 * - Disconnects on unmount, on ``auth:logout``, or when the access token is
 *   cleared. On ``auth:token-refreshed`` the hook rebuilds the socket with
 *   the new token instead of leaving the previous one to ride out the
 *   access-token TTL.
 *
 * Scope
 * -----
 * The BE endpoint at ``app/api/websocket.py:NotificationHub`` authenticates
 * the JWT, registers the socket under the authenticated user id, and forwards
 * every Redis Pub/Sub message on ``notifications:user:{user_id}`` to the
 * socket as JSON. Producer side lives in
 * ``app/core/public_api/notifications.py`` — modules call
 * ``core_api.notifications.publish_async`` after their own ``db.commit()``.
 *
 * This hook is the consumer; we deliberately do not parse the message
 * payload beyond the existence check — TanStack Query refetches via the
 * existing ``useNotifications`` hook and is the SSOT for the UI state.
 */

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { tokenStore } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";

const WS_PATH = "/api/v1/ws/notifications";
/**
 * Offered just ahead of the token. A browser socket cannot set an
 * `Authorization` header, but its subprotocols travel in one
 * (`Sec-WebSocket-Protocol`); a token in the address would be written into
 * every access log between here and the backend instead.
 */
const BEARER_SUBPROTOCOL = "bearer";
const RECONNECT_BASE_MS = 1_000;
const RECONNECT_MAX_MS = 30_000;

/**
 * Resolve the absolute WebSocket URL for the current origin.
 * Falls back to ws:// on http:// and wss:// on https:// for dev.
 */
function resolveWsUrl(): string {
  if (typeof window === "undefined") return "";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  // Replace only the leading scheme; keep path empty because the path
  // is rooted at /api/v1 which is what nginx proxies to FastAPI.
  const host = window.location.host;
  return `${proto}//${host}${WS_PATH}`;
}

/** Stable predicate: was this close intentional or recoverable? */
function shouldReconnect(event: CloseEvent): boolean {
  // Auth failures (4001/4003) and policy violation (1008) are not retryable.
  if (event.code === 4001 || event.code === 4003 || event.code === 1008) {
    return false;
  }
  // 4xxx codes are client errors; do not retry.
  if (event.code >= 4000 && event.code < 5000) return false;
  return true;
}

interface UseNotificationsWebSocketOptions {
  /**
   * Whether the hook should try to connect. Set to false during logout
   * or before the token is available. Defaults to true.
   */
  enabled?: boolean;
}

/**
 * Connects to the notifications WebSocket and invalidates the
 * notifications query on every received message.
 *
 * Returns nothing — the side-effect is the TanStack Query invalidation.
 * Mount this hook once at the AppShell level so the socket stays open
 * across route changes inside the SPA.
 */
export function useNotificationsWebSocket(
  options: UseNotificationsWebSocketOptions = {},
): void {
  const { enabled = true } = options;
  const queryClient = useQueryClient();
  const socketRef = useRef<WebSocket | null>(null);
  const reconnectAttemptRef = useRef(0);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  /**
   * Which socket is "the" socket. Every connect and every deliberate close
   * moves it on, so events arriving from a socket the hook has already
   * replaced cannot schedule a reconnect for the live one.
   */
  const generationRef = useRef(0);
  const enabledRef = useRef(enabled);

  useEffect(() => {
    enabledRef.current = enabled;
  }, [enabled]);

  useEffect(() => {
    if (!enabled) return;
    const token = tokenStore.get();
    if (!token) return;

    const closeSocket = () => {
      if (reconnectTimerRef.current !== null) {
        clearTimeout(reconnectTimerRef.current);
        reconnectTimerRef.current = null;
      }
      // Moving the generation on before the socket closes says "this close
      // is ours": the close event that follows must not be read as a dropped
      // connection, and the socket it belongs to is no longer the live one.
      generationRef.current += 1;
      const socket = socketRef.current;
      socketRef.current = null;
      if (!socket) return;
      // Closing a socket whose handshake is still in flight makes the browser
      // log "WebSocket is closed before the connection is established" — at
      // sign-out, and whenever a socket is replaced before it opens. Let it
      // finish connecting, then close it; by then the close is silent.
      if (socket.readyState === WebSocket.CONNECTING) {
        socket.addEventListener(
          "open",
          () => {
            try {
              socket.close();
            } catch {
              // best-effort cleanup
            }
          },
          { once: true },
        );
        return;
      }
      try {
        socket.close();
      } catch {
        // best-effort cleanup
      }
    };

    const connect = () => {
      if (!enabledRef.current) return;
      const currentToken = tokenStore.get();
      if (!currentToken) return;

      const socket = new WebSocket(resolveWsUrl(), [
        BEARER_SUBPROTOCOL,
        currentToken,
      ]);
      const generation = ++generationRef.current;
      socketRef.current = socket;

      socket.addEventListener("open", () => {
        reconnectAttemptRef.current = 0;
      });

      socket.addEventListener("message", (event) => {
        // Any payload means "something changed for this user". We don't
        // need to parse the body — the BE NotificationHub already filters
        // by user id, so receiving anything at all is a signal to refetch.
        if (typeof event.data === "string" && event.data.length > 0) {
          queryClient.invalidateQueries({
            queryKey: queryKeys.notifications.all,
          });
        }
      });

      socket.addEventListener("close", (event) => {
        // A socket the hook has already replaced (logout, token rotation)
        // fires its close after the new one exists; only the live socket
        // speaks for the connection.
        if (generationRef.current !== generation) return;
        socketRef.current = null;
        if (!enabledRef.current) return;
        if (!shouldReconnect(event)) return;

        const attempt = reconnectAttemptRef.current + 1;
        reconnectAttemptRef.current = attempt;
        const delay = Math.min(
          RECONNECT_MAX_MS,
          RECONNECT_BASE_MS * 2 ** Math.min(attempt - 1, 5),
        );
        reconnectTimerRef.current = setTimeout(connect, delay);
      });

      socket.addEventListener("error", () => {
        // The close handler will fire right after — reconnect logic lives there.
      });
    };

    connect();

    const handleLogout = () => closeSocket();
    const handleTokenRefreshed = () => {
      // The current socket was opened with the old (now-invalidated) token;
      // rebuild it with the new one.
      closeSocket();
      if (enabledRef.current) connect();
    };
    window.addEventListener("auth:logout", handleLogout);
    window.addEventListener("auth:token-refreshed", handleTokenRefreshed);

    return () => {
      window.removeEventListener("auth:logout", handleLogout);
      window.removeEventListener("auth:token-refreshed", handleTokenRefreshed);
      closeSocket();
    };
  }, [enabled, queryClient]);
}
