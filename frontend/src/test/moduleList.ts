/**
 * Declare the organization's module list for one test.
 *
 * The module list is the authority on whether a module's queries may run: a
 * spec that mounts a module's screen has to say the organization has that
 * module, rather than lean on the fallback list the shell shows while the
 * real one is still loading.
 */
import { http, HttpResponse } from "msw";

import { server } from "./mocks/server";

const ALWAYS_ON = ["core", "items", "locations", "categories"];

export function withModules(...names: string[]): void {
  server.use(
    http.get("/api/v1/modules/my", () =>
      HttpResponse.json([...ALWAYS_ON, ...names]),
    ),
  );
}
