import { afterEach, describe, expect, it, vi } from "vitest";
import type { Metric } from "web-vitals";

const { onCLS, onINP, onLCP } = vi.hoisted(() => ({
  onCLS: vi.fn(),
  onINP: vi.fn(),
  onLCP: vi.fn(),
}));
vi.mock("web-vitals", () => ({ onCLS, onINP, onLCP }));

import { initWebVitals } from "./webVitals";

const lcp = { name: "LCP", value: 2512.349, id: "v5-1" } as Metric;

describe("initWebVitals", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("subscribes to the three metrics the app tracks, each with the same reporter", () => {
    initWebVitals();

    expect(onCLS).toHaveBeenCalledTimes(1);
    expect(onINP).toHaveBeenCalledTimes(1);
    expect(onLCP).toHaveBeenCalledTimes(1);
    expect(onCLS.mock.calls[0][0]).toBe(onLCP.mock.calls[0][0]);
  });

  it("prints a metric line in a production build", () => {
    vi.stubEnv("PROD", true);
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    initWebVitals();

    onLCP.mock.calls[0][0](lcp);

    expect(info).toHaveBeenCalledExactlyOnceWith(
      "[Web Vitals] LCP: 2512.3 (id: v5-1)",
    );
  });

  it("stays silent outside production", () => {
    vi.stubEnv("PROD", false);
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    initWebVitals();

    onLCP.mock.calls[0][0](lcp);

    expect(info).not.toHaveBeenCalled();
  });
});
