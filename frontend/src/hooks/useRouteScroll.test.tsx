import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Link, MemoryRouter, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { useRouteScroll } from "./useRouteScroll";

function Shell() {
  useRouteScroll();
  const navigate = useNavigate();
  return (
    <>
      <Link to="/list/1">detail</Link>
      <Link to="/list#part">part</Link>
      <Link to="/list">whole</Link>
      <button onClick={() => navigate(-1)}>back</button>
    </>
  );
}

function setScroll(y: number) {
  Object.defineProperty(window, "scrollY", { value: y, configurable: true });
  window.dispatchEvent(new Event("scroll"));
}

describe("useRouteScroll", () => {
  let scrollTo: ReturnType<typeof vi.fn>;
  beforeEach(() => {
    sessionStorage.clear();
    scrollTo = vi.fn();
    window.scrollTo = scrollTo as unknown as typeof window.scrollTo;
    // A page tall enough to reach 900.
    Object.defineProperty(document.documentElement, "scrollHeight", {
      value: 5000,
      configurable: true,
    });
    Object.defineProperty(window, "innerHeight", {
      value: 800,
      configurable: true,
    });
  });
  afterEach(() => setScroll(0));

  function renderAt(path: string) {
    return render(
      <MemoryRouter initialEntries={["/list", path]} initialIndex={1}>
        <Shell />
      </MemoryRouter>,
    );
  }

  it("opens a screen reached by a link at its top", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/list"]}>
        <Shell />
      </MemoryRouter>,
    );
    setScroll(900);
    scrollTo.mockClear();

    await user.click(screen.getByRole("link", { name: "detail" }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
  });

  it("scrolls to the top when a link leaves a section of the same page", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/list#part"]}>
        <Shell />
      </MemoryRouter>,
    );
    setScroll(900);
    scrollTo.mockClear();

    await user.click(screen.getByRole("link", { name: "whole" }));

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
  });

  it("returns to where the earlier screen was left when going back", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/list"]}>
        <Shell />
      </MemoryRouter>,
    );
    setScroll(900);
    await user.click(screen.getByRole("link", { name: "detail" }));
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
    setScroll(0);
    scrollTo.mockClear();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "back" }));
    });

    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 900));
  });

  it("keeps trying while the page is still too short to reach the position", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/list"]}>
        <Shell />
      </MemoryRouter>,
    );
    setScroll(900);
    await user.click(screen.getByRole("link", { name: "detail" }));
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
    // The list is fetched again: only 700 px of it is there at first.
    Object.defineProperty(document.documentElement, "scrollHeight", {
      value: 1500,
      configurable: true,
    });
    scrollTo.mockClear();

    await act(async () => {
      await user.click(screen.getByRole("button", { name: "back" }));
    });
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 700));
    expect(scrollTo).not.toHaveBeenCalledWith(0, 900);

    Object.defineProperty(document.documentElement, "scrollHeight", {
      value: 5000,
      configurable: true,
    });
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 900));
  });

  it("does not pull a reader back once they have touched the page", async () => {
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/list"]}>
        <Shell />
      </MemoryRouter>,
    );
    setScroll(900);
    await user.click(screen.getByRole("link", { name: "detail" }));
    await waitFor(() => expect(scrollTo).toHaveBeenCalledWith(0, 0));
    Object.defineProperty(document.documentElement, "scrollHeight", {
      value: 1000,
      configurable: true,
    });
    scrollTo.mockClear();
    await user.click(screen.getByRole("button", { name: "back" }));
    await waitFor(() => expect(scrollTo).toHaveBeenCalled());

    window.dispatchEvent(new Event("touchstart"));
    scrollTo.mockClear();
    await new Promise((r) => setTimeout(r, 80));

    expect(scrollTo).not.toHaveBeenCalled();
  });

  it("leaves the position alone when only the query string changes", () => {
    renderAt("/list?q=x");
    expect(scrollTo).not.toHaveBeenCalledWith(0, 0);
  });
});
