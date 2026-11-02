/**
 * The development admin account, in one place.
 *
 * The Makefile owns the value (`DEV_ADMIN_PASSWORD`) and `make dev-up` prints
 * it; the suite reads the same value from the environment, so a stack started
 * with another password needs no spec edited. Every spec signs in through
 * these two constants rather than a literal of its own.
 */
export const ADMIN_EMAIL = process.env.DEV_ADMIN_EMAIL ?? "admin@example.com";
export const ADMIN_PASSWORD = process.env.DEV_ADMIN_PASSWORD ?? "Admin123";
