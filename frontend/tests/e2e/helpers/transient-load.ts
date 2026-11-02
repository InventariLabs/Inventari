/**
 * The message Chromium gives a failed `import()`, whatever the cause. Under
 * e2e the cause is the host network changing mid-load (see fixtures/auth.ts),
 * not the app.
 */
export const isTransientModuleLoadError = (message: string): boolean =>
  /Failed to fetch dynamically imported module/.test(message);
