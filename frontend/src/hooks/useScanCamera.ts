import { useState, useRef, useEffect, useSyncExternalStore } from "react";
import { setTorchAvailable } from "@/hooks/useTorchAvailable";

// Views that draw their own torch button ask the camera hook's module.
export { useTorchAvailable } from "@/hooks/useTorchAvailable";
import { logger } from "@/utils/logger";
import { cameraErrorMessage } from "@/lib/cameraErrors";
import { Html5Qrcode, Html5QrcodeSupportedFormats } from "html5-qrcode";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";

interface UseScanCameraOptions {
  onCodeScanned: (code: string) => void;
}

/**
 * The one box that is both drawn (html5-qrcode shades everything outside it)
 * and decoded, sized from the picture as it is shown. It is a wide rectangle
 * so a 1-D code keeps its modules, and never taller than the part of the
 * picture the screen leaves visible, so the frame is never clipped.
 */
export function decodeRegion(
  videoWidth: number,
  videoHeight: number,
  visibleHeight: number = videoHeight,
) {
  const width = Math.floor(videoWidth * 0.9);
  const maxHeight = Math.min(videoHeight, visibleHeight) * 0.9;
  return { width, height: Math.floor(Math.min(width * 0.6, maxHeight)) };
}

// html5-qrcode sizes the canvas it decodes from to the box in CSS pixels, so a
// 288 px box holds a 95-module EAN at under 2 px per module however sharp the
// camera is. The canvas is sized to the camera pixels the box covers instead
// (longest edge capped, to keep the decode time in check).
const MAX_DECODE_EDGE = 1280;

// The 1-D reader picks one black point per row from a histogram, and a label
// printed on a mid-tone surround gives that histogram three humps, so the
// quiet zone reads as bars. Each pixel is judged against its own
// neighbourhood instead: clearly darker than the local mean is ink, anything
// else is paper, so a flat surround of any tone is paper while grey ink on
// white paper (well above half the mean) still counts as ink.
export function binarizeLocally(image: ImageData, dropWide = false) {
  const { width, height, data } = image;
  const half = Math.max(4, width >> 4);
  const stride = width + 1;
  const sum = new Uint32Array(stride * (height + 1));
  const luma = new Uint8Array(width * height);
  for (let y = 0; y < height; y++) {
    let row = 0;
    for (let x = 0; x < width; x++) {
      const i = y * width + x;
      row += luma[i] =
        (data[i * 4] * 77 + data[i * 4 + 1] * 150 + data[i * 4 + 2] * 29) >> 8;
      sum[(y + 1) * stride + x + 1] = sum[y * stride + x + 1] + row;
    }
  }
  for (let y = 0; y < height; y++) {
    const y0 = Math.max(0, y - half);
    const y1 = Math.min(height, y + half + 1);
    for (let x = 0; x < width; x++) {
      const x0 = Math.max(0, x - half);
      const x1 = Math.min(width, x + half + 1);
      const total =
        sum[y1 * stride + x1] -
        sum[y0 * stride + x1] -
        sum[y1 * stride + x0] +
        sum[y0 * stride + x0];
      const i = y * width + x;
      const ink = luma[i] * (x1 - x0) * (y1 - y0) < total * 0.85;
      data[i * 4] = data[i * 4 + 1] = data[i * 4 + 2] = ink ? 0 : 255;
    }
    // The edge of a dark package beside the label is ink to the threshold
    // above and sits where the quiet zone must be white. A bar is a few
    // modules wide; a run across a fortieth of the picture is not one. (A
    // QR finder pattern is wider than a bar, so this is a separate pass.)
    if (!dropWide) continue;
    const widest = Math.max(4, width / 40);
    let start = 0;
    for (let x = 0; x <= width; x++) {
      const dark = x < width && data[(y * width + x) * 4] === 0;
      if (dark) continue;
      if (x - start > widest) {
        for (let k = start; k < x; k++) {
          const j = (y * width + k) * 4;
          data[j] = data[j + 1] = data[j + 2] = 255;
        }
      }
      start = x + 1;
    }
  }
}

