import "@testing-library/jest-dom/vitest";
import { afterAll, afterEach, beforeAll, beforeEach, expect } from "vitest";
import { cleanup, configure } from "@testing-library/react";
import { server } from "./mocks/server";

import "./mocks/i18n";
import "./mocks/reactQuery";
import "./mocks/lucide";
import "./mocks/browser";

import "../modules/shopping_lists/module";
import "../modules/stats/module";
import "../modules/stock_takes/module";
import "../modules/nutrition/module";
import "../modules/announcements/module";
import "../modules/equipment/module";

import baselineFile from "./console-baseline.json";
import {
  assertNoUnexpected,
  createConsoleGate,
  writeObservations,
  type ConsoleBaseline,
} from "./consoleGate";

// Enable React 18 act environment so async state updates from 3rd-party
// components (Radix, sonner Toaster in AllTheProviders) are treated as
// wrapped in act(...). Eliminates "not configured to support act(...)" warnings.
(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true;

// A green run that printed React warnings is not a green run — the gate
// (consoleGate.ts) takes over console.error and React's console.warn, absorbs
// what the baseline recorded, and fails the test on anything else. Messages
// outside the gate — another library's console.warn — pass through untouched.
const gate = createConsoleGate(
  (baselineFile as { entries: ConsoleBaseline }).entries,
);
const originalConsoleError = console.error.bind(console);
const originalConsoleWarn = console.warn.bind(console);

console.error = (...args: unknown[]) => {
  if (gate.record("error", args) !== "pass") return;
  originalConsoleError(...args);
};

console.warn = (...args: unknown[]) => {
  if (gate.record("warn", args) !== "pass") return;
  originalConsoleWarn(...args);
};

configure({ asyncUtilTimeout: 5000 });

beforeAll(() => server.listen({ onUnhandledRequest: "warn" }));

beforeEach(() => {
  gate.beginTest(expect.getState().testPath ?? "");
});

afterAll(() => {
  server.close();
  const beforeAnyTest = gate.endFile();
  if (process.env.CONSOLE_BASELINE_WRITE) {
    writeObservations(gate.observations());
  } else {
    assertNoUnexpected(beforeAnyTest);
  }
});

afterEach(() => {
  cleanup();
  // Per-tab memory must not carry a count from one test into the next.
  window.sessionStorage.clear();
  server.resetHandlers();
  vi.clearAllMocks();
  if (window.location && typeof window.location === "object") {
    (window.location as unknown as Record<string, unknown>).href =
      "http://localhost:3000/";
  }
  const unexpected = gate.endTest();
  if (!process.env.CONSOLE_BASELINE_WRITE) assertNoUnexpected(unexpected);
});
