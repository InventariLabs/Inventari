/**
 * Thin logging utility that wraps `console.*` calls.
 * In production builds (import.meta.env.PROD) debug/info/log messages are silenced.
 * Error and warn are always forwarded to keep observability for unexpected issues.
 */
/* eslint-disable no-console */

const isProd = import.meta.env.PROD;

export const logger = {
  debug: (...args: unknown[]) => {
    if (!isProd) console.debug(...args);
  },
  log: (...args: unknown[]) => {
    if (!isProd) console.log(...args);
  },
  info: (...args: unknown[]) => {
    if (!isProd) console.info(...args);
  },
  warn: (...args: unknown[]) => {
    console.warn(...args);
  },
  error: (...args: unknown[]) => {
    console.error(...args);
  },
};
