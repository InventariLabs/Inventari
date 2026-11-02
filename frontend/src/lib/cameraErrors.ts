/**
 * Which sentence a camera refusal deserves.
 *
 * The scanner used to print the browser's own words under a translated
 * heading: "Błąd kamery" over "Error getting userMedia, error =
 * NotSupportedError: Not supported". English in a Polish interface, and no
 * answer to the only question the reader has — what do I do now. The causes
 * are different actions, not one: a permission to grant, an address to open
 * over HTTPS, a device that has no camera, a camera that is there but cannot
 * meet the constraints asked of it, an application holding it.
 *
 * A pure function, because the branch it picks is the whole behaviour and a
 * hook that starts a camera is not a thing a test can hold still.
 */
export type CameraErrorKey =
  | "errorInsecureContext"
  | "errorCameraPermission"
  | "errorCameraNotFound"
  | "errorCameraOverconstrained"
  | "errorCameraBusy"
  | "errorCameraUnavailable";

interface CameraErrorContext {
  /** `window.isSecureContext` — false on plain http, which forbids the camera. */
  isSecureContext: boolean;
}

/**
 * html5-qrcode rejects with a plain string as often as with an Error
 * ("NotAllowedError: Permission denied"), so the name has to be read off both.
 */
function names(error: unknown): string {
  const named = (error as { name?: string } | null)?.name;
  return `${named ?? ""} ${String(error)}`;
}

export function cameraErrorKey(
  error: unknown,
  { isSecureContext }: CameraErrorContext,
): CameraErrorKey {
  // First, because an insecure page fails before any permission is asked for,
  // and the browser's name for that failure varies by vendor.
  if (!isSecureContext) return "errorInsecureContext";

  const said = names(error);
  const saidAny = (...candidates: string[]) =>
    candidates.some((candidate) => said.includes(candidate));

  if (saidAny("NotAllowedError", "SecurityError", "PermissionDeniedError")) {
    return "errorCameraPermission";
  }
  if (saidAny("NotFoundError", "DevicesNotFoundError")) {
    return "errorCameraNotFound";
  }
  // Not a missing camera: the device answered and refused the ask. A laptop
  // whose only camera faces the user, scanned at with `facingMode:
  // "environment"`, used to be told there was no camera on it — while the
  // reader was looking into the one there was.
  if (saidAny("OverconstrainedError")) {
    return "errorCameraOverconstrained";
  }
  if (saidAny("NotReadableError", "TrackStartError", "AbortError")) {
    return "errorCameraBusy";
  }
  // Everything else, including the NotSupportedError this was found on. The
  // reader gets a sentence they can act on rather than the exception text:
  // whatever the cause, the way through the screen is the same.
  return "errorCameraUnavailable";
}

/**
 * The sentence itself.
 *
 * A `switch` with six literal keys rather than `t(key)`, so the catalogue
 * gate can still see that these six are used. A key consumed through a
 * variable reads as an orphan to a static scan, and the fix for that is an
 * allowlist entry — which is a promise, where this is a fact.
 */
export function cameraErrorMessage(
  error: unknown,
  context: CameraErrorContext,
  t: (key: string) => string,
): string {
  switch (cameraErrorKey(error, context)) {
    case "errorInsecureContext":
      return t("scan:errorInsecureContext");
    case "errorCameraPermission":
      return t("scan:errorCameraPermission");
    case "errorCameraNotFound":
      return t("scan:errorCameraNotFound");
    case "errorCameraOverconstrained":
      return t("scan:errorCameraOverconstrained");
    case "errorCameraBusy":
      return t("scan:errorCameraBusy");
    case "errorCameraUnavailable":
      return t("scan:errorCameraUnavailable");
  }
}
