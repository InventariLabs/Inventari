import { afterEach, describe, expect, it, vi } from "vitest";

async function loadLogger() {
  vi.resetModules();
  return (await import("./logger")).logger;
}

describe("logger", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.restoreAllMocks();
  });

  it("forwards debug, log and info to the console outside production", async () => {
    vi.stubEnv("PROD", false);
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const logger = await loadLogger();

    logger.debug("d", 1);
    logger.log("l", 2);
    logger.info("i", 3);

    expect(debug).toHaveBeenCalledExactlyOnceWith("d", 1);
    expect(log).toHaveBeenCalledExactlyOnceWith("l", 2);
    expect(info).toHaveBeenCalledExactlyOnceWith("i", 3);
  });

  it("silences debug, log and info in a production build so users' consoles stay quiet", async () => {
    vi.stubEnv("PROD", true);
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const logger = await loadLogger();

    logger.debug("d");
    logger.log("l");
    logger.info("i");

    expect(debug).not.toHaveBeenCalled();
    expect(log).not.toHaveBeenCalled();
    expect(info).not.toHaveBeenCalled();
  });

  it("always forwards warnings and errors, production or not", async () => {
    vi.stubEnv("PROD", true);
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const logger = await loadLogger();

    logger.warn("w");
    logger.error("e", new Error("boom"));

    expect(warn).toHaveBeenCalledExactlyOnceWith("w");
    expect(error).toHaveBeenCalledExactlyOnceWith("e", new Error("boom"));
  });
});