export function decodeAtCameraResolution(canvas: HTMLCanvasElement) {
  const context = canvas.getContext("2d");
  if (!context) return;
  let frame = 0;
  const draw = context.drawImage.bind(context) as (...a: unknown[]) => void;
  (context as { drawImage: unknown }).drawImage = (...args: unknown[]) => {
    const [source, , , sw, sh] = args as [
      unknown,
      number,
      number,
      number,
      number,
    ];
    if (args.length !== 9 || !(source instanceof HTMLVideoElement)) {
      return draw(...args);
    }
    const fit = Math.min(1, MAX_DECODE_EDGE / Math.max(sw, sh));
    // Assigning a size clears the bitmap, so only when it changes.
    const width = Math.max(1, Math.round(sw * fit));
    const height = Math.max(1, Math.round(sh * fit));
    if (canvas.width !== width) canvas.width = width;
    if (canvas.height !== height) canvas.height = height;
    draw(source, args[1], args[2], sw, sh, 0, 0, width, height);
    // One frame in three stays as the camera saw it, so a code the local
    // threshold would not survive (faint print) still gets its plain read;
    // the other two are thresholded, one of them also dropping the wide
    // ink of a dark package edge, which a QR code cannot survive.
    const pass = frame++ % 3;
    if (pass === 0) return;
    const picture = context.getImageData(0, 0, width, height);
    binarizeLocally(picture, pass === 2);
    context.putImageData(picture, 0, 0);
  };
}

export function whenDecodeCanvas(
  onCanvas: (canvas: HTMLCanvasElement) => void,
) {
  const find = () =>
    document.querySelector<HTMLCanvasElement>("#qr-reader #qr-canvas");
  const observer = new MutationObserver(() => {
    const canvas = find();
    if (!canvas) return;
    observer.disconnect();
    onCanvas(canvas);
  });
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}

// html5-qrcode calls play() on the video it puts in #qr-reader and drops the
// promise. A reader closed before playback begins takes the video out of the
// page, the browser rejects that promise with an AbortError, and nothing is
// listening: an unhandled rejection in the console for a scan that was simply
// cancelled. The interruption is the expected end of a cancelled start, so it
// is absorbed for the reader's video only; any other play() failure, and any
// other video, still surfaces.
const ABSORBED_PLAY = Symbol.for("inventari.readerPlayAbortAbsorbed");

export function absorbReaderPlayAbort() {
  const proto = HTMLVideoElement.prototype as {
    play: ((this: HTMLVideoElement) => Promise<void>) & {
      [ABSORBED_PLAY]?: boolean;
    };
  };
  const play = proto.play;
  if (play[ABSORBED_PLAY]) return;
  const absorbing = function (this: HTMLVideoElement) {
    const started = play.call(this);
    if (this.closest?.("#qr-reader")) {
      started?.catch?.((err: unknown) => {
        if ((err as { name?: string } | null)?.name === "AbortError") return;
        return Promise.reject(err);
      });
    }
    return started;
  };
  absorbing[ABSORBED_PLAY] = true;
  proto.play = absorbing;
}

/** Whether a camera track can switch a torch on, by what the track reports. */
function hasTorch(track: MediaStreamTrack | null | undefined): boolean {
  const capabilities = track?.getCapabilities?.() as
    (MediaTrackCapabilities & { torch?: boolean }) | undefined;
  return Boolean(capabilities?.torch);
}

const readerIsMounted = () => !!document.getElementById("qr-reader");

function subscribeToReader(notify: () => void) {
  const observer = new MutationObserver(notify);
  observer.observe(document.body, { childList: true, subtree: true });
  return () => observer.disconnect();
}

/**
 * The decoder's region, and the frame drawn from it, are sized once, when the
 * camera starts. A phone turned on its side kept the old ones: the landscape
 * frame, wider than the upright screen, hung off both edges and no longer
 * matched what the decoder read. So a turn restarts the camera; so does any
 * other change of the reader's box (a window dragged narrower, a split
 * screen) — a turn is only the commonest of them, and one that leaves the
 * screen landscape raises no orientation event at all.
 */
function useRestartWhenReaderBoxChanges(
  isCameraRunning: boolean,
  aimedFor: { current: { width: number; height: number } | null },
  restart: () => void,
) {
  const restartRef = useRef(restart);
  restartRef.current = restart;
  useEffect(() => {
    if (!isCameraRunning) return;
    const restartForNewSize = () => {
      aimedFor.current = null;
      restartRef.current();
    };
    const orientation = window.matchMedia?.("(orientation: portrait)");
    orientation?.addEventListener("change", restartForNewSize);

    let settle: ReturnType<typeof setTimeout> | undefined;
    const onResize = () => {
      clearTimeout(settle);
      // A drag fires a resize per frame; the box is read once it stops.
      settle = setTimeout(() => {
        const aimed = aimedFor.current;
        const reader = document.getElementById("qr-reader");
        if (!aimed || !reader) return;
        if (
          reader.clientWidth !== aimed.width ||
          reader.clientHeight !== aimed.height
        ) {
          restartForNewSize();
        }
      }, 250);
    };
    window.addEventListener("resize", onResize);
    return () => {
      orientation?.removeEventListener("change", restartForNewSize);
      window.removeEventListener("resize", onResize);
      clearTimeout(settle);
    };
  }, [isCameraRunning, aimedFor]);
}

