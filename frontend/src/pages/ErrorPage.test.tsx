/**
 * The screen named by the route tree's `errorElement`, in the reader's
 * language.
 *
 * It used to be three English literals — "Oops! Something went wrong", "An
 * unexpected error occurred." and "Go back home" — so the one moment the
 * application owed the reader an explanation was the one it stopped speaking
 * their language. What this pins is not the wording but where the words come
 * from: the catalogue.
 *
 * `useRouteError` is mocked rather than reached through a router, and that is
 * deliberate. The rendering is what is under test here; the wiring is pinned
 * where it lives — `App.routerError.test.tsx` builds the route tree this
 * screen is the `errorElement` of and plants a route that fails.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

const routeError = vi.hoisted(() => ({
  current: new Error("planted: the screen broke"),
}));

vi.mock("react-router-dom", async () => {
  const actual = await vi.importActual("react-router-dom");
  return {
    ...actual,
    useRouteError: () => routeError.current,
  };
});

import { withLanguage } from "@/test/mocks/i18n";
import ErrorPage from "./ErrorPage";

describe("ErrorPage", () => {
  afterEach(() => {
    routeError.current = new Error("planted: the screen broke");
  });

  it("says in Polish what went wrong and how to get back", async () => {
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    await withLanguage("pl", () => {
      expect(screen.getByRole("heading").textContent).toBe(
        "Coś poszło nie tak",
      );
      expect(screen.getByText(/nieoczekiwany błąd/i)).toBeTruthy();
      expect(screen.getByRole("link", { name: "Strona główna" })).toBeTruthy();
      expect(
        screen.getByRole("button", { name: "Odśwież stronę" }),
      ).toBeTruthy();
      expect(screen.queryByText(/poinformowani/i)).toBeNull();
    });
  });

  it("names the same three keys the error boundary names", () => {
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    // The two literals this screen used to carry, gone in every language.
    expect(screen.queryByText(/Oops! Something went wrong/)).toBeNull();
    expect(screen.queryByText(/Go back home/)).toBeNull();
    expect(screen.getByRole("heading").textContent).toBe(
      "Something went wrong",
    );
    expect(screen.getByRole("link", { name: "Go Home" })).toBeTruthy();
  });

  // Both actions are the shared Button's markup, as on the error boundary's
  // screen for the same failure — not a hand-rolled class string.
  it("builds its two actions from the shared button styles", () => {
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    for (const action of [
      screen.getByRole("button", { name: "Reload Page" }),
      screen.getByRole("link", { name: "Go Home" }),
    ]) {
      expect(action).toHaveClass("focus-visible:ring-2", "font-medium");
      expect(action).not.toHaveClass("font-semibold");
    }
  });

  it("reloads the page when the reader presses Reload Page", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reload Page" }));

    expect(reload).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("offers the error in a form a bug report can carry", () => {
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText("Error details").textContent).toContain(
      "planted: the screen broke",
    );
    expect(screen.getByRole("button", { name: "Copy details" })).toBeTruthy();
  });

  it("says a new version is ready when a route's chunk could not be loaded", async () => {
    routeError.current = new TypeError(
      "Failed to fetch dynamically imported module: https://x/assets/Launcher-abc.js",
    );
    render(
      <MemoryRouter>
        <ErrorPage />
      </MemoryRouter>,
    );

    expect(screen.getByRole("heading").textContent).toBe(
      "A new version is ready",
    );
    expect(screen.getByRole("button", { name: "Reload Page" })).toBeTruthy();
    expect(screen.queryByText(/dynamically imported/)).toBeNull();
    await withLanguage("pl", () => {
      expect(screen.getByRole("heading").textContent).toBe(
        "Dostępna jest nowa wersja",
      );
    });
  });
});
