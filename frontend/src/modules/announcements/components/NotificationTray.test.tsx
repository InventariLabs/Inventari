import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";
import NotificationTray from "./NotificationTray";
import { onePage } from "@/test/mocks/page";

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
  Toaster: () => null,
}));

const mockNotifications = [
  {
    id: "n1",
    title: "Low stock alert",
    message: "Item X is running low",
    is_read: false,
    created_at: new Date().toISOString(),
  },
  {
    id: "n2",
    title: "Item expired",
    message: "Item Y has expired",
    is_read: true,
    created_at: new Date().toISOString(),
  },
];

describe("NotificationTray", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    server.use(
      http.get("/api/v1/notifications", () =>
        HttpResponse.json(onePage(mockNotifications)),
      ),
    );
  });

  it("renders bell icon", async () => {
    render(<NotificationTray />);
    const button = screen.getByRole("button");
    expect(button).toBeInTheDocument();
  });

  it("names the bell with the unread count its badge shows", async () => {
    render(<NotificationTray />);
    // The badge's digit is visible text inside the button; a name without it
    // fails WCAG 2.5.3 (label in name) for anyone who says what they see.
    expect(
      await screen.findByRole("button", { name: "Notifications, 1 unread" }),
    ).toBeInTheDocument();
  });

  it("shows the whole unread count in the badge, so the name still contains it", async () => {
    const many = Array.from({ length: 12 }, (_, i) => ({
      ...mockNotifications[0],
      id: `n${i}`,
    }));
    server.use(
      http.get("/api/v1/notifications", () => HttpResponse.json(onePage(many))),
    );
    render(<NotificationTray />);

    // A badge capped at "9+" beside the name "10 unread" fails WCAG 2.5.3.
    const bell = await screen.findByRole("button", {
      name: "Notifications, 12 unread",
    });
    expect(bell).toHaveTextContent("12");
    expect(bell).not.toHaveTextContent("9+");
  });

  it("draws the badge in a pair that carries ten-pixel text", async () => {
    // white on red-500 measured 3.76:1; axe flags it as soon as a user has
    // anything unread, which made the first-screens scan depend on spec order.
    render(<NotificationTray />);
    const bell = await screen.findByRole("button", {
      name: "Notifications, 1 unread",
    });
    const badge = bell.querySelector("span[aria-hidden='true']");
    expect(badge).toHaveClass("bg-red-700", "text-white");
    expect(badge?.className).not.toContain("bg-red-500");
  });

  it("shows notifications after clicking bell", async () => {
    const user = userEvent.setup();
    render(<NotificationTray />);
    const button = screen.getByRole("button");
    await user.click(button);

    await waitFor(() => {
      expect(screen.getByText("Low stock alert")).toBeInTheDocument();
    });
    expect(screen.getByText("Item expired")).toBeInTheDocument();
  });

  it("renders empty state when no notifications", async () => {
    server.use(
      http.get("/api/v1/notifications", () => HttpResponse.json(onePage([]))),
    );

    const user = userEvent.setup();
    render(<NotificationTray />);
    const button = screen.getByRole("button");
    await user.click(button);

    await waitFor(() => {
      expect(screen.getByText("All caught up!")).toBeInTheDocument();
    });
  });
});

const notice = (id: string, overrides: Record<string, unknown> = {}) => ({
  id,
  title: `Notice ${id}`,
  content: `Body of ${id}`,
  type: "info",
  is_read: false,
  created_at: new Date().toISOString(),
  ...overrides,
});

async function openTray(items: unknown[]) {
  server.use(
    http.get("/api/v1/notifications", () => HttpResponse.json(onePage(items))),
  );
  const user = userEvent.setup();
  render(<NotificationTray />);
  await user.click(
    await screen.findByRole("button", { name: /Notifications/ }),
  );
  await screen.findByRole("dialog");
  return user;
}

describe("NotificationTray — leaving the drawer", () => {
  it("closes on Escape and gives the page its scrolling back", async () => {
    const user = await openTray([notice("a")]);
    expect(document.body.style.overflow).toBe("hidden");

    await user.keyboard("{Escape}");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(document.body.style.overflow).toBe("");
  });

  it("closes from the close button", async () => {
    const user = await openTray([notice("a")]);

    await user.click(
      screen.getByRole("button", { name: "Close notifications" }),
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closes when the reader clicks outside the drawer", async () => {
    const user = await openTray([notice("a")]);
    const backdrop = screen.getByRole("dialog").previousElementSibling;

    await user.click(backdrop as Element);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

describe("NotificationTray — acting on notifications", () => {
  it("marks one notification read without touching the others", async () => {
    const patched: Array<[string, unknown]> = [];
    server.use(
      http.patch("/api/v1/notifications/:id", async ({ params, request }) => {
        patched.push([String(params.id), await request.json()]);
        return HttpResponse.json({});
      }),
    );
    const user = await openTray([notice("a"), notice("b")]);
    const dialog = screen.getByRole("dialog");

    await user.click(
      within(dialog).getAllByRole("button", { name: "Mark as read" })[1],
    );

    await waitFor(() => expect(patched).toEqual([["b", { is_read: true }]]));
  });

  it("deletes the notification whose bin was clicked", async () => {
    const deleted: string[] = [];
    server.use(
      http.delete("/api/v1/notifications/:id", ({ params }) => {
        deleted.push(String(params.id));
        return HttpResponse.json({});
      }),
    );
    const user = await openTray([notice("a"), notice("b")]);

    await user.click(
      within(screen.getByRole("dialog")).getAllByRole("button", {
        name: "Delete notification",
      })[0],
    );

    await waitFor(() => expect(deleted).toEqual(["a"]));
  });

  it("marks everything read from the header button", async () => {
    let posts = 0;
    server.use(
      http.post("/api/v1/notifications/read-all", () => {
        posts += 1;
        return HttpResponse.json({});
      }),
    );
    // One unread notification: only the header button is offered.
    const user = await openTray([notice("a"), notice("b", { is_read: true })]);

    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "Mark all as read",
      }),
    );

    await waitFor(() => expect(posts).toBe(1));
  });

  it("offers a second mark-all at the foot once more than one is unread", async () => {
    let posts = 0;
    server.use(
      http.post("/api/v1/notifications/read-all", () => {
        posts += 1;
        return HttpResponse.json({});
      }),
    );
    const user = await openTray([notice("a"), notice("b")]);
    const buttons = within(screen.getByRole("dialog")).getAllByRole("button", {
      name: "Mark all as read",
    });
    expect(buttons).toHaveLength(2);

    await user.click(buttons[1]);

    await waitFor(() => expect(posts).toBe(1));
  });

  it("follows a notification's link, closing the drawer and marking it read", async () => {
    const patched: string[] = [];
    server.use(
      http.patch("/api/v1/notifications/:id", ({ params }) => {
        patched.push(String(params.id));
        return HttpResponse.json({});
      }),
    );
    const user = await openTray([notice("a", { link: "/inventory/items" })]);

    await user.click(screen.getByRole("link", { name: /Details/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() => expect(patched).toEqual(["a"]));
  });

  it("does not mark a notification read again when its link is followed", async () => {
    let patched = false;
    server.use(
      http.patch("/api/v1/notifications/:id", () => {
        patched = true;
        return HttpResponse.json({});
      }),
    );
    const user = await openTray([
      notice("a", { link: "/inventory/items", is_read: true }),
    ]);

    await user.click(screen.getByRole("link", { name: /Details/ }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(patched).toBe(false);
  });
});
