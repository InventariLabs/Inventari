/**
 * A request body as a caller writes it, with the named keys optional.
 *
 * The generated request types already leave a field with a server default
 * optional (scripts/openapi-request-defaults.mjs drops the default from
 * request-only schemas), so a type built from the contract needs no help. This
 * stays for a body type that is also a response, where the contract keeps the
 * default and so the field required: leaving it out is how a caller says "the
 * default" (or, on a PATCH, "unchanged").
 */
export type WithServerDefaults<T, K extends keyof T> = Omit<T, K> &
  Partial<Pick<T, K>>;