export function useScanCamera({ onCodeScanned }: UseScanCameraOptions) {
  const { t: tScan } = useTranslation("scan");

  const scannerRef = useRef<Html5Qrcode | null>(null);
  const lastReadCode = useRef<string | null>(null);
  const readCount = useRef<number>(0);
  // One presence is one read. A code held in front of the camera decodes on
  // every frame, and the consensus counter alone cannot tell "still being
  // shown" from "shown again": it reset the moment a read was reported, so
  // two frames later the same code was read again, and a product held up for
  // five seconds was added ten times. So a code once reported stays reported
  // until the decoder stops seeing it — `missedAttempts` counts the frames
  // the library tried and failed (it tries each frame twice, mirrored) with
  // that code out of view. A different code arriving also clears it: the
  // first one has left the frame.
  const reportedCode = useRef<string | null>(null);
  const missedAttempts = useRef<number>(0);
  // A turn of the phone restarts the camera only to size its frame for the
  // new screen; the code in front of it never left. The run before the turn
  // hands the code it reported to the run after it, which keeps it reported
  // until the decoder stops seeing it — a held code was counted once more on
  // every turn.
  const reportedBeforeTurn = useRef<string | null>(null);
  // The size of the reader's box the running camera's frame was computed for.
  const aimedFor = useRef<{ width: number; height: number } | null>(null);
  // About a second of frames with nothing to read (the reader runs at 20 fps
  // and tries twice per frame). Long enough that a code merely hard to read
  // — a frame or three of blur — is still the same reading, short enough that
  // taking the code away and bringing it back reads as the second piece it is.
  const MISSES_TO_LEAVE_VIEW = 40;
  // Read through a ref: at every call site this is an inline arrow, so as an
  // effect dependency it tore the running camera down and started it again on
  // each render — and publishing the device state below is itself a render.
  const onCodeScannedRef = useRef(onCodeScanned);
  onCodeScannedRef.current = onCodeScanned;
  const CONSENSUS_REQUIRED = 2;

  const [scannerError, setScannerError] = useState<string | null>(null);
  const [isCameraActive, setIsCameraActive] = useState(() => {
    return (
      window.matchMedia("(pointer: coarse)").matches || window.innerWidth < 1024
    );
  });
  // What the device is doing, not what the user asked for. `isCameraActive`
  // is the wish to scan — it stays true while the camera is being started and
  // while it is refusing — so a screen that drew "Scanning…" from it kept the
  // label glowing over the sentence saying the camera had refused.
  const [isCameraRunning, setIsCameraRunning] = useState(false);
  const [isTorchOn, setIsTorchOn] = useState(false);

  // The camera belongs to the reader element: a caller that closes its
  // scanner panel removes #qr-reader but cannot be relied on to switch the
  // wish off too, and html5-qrcode keeps decoding a detached video. So the
  // camera runs only while the element is on the page, and starts again by
  // itself when the panel reopens.
  const isReaderMounted = useSyncExternalStore(
    subscribeToReader,
    readerIsMounted,
  );
  // A hidden page (screen lock, another app in front) must not hold the
  // camera: the phone's light stays on and, on return, the stream is often
  // dead. Going hidden tears the camera down through the effect below, and
  // coming back starts it again.
  const [isPageHidden, setIsPageHidden] = useState(
    () => document.visibilityState === "hidden",
  );
  useEffect(() => {
    const onVisibility = () =>
      setIsPageHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("pagehide", onVisibility);
    return () => {
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener("pagehide", onVisibility);
    };
  }, []);
  const shouldRun = isCameraActive && isReaderMounted && !isPageHidden;

  // The restart cooldown is delayed work on the global timer queue, and a
  // component (or a test environment) that goes away inside the window used
  // to take the callback with it — state set on a dead world, reported by
  // vitest as an unhandled error: green tests, exit 1. The id is kept so
  // unmount can take the timer back.
  const restartTimerRef = useRef<number | null>(null);

  const restartCamera = () => {
    if (restartTimerRef.current !== null) {
      clearTimeout(restartTimerRef.current);
    }
    setScannerError(null);
    setIsTorchOn(false);
    setTorchAvailable(false);
    setIsCameraRunning(false);
    setIsCameraActive(false);
    restartTimerRef.current = window.setTimeout(() => {
      restartTimerRef.current = null;
      setIsCameraActive(true);
    }, 120);
  };

  const restartCameraRef = useRef(restartCamera);
  restartCameraRef.current = restartCamera;

  // Runs whether or not the camera ever started: the cooldown may be
  // pending while the camera effect below never mounted its cleanup.
  useEffect(() => {
    return () => {
      if (restartTimerRef.current !== null) {
        clearTimeout(restartTimerRef.current);
        restartTimerRef.current = null;
      }
    };
  }, []);

  const startCamera = () => {
    restartCamera();
  };

  const resumeCamera = () => {
    if (scannerRef.current) {
      try {
        scannerRef.current.resume();
      } catch {
        startCamera();
      }
    } else if (isCameraActive) {
      startCamera();
    }
    // Otherwise the reader never asked for the camera (a wide screen waits
    // for "Start Camera"): a refused typed code used to start it here and
    // swap the notice for a camera error nobody had asked about.
  };

  const pauseCamera = async () => {
    if (scannerRef.current?.isScanning) {
      try {
        await scannerRef.current.pause();
      } catch {
        // ignore if not scanning
      }
    }
  };

  const toggleTorch = async () => {
    if (scannerRef.current) {
      try {
        const state = !isTorchOn;
        const video = document.querySelector(
          "#qr-reader video",
        ) as HTMLVideoElement | null;
        const stream = video?.srcObject;
        const track =
          stream instanceof MediaStream ? stream.getVideoTracks()[0] : null;

        if (!hasTorch(track)) {
          toast.error(tScan("flashlightNotSupported"));
          return;
        }

        await scannerRef.current.applyVideoConstraints({
          advanced: [{ torch: state } as MediaTrackConstraintSet],
        } as MediaTrackConstraints);
        setIsTorchOn(state);
      } catch {
        toast.error(tScan("flashlightNotSupported"));
      }
    }
  };

  // The decoder's region, and the frame drawn from it, are sized once, when
  // the camera starts. A change of the reader's box leaves them stale, so the
  // camera starts again and the new start sizes both for the box as it stands.
  useRestartWhenReaderBoxChanges(isCameraRunning, aimedFor, () => {
    reportedBeforeTurn.current = reportedCode.current;
    restartCameraRef.current();
  });

  // Camera lifecycle
  useEffect(() => {
    if (!shouldRun) return;
    reportedCode.current = reportedBeforeTurn.current;
    reportedBeforeTurn.current = null;

    // A reader torn down and started again — the panel closed and reopened,
    // the page hidden and shown — knows nothing about the code in front of
    // it: what it established belongs to the run that established it, so a
    // code still in view is read once more by the new one. A turn is the one
    // restart that carries its reported code over (above).
    const forgetReadState = () => {
      lastReadCode.current = null;
      readCount.current = 0;
      reportedCode.current = null;
      missedAttempts.current = 0;
    };

    let isMounted = true;
    let timer: ReturnType<typeof setTimeout>;
    let isStarting = false;
    let stopWatchingCanvas = () => {};

    const initCamera = async () => {
      timer = setTimeout(async () => {
        if (!isMounted) return;
        if (isStarting) return;
        isStarting = true;

        try {
          if (scannerRef.current) {
            try {
              if (scannerRef.current.isScanning) {
                await scannerRef.current.stop();
              }
              scannerRef.current.clear();
            } catch {
              // ignore cleanup errors
            }
          }

          if (!document.getElementById("qr-reader")) {
            isStarting = false;
            return;
          }

          const html5QrCode = new Html5Qrcode("qr-reader");
          scannerRef.current = html5QrCode;

          const config = {
            fps: 20,
            qrbox: (viewfinderWidth: number, viewfinderHeight: number) => {
              const reader = document.getElementById("qr-reader");
              const region = decodeRegion(
                viewfinderWidth,
                viewfinderHeight,
                reader?.clientHeight,
              );
              if (reader) {
                aimedFor.current = {
                  width: reader.clientWidth,
                  height: reader.clientHeight,
                };
              }
              // The scan screen draws its frame from these two numbers, so
              // the frame is the region the decoder reads, not a look-alike.
              reader?.parentElement?.style.setProperty(
                "--aim-w",
                `${region.width}px`,
              );
              reader?.parentElement?.style.setProperty(
                "--aim-h",
                `${region.height}px`,
              );
              return region;
            },
            aspectRatio: 1.0,
            // Without a size the browser picks 640x480, which leaves a
            // barcode too few pixels per module however the canvas is sized.
            videoConstraints: {
              facingMode: "environment",
              width: { ideal: MAX_DECODE_EDGE },
              height: { ideal: 720 },
            },
            formatsToSupport: [
              Html5QrcodeSupportedFormats.QR_CODE,
              Html5QrcodeSupportedFormats.EAN_13,
              Html5QrcodeSupportedFormats.EAN_8,
              Html5QrcodeSupportedFormats.UPC_A,
              Html5QrcodeSupportedFormats.CODE_128,
              Html5QrcodeSupportedFormats.CODE_39,
            ],
          };

          // The library creates #qr-canvas in its "playing" handler, after
          // start() has resolved, so the canvas is waited for, not looked up.
          stopWatchingCanvas = whenDecodeCanvas(decodeAtCameraResolution);
          absorbReaderPlayAbort();
          await html5QrCode.start(
            { facingMode: "environment" },
            config,
            (decodedText) => {
              if (!isMounted) return;

              if (decodedText === reportedCode.current) {
                // The reading already happened; the code is simply still
                // there. Nothing to count and nothing to report.
                missedAttempts.current = 0;
                return;
              }
              // Some other code is in the frame, so the reported one has
              // left it and may be read as a new piece whenever it returns.
              reportedCode.current = null;
              missedAttempts.current = 0;

              if (decodedText === lastReadCode.current) {
                readCount.current++;
              } else {
                lastReadCode.current = decodedText;
                readCount.current = 1;
                return;
              }

              if (readCount.current >= CONSENSUS_REQUIRED) {
                lastReadCode.current = null;
                readCount.current = 0;
                reportedCode.current = decodedText;
                onCodeScannedRef.current(decodedText);
              }
            },
            () => {
              // A frame the decoder could not read. The only one it matters
              // for is a code already reported: once it has gone unread for
              // long enough it counts as out of view, and showing it again
              // is a second reading. Counted in frames rather than clock
              // time, so a page the browser throttles cannot decide it.
              if (reportedCode.current === null) return;
              if (++missedAttempts.current < MISSES_TO_LEAVE_VIEW) return;
              reportedCode.current = null;
              missedAttempts.current = 0;
            },
          );

          if (!isMounted) {
            try {
              await html5QrCode.stop();
            } catch {
              // ignore
            }
          } else {
            setIsCameraRunning(true);
            // The system can end the track under a visible page too (another
            // app takes the camera); nothing else would notice, and the label
            // would go on saying "Scanning…".
            const video =
              document.querySelector<HTMLVideoElement>("#qr-reader video");
            const stream = video?.srcObject as MediaStream | null | undefined;

            stream?.getVideoTracks?.().forEach((track) =>
              track.addEventListener("ended", () => {
                if (isMounted) restartCameraRef.current();
              }),
            );
            setTorchAvailable(hasTorch(stream?.getVideoTracks?.()[0]));
          }
        } catch (err) {
          logger.error("Camera start error:", err);
          if (!isMounted) return;
          setIsCameraRunning(false);

          // The exception text stays in the log, where it belongs. What
          // reaches the screen is a sentence in the reader's language naming
          // the next step — the browser's own words used to be printed under
          // a translated heading and answered nothing.
          setScannerError(
            cameraErrorMessage(
              err,
              { isSecureContext: window.isSecureContext !== false },
              tScan,
            ),
          );
        } finally {
          isStarting = false;
        }
      }, 500);
    };

    initCamera();

    return () => {
      isMounted = false;
      clearTimeout(timer);
      stopWatchingCanvas();
      // Whatever the reader had established about the code in front of it
      // belongs to the run that established it: the next start is a fresh
      // reading, and a code still in view is read again.
      forgetReadState();
      // The effect tears down whenever the camera is switched off, restarted
      // or the component goes away, and in every one of those cases nothing is
      // delivering frames any more.
      setIsCameraRunning(false);
      setTorchAvailable(false);

      if (!isStarting && scannerRef.current) {
        const stopScanner = async () => {
          try {
            await scannerRef.current?.stop();
          } catch {
            // ignore
          }
        };
        stopScanner();
      }
    };
  }, [shouldRun, tScan]);

  return {
    scannerError,
    isCameraActive,
    isCameraRunning,
    setIsCameraActive,
    isTorchOn,
    restartCamera,
    startCamera,
    resumeCamera,
    pauseCamera,
    toggleTorch,
  };
}
