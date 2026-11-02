/**
 * What the onboarding module publishes to the modules that depend on it.
 *
 * `check:boundaries` counts every import of a module's internals as an edge;
 * this file is the one it lets through. A name is added here when a second
 * module needs it, and removing or renaming one is a breaking change for
 * them.
 */
// The product profiles, and the preview and apply of a switch between them,
// which the launcher and the workspace settings offer outside onboarding.
export {
  useProfiles,
  useProfileSwitchApply,
  useProfileSwitchPreview,
} from "./hooks/useOnboarding";
