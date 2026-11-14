/**
 * Tests for useNotificationsWebSocket — covers the lifecycle contract that
 * keeps the FE notification tray in sync with the BE ``NotificationHub``.
 *
 * The hook intentionally avoids re-renders when the token rotates; instead
 * it rebuilds the WebSocket via the ``auth:token-refreshed`` window event
 * dispatched by the silent-refresh interceptor (see
 * ``lib/api/client.ts``).
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { type ReactNode } from "react";

import { tokenStore } from "@/lib/api/client";
import { queryKeys } from "@/hooks/queries/keys";

import {
  useNotificationsSocketLive,
  useNotificationsWebSocket,
} from "@/modules/announcements/hooks/useNotificationsWebSocket";
import { useNotifications } from "@/modules/announcements/hooks/useNotifications";

class FakeWebSocket {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSING = 2;
  static readonly CLOSED = 3;

  static instances: FakeWebSocket[] = [];

  url: string;
  protocols: string[];
  readyState: number = FakeWebSocket.OPEN;
  sent: unknown[] = [];
  listeners: Record<string, Array<(event: unknown) => void>> = {};
  closedByClient = false;
  /**
   * A real browser dispatches `close` some time after `close()` is called,
   * not inside the call. Set this to see the hook through that gap; the test
   * then delivers the event itself with `finishClose`.
   */
  deferClose = false;
  private pendingClose: { code: number } | null = null;

  constructor(url: string, protocols: string | string[] = []) {
    this.url = url;
    this.protocols = typeof protocols === "string" ? [protocols] : protocols;
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event: unknown) => void) {
    (this.listeners[type] ??= []).push(listener);
  }

  send(data: string) {
    this.sent.push(data);
  }

  close(code = 1000) {
    this.closedByClient = true;
    if (this.deferClose) {
      this.readyState = FakeWebSocket.CLOSING;
      this.pendingClose = { code };
      return;
    }
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code, reason: "", wasClean: true });
  }

  finishClose() {
    if (!this.pendingClose) return;
    const { code } = this.pendingClose;
    this.pendingClose = null;
    this.readyState = FakeWebSocket.CLOSED;
    this.dispatch("close", { code, reason: "", wasClean: true });
  }

  dispatch(type: string, event: unknown) {
    for (const listener of this.listeners[type] ?? []) listener(event);
  }
}

const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

function makeWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

beforeEach(() => {
  FakeWebSocket.instances = [];
  tokenStore.set("initial-token");
  vi.stubGlobal("WebSocket", FakeWebSocket as unknown as typeof WebSocket);
});

afterEach(() => {
  tokenStore.clear();
  vi.unstubAllGlobals();
});

