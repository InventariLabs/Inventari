/**
 * Which addresses are served without an account.
 *
 * `Root.tsx` reads this before importing either tree, so the answer has to be
 * a pure function of the path — no router, no store, no module registry. Keep
 * the pattern exact rather than a `/public/` prefix: a path that starts with
 * `/public/` but matches nothing here is a mistyped address, and it belongs to
 * the application's own 404 rather than to a tree with one route in it.
 */
const PUBLIC_PATHS: RegExp[] = [
  // The attestation link an employee receives by email: /public/attestation/<token>
  /^\/public\/attestation\/[^/]+\/?$/,
];

export function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((pattern) => pattern.test(pathname));
}
