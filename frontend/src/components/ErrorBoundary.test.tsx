import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { lazy, Suspense } from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import ErrorBoundary from "./ErrorBoundary";

function Broken(): React.ReactElement {
  throw new Error("planted: the screen broke");
}

describe("ErrorBoundary", () => {
  // The throw is planted on purpose; see App.routerError.test.tsx.
  beforeEach(() => {
    vi.spyOn(console, "error").mockImplementation(() => {});
  });
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the error with a copy button outside development builds too", () => {
    vi.stubEnv("DEV", false);
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    expect(screen.getByLabelText("Error details").textContent).toContain(
      "planted: the screen broke",
    );
    expect(screen.getByRole("button", { name: "Copy details" })).toBeTruthy();
    expect(screen.queryByText(/notified/i)).toBeNull();
    vi.unstubAllEnvs();
  });

  it("tells the reader a new version is ready when a lazy chunk has gone missing", async () => {
    // What a deploy does to a tab that still holds the old chunk names: the
    // import rejects the way the browser words it, with nothing to render.
    const Missing = lazy(() =>
      Promise.reject(
        new TypeError(
          "Failed to fetch dynamically imported module: https://x/assets/Launcher-abc.js",
        ),
      ),
    );
    render(
      <ErrorBoundary>
        <Suspense fallback={null}>
          <Missing />
        </Suspense>
      </ErrorBoundary>,
    );

    await waitFor(() =>
      expect(screen.getByRole("heading").textContent).toBe(
        "A new version is ready",
      ),
    );
    expect(screen.getByRole("button", { name: "Reload Page" })).toBeTruthy();
    expect(screen.queryByText(/dynamically imported/)).toBeNull();
    expect(screen.queryByLabelText("Error details")).toBeNull();
  });

  it("sends the reader to the start page from the full-screen fallback", () => {
    const location = { ...window.location, href: "/orders/42" };
    vi.stubGlobal("location", location);
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Go Home" }));

    expect(location.href).toBe("/");
    vi.unstubAllGlobals();
  });

  it("reloads the page from the full-screen fallback", () => {
    const reload = vi.fn();
    vi.stubGlobal("location", { ...window.location, reload });
    render(
      <ErrorBoundary>
        <Broken />
      </ErrorBoundary>,
    );

    fireEvent.click(screen.getByRole("button", { name: "Reload Page" }));

    expect(reload).toHaveBeenCalledTimes(1);
    vi.unstubAllGlobals();
  });

  it("lets the reader retry a failed module panel once the cause is gone", () => {
    let broken = true;
    function Flaky() {
      if (broken) throw new Error("planted: the panel broke");
      return <p>Panel is back</p>;
    }
    render(
      <ErrorBoundary variant="mini">
        <Flaky />
      </ErrorBoundary>,
    );
    expect(screen.queryByText("Panel is back")).toBeNull();

    broken = false;
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));

    expect(screen.getByText("Panel is back")).toBeInTheDocument();
  });
});
