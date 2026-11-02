import type { components } from "@/types/api-generated";
export type ApiKey = components["schemas"]["ApiKeyResponse"];

export type ApiKeyCreate = components["schemas"]["ApiKeyCreate"];

export type ApiKeyCreated = components["schemas"]["ApiKeyCreatedResponse"];

/**
 * What a key issued here may carry, and how it authenticates.
 *
 * Comes from the server rather than from a sentence written on the screen:
 * what the reader may grant depends on what they hold, and what no key may
 * hold is a constant in the authentication path — anything the screen states
 * about either has to be read from there or it will drift.
 */
export type ApiKeyCapabilities = components["schemas"]["ApiKeyCapabilities"];

/** One permission of the catalogue, with the labels the roles editor uses. */
export type ApiKeyPermissionOption =
  components["schemas"]["ApiKeyPermissionOption"];
