import { describe, it, expect, beforeEach } from "vitest";
import { http, HttpResponse } from "msw";
import userEvent from "@testing-library/user-event";

import { render, screen } from "@/test/utils";
import { server } from "@/test/mocks/server";
import { withLanguage } from "@/test/mocks/i18n";

import AnnouncementBanner from "./AnnouncementBanner";
import { onePage } from "@/test/mocks/page";

const ANNOUNCEMENT = {
  id: "a1",
  title: "Przerwa serwisowa",
  content: "Dziś o 22:00 aplikacja będzie niedostępna.",
  type: "info",
};

/**
 * The close button is an icon 14×14 with no visible text, so its accessible
 * name is the whole of what a screen reader gets. It used to be "Odrzuć" —
 * the word the approvals queue uses to reject a request, and both controls
 * stood on one screen. German and French chose the "close" sense; Polish now
 * uses the word the rest of the app closes windows with.
 */
describe("AnnouncementBanner — the close button is named for closing", () => {
  beforeEach(() => {
    localStorage.clear();
    server.use(
      http.get("/api/v1/announcements/active", () =>
        HttpResponse.json(onePage([ANNOUNCEMENT])),
      ),
    );
  });

  it("uses the closing word, not the rejecting one (pl)", async () => {
    await withLanguage("pl", async () => {
      render(<AnnouncementBanner />);

      expect(
        await screen.findByRole("button", { name: "Zamknij" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /Odrzuć/ })).toBeNull();
    });
  });
});

describe("AnnouncementBanner — dismissing", () => {
  const SECOND = {
    id: "a2",
    title: "Maintenance",
    content: "Tonight at 22:00.",
    type: "warning",
  };

  beforeEach(() => {
    localStorage.clear();
    server.use(
      http.get("/api/v1/announcements/active", () =>
        HttpResponse.json(onePage([ANNOUNCEMENT, SECOND])),
      ),
    );
  });

  it("hides only the dismissed announcement and keeps it hidden after a reload", async () => {
    const first = render(<AnnouncementBanner />);
    await screen.findByText(ANNOUNCEMENT.title);
    await screen.findByText(SECOND.title);

    await userEvent.click(
      screen.getAllByRole("button", { name: "Dismiss" })[0],
    );

    expect(screen.queryByText(ANNOUNCEMENT.title)).not.toBeInTheDocument();
    expect(screen.getByText(SECOND.title)).toBeInTheDocument();

    first.unmount();
    render(<AnnouncementBanner />);
    await screen.findByText(SECOND.title);
    expect(screen.queryByText(ANNOUNCEMENT.title)).not.toBeInTheDocument();
  });

  it("removes the banner altogether once the last announcement is dismissed", async () => {
    render(<AnnouncementBanner />);
    await screen.findByText(ANNOUNCEMENT.title);

    await userEvent.click(
      screen.getAllByRole("button", { name: "Dismiss" })[0],
    );
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    expect(screen.queryByRole("region")).not.toBeInTheDocument();
  });
});
