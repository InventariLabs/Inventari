import { describe, it, expect } from "vitest";
import { cameraErrorKey } from "./cameraErrors";

const secure = { isSecureContext: true };

describe("cameraErrorKey", () => {
  it("sends a page served over plain http to the HTTPS sentence", () => {
    expect(
      cameraErrorKey(new Error("whatever"), { isSecureContext: false }),
    ).toBe("errorInsecureContext");
  });

  it("tells a blocked permission from a missing camera", () => {
    expect(cameraErrorKey({ name: "NotAllowedError" }, secure)).toBe(
      "errorCameraPermission",
    );
    expect(cameraErrorKey({ name: "NotFoundError" }, secure)).toBe(
      "errorCameraNotFound",
    );
  });

  it("names a camera another application is holding", () => {
    expect(cameraErrorKey({ name: "NotReadableError" }, secure)).toBe(
      "errorCameraBusy",
    );
  });

  // A camera refusing the constraints is not a missing camera: the device is
  // right there — it is the ask it cannot satisfy (a laptop with only a
  // front camera asked for `facingMode: "environment"`). It used to be folded
  // into "no camera was found", which sent the reader looking for hardware
  // standing in front of them.
  it("tells a camera that cannot meet the constraints from a missing one", () => {
    expect(
      cameraErrorKey(
        new DOMException("Constraints not satisfied", "OverconstrainedError"),
        secure,
      ),
    ).toBe("errorCameraOverconstrained");
    expect(
      cameraErrorKey(
        "Error getting userMedia, error = OverconstrainedError: Constraints not satisfied",
        secure,
      ),
    ).toBe("errorCameraOverconstrained");
  });

  // html5-qrcode rejects with a string as often as with an Error, so the name
  // is not always on `.name`.
  it("reads the cause out of a plain string rejection", () => {
    expect(
      cameraErrorKey(
        "Error getting userMedia, error = NotAllowedError",
        secure,
      ),
    ).toBe("errorCameraPermission");
  });

  // The one this was found on: "Error getting userMedia, error =
  // NotSupportedError: Not supported", printed verbatim in a Polish interface.
  it("gives an unrecognised refusal a sentence instead of the exception", () => {
    expect(
      cameraErrorKey(
        "Error getting userMedia, error = NotSupportedError: Not supported",
        secure,
      ),
    ).toBe("errorCameraUnavailable");
    expect(cameraErrorKey(undefined, secure)).toBe("errorCameraUnavailable");
  });
});
