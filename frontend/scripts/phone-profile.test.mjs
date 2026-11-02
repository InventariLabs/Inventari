/**
 * The bytes the phone measurement reads off a page are information only, so a
 * size the browser can no longer give must not be what ends the measurement.
 */
import { EventEmitter } from "node:events";
import { afterEach, describe, expect, it } from "vitest";

import { hostLoad, scriptBytes } from "./phone-profile.mjs";

const script = (sizes) => ({ resourceType: () => "script", sizes });

describe("scriptBytes", () => {
  const unhandled = [];
  const record = (reason) => unhandled.push(reason);
  afterEach(() => {
    process.off("unhandledRejection", record);
    unhandled.length = 0;
  });

  it("sums the scripts that finished and ignores the rest", async () => {
    const page = new EventEmitter();
    const total = scriptBytes(page);
    page.emit("requestfinished", script(async () => ({ responseBodySize: 1000 })));
    page.emit("requestfinished", { resourceType: () => "image", sizes: async () => ({ responseBodySize: 5 }) });
    page.emit("requestfinished", script(async () => ({ responseBodySize: 24 })));

    expect(await total()).toBe(1024);
  });

  it("does not leave a size read the closing page refused unhandled", async () => {
    // Playwright refuses `request.sizes()` once the page is closed. The read
    // is asked for when the request finishes and summed only after the network
    // goes idle, so a refusal in between had no handler for that long, and
    // Node ended the run on it instead of reporting the screen.
    process.on("unhandledRejection", record);
    const page = new EventEmitter();
    const total = scriptBytes(page);
    page.emit(
      "requestfinished",
      script(() => Promise.reject(new Error("Target page, context or browser has been closed"))),
    );
    page.emit("requestfinished", script(async () => ({ responseBodySize: 24 })));
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(unhandled).toEqual([]);
    expect(await total()).toBe(24);
  });
});

describe("hostLoad", () => {
  // A timing read on a host with more runnable work than cores measures the
  // queue for the CPU as much as the screen, so the gate names that state.
  it("calls the host loaded once the one-minute load reaches its cores", () => {
    expect(hostLoad([44.2, 30, 20], 24)).toEqual({ load: 44.2, cores: 24, loaded: true });
    expect(hostLoad([24, 30, 20], 24).loaded).toBe(true);
  });

  it("calls a host with spare cores calm", () => {
    expect(hostLoad([3.5, 60, 60], 24)).toEqual({ load: 3.5, cores: 24, loaded: false });
  });
});