describe("useNotificationsWebSocket", () => {
  it("offers the current token as a subprotocol, never in the address", async () => {
    // An address is written down by every access log it passes through; the
    // subprotocols travel in a header, as the token does on every other call.
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();
    expect(FakeWebSocket.instances).toHaveLength(1);
    const socket = FakeWebSocket.instances[0];
    expect(new URL(socket.url).pathname).toBe("/api/v1/ws/notifications");
    expect(socket.url).not.toContain("initial-token");
    expect(socket.protocols).toEqual(["bearer", "initial-token"]);
  });

  it("invalidates the notifications query on a received message", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const invalidateWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    renderHook(() => useNotificationsWebSocket(), {
      wrapper: invalidateWrapper,
    });
    await flush();

    const socket = FakeWebSocket.instances[0];
    act(() => socket.dispatch("message", { data: '{"id":"n1"}' }));

    expect(invalidateSpy).toHaveBeenCalledWith({
      queryKey: queryKeys.notifications.all,
    });
  });

  it("ignores empty message payloads", async () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const invalidateSpy = vi.spyOn(queryClient, "invalidateQueries");
    const invalidateWrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );

    renderHook(() => useNotificationsWebSocket(), {
      wrapper: invalidateWrapper,
    });
    await flush();

    const socket = FakeWebSocket.instances[0];
    act(() => socket.dispatch("message", { data: "" }));

    expect(invalidateSpy).not.toHaveBeenCalled();
  });

  it("closes the socket on unmount", async () => {
    const { unmount } = renderHook(() => useNotificationsWebSocket(), {
      wrapper: makeWrapper(),
    });
    await flush();

    const socket = FakeWebSocket.instances[0];
    unmount();

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it("does not connect when no token is available", async () => {
    tokenStore.clear();
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();
    expect(FakeWebSocket.instances).toHaveLength(0);
  });

  it("does not reconnect on close code 4001 (auth failure)", async () => {
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    const socket = FakeWebSocket.instances[0];
    act(() =>
      socket.dispatch("close", { code: 4001, reason: "Missing token" }),
    );
    // Wait long enough for any (forbidden) reconnect to fire — backoff base is 1s.
    await new Promise((resolve) => setTimeout(resolve, 1_500));

    expect(FakeWebSocket.instances).toHaveLength(1);
  });

  it("reconnects on abnormal close (code 1006) after backoff", async () => {
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    const socket = FakeWebSocket.instances[0];
    act(() => socket.dispatch("close", { code: 1006, reason: "" }));
    // Base backoff is 1s, plus scheduling jitter.
    await new Promise((resolve) => setTimeout(resolve, 1_500));

    expect(FakeWebSocket.instances.length).toBeGreaterThanOrEqual(2);
    expect(FakeWebSocket.instances[1].protocols).toEqual([
      "bearer",
      "initial-token",
    ]);
  });

  it("leaves reconnecting to the close that follows an error, not the error itself", async () => {
    vi.useFakeTimers();
    try {
      renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const socket = FakeWebSocket.instances[0];

      act(() => socket.dispatch("error", new Event("error")));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });
      // The error alone neither reopens the socket nor closes it.
      expect(FakeWebSocket.instances).toHaveLength(1);
      expect(socket.closedByClient).toBe(false);

      act(() => socket.dispatch("close", { code: 1006, reason: "" }));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(2_000);
      });
      expect(FakeWebSocket.instances).toHaveLength(2);
    } finally {
      vi.useRealTimers();
    }
  });

  it("closes the socket when the user logs out", async () => {
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    const socket = FakeWebSocket.instances[0];
    act(() => window.dispatchEvent(new CustomEvent("auth:logout")));
    await flush();

    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it("waits for the handshake before closing a socket that is still connecting", async () => {
    // Closing a socket mid-handshake makes the browser log "WebSocket is
    // closed before the connection is established" — at sign-out, and on
    // every page load where a socket is replaced before it opens.
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    const socket = FakeWebSocket.instances[0];
    socket.readyState = FakeWebSocket.CONNECTING;
    act(() => window.dispatchEvent(new CustomEvent("auth:logout")));

    expect(socket.readyState).toBe(FakeWebSocket.CONNECTING);

    act(() => socket.dispatch("open", {}));
    expect(socket.readyState).toBe(FakeWebSocket.CLOSED);
  });

  it("does not reconnect a socket that a token rotation replaced mid-handshake", async () => {
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    const first = FakeWebSocket.instances[0];
    first.readyState = FakeWebSocket.CONNECTING;
    tokenStore.set("rotated-token");
    act(() => window.dispatchEvent(new CustomEvent("auth:token-refreshed")));
    await flush();

    expect(FakeWebSocket.instances).toHaveLength(2);
    expect(FakeWebSocket.instances[1].protocols).toEqual([
      "bearer",
      "rotated-token",
    ]);

    // The replaced socket opens late and closes silently; its close event
    // belongs to nobody and must not schedule a reconnect.
    act(() => first.dispatch("open", {}));
    expect(first.readyState).toBe(FakeWebSocket.CLOSED);
    await new Promise((resolve) => setTimeout(resolve, 1_500));
    expect(FakeWebSocket.instances).toHaveLength(2);
  });

  it("does not reconnect when a replaced socket's close arrives after the new socket exists", async () => {
    // A browser delivers `close` after `close()` has returned, so by then the
    // replacement is already live. A flag shared by both sockets ("this close
    // was ours") has been cleared by the new connect() at that point, and the
    // late close read as a dropped connection: a third socket, opened behind
    // the live one. Each socket has to be judged by its own generation.
    vi.useFakeTimers();
    try {
      renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      const first = FakeWebSocket.instances[0];
      first.deferClose = true;

      tokenStore.set("rotated-token");
      act(() => window.dispatchEvent(new CustomEvent("auth:token-refreshed")));
      expect(FakeWebSocket.instances).toHaveLength(2);
      expect(first.readyState).toBe(FakeWebSocket.CLOSING);

      // The close lands now, after the replacement was built, with a code
      // that would normally earn a retry.
      act(() => first.finishClose());
      await act(async () => {
        await vi.advanceTimersByTimeAsync(60_000);
      });

      expect(FakeWebSocket.instances).toHaveLength(2);
      expect(FakeWebSocket.instances[1].protocols).toEqual([
        "bearer",
        "rotated-token",
      ]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("rebuilds the socket with the new token after a silent refresh", async () => {
    tokenStore.set("rotated-token");
    renderHook(() => useNotificationsWebSocket(), { wrapper: makeWrapper() });
    await flush();

    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(FakeWebSocket.instances[0].protocols).toEqual([
      "bearer",
      "rotated-token",
    ]);
  });

  describe("polling beside the socket", () => {
    const pollingOf = (queryClient: QueryClient) => {
      const query = queryClient
        .getQueryCache()
        .find({ queryKey: queryKeys.notifications.all });
      return query?.observers[0]?.options.refetchInterval;
    };

    function renderBoth() {
      const queryClient = new QueryClient({
        defaultOptions: { queries: { retry: false } },
      });
      const wrapper = ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={queryClient}>
          {children}
        </QueryClientProvider>
      );
      const view = renderHook(
        () => {
          useNotificationsWebSocket();
          return {
            live: useNotificationsSocketLive(),
            notifications: useNotifications(),
          };
        },
        { wrapper },
      );
      return { queryClient, ...view };
    }

    it("polls while the socket is not open and stops once it is", async () => {
      const { queryClient, result } = renderBoth();
      await flush();
      expect(result.current.live).toBe(false);
      expect(pollingOf(queryClient)).toBe(5 * 60 * 1000);

      act(() => FakeWebSocket.instances[0].dispatch("open", {}));
      expect(result.current.live).toBe(true);
      expect(pollingOf(queryClient)).toBe(false);
    });

    it("polls again when the socket drops", async () => {
      const { queryClient, result } = renderBoth();
      await flush();
      const socket = FakeWebSocket.instances[0];
      act(() => socket.dispatch("open", {}));
      act(() => socket.dispatch("close", { code: 1006 }));

      expect(result.current.live).toBe(false);
      expect(pollingOf(queryClient)).toBe(5 * 60 * 1000);
    });

    it("asks once for what the gap swallowed when a dropped socket comes back", async () => {
      vi.useFakeTimers();
      try {
        const { queryClient } = renderBoth();
        await act(async () => {
          await vi.advanceTimersByTimeAsync(0);
        });
        const spy = vi.spyOn(queryClient, "invalidateQueries");
        const first = FakeWebSocket.instances[0];
        act(() => first.dispatch("open", {}));
        // The first connection has no gap behind it.
        expect(spy).not.toHaveBeenCalled();

        act(() => first.dispatch("close", { code: 1006 }));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(2_000);
        });
        act(() => FakeWebSocket.instances[1].dispatch("open", {}));
        expect(spy).toHaveBeenCalledWith({
          queryKey: queryKeys.notifications.all,
        });
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
