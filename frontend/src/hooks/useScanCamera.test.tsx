import { renderHook, act } from "@testing-library/react";
import { describe, it, expect, vi, afterEach } from "vitest";
import { toast } from "sonner";
import { Html5Qrcode } from "html5-qrcode";
import { withLanguage } from "@/test/mocks/i18n";
import {
  useScanCamera,
  decodeRegion,
  decodeAtCameraResolution,
  binarizeLocally,
  whenDecodeCanvas,
  absorbReaderPlayAbort,
} from "./useScanCamera";
import { useTorchAvailable } from "./useTorchAvailable";
import { logger } from "@/utils/logger";

vi.mock("html5-qrcode", () => {
  class MockHtml5Qrcode {
    static rejectError: unknown = null;
    isScanning = false;
    async start() {
      if (MockHtml5Qrcode.rejectError !== null) {
        throw MockHtml5Qrcode.rejectError;
      }
    }
    async stop() {}
    clear() {}
    static constraints: unknown[] = [];
    async applyVideoConstraints(constraints: unknown) {
      MockHtml5Qrcode.constraints.push(constraints);
    }
  }
  return {
    Html5Qrcode: MockHtml5Qrcode,
    Html5QrcodeSupportedFormats: {
      QR_CODE: 0,
      EAN_13: 1,
      EAN_8: 2,
      UPC_A: 3,
      CODE_128: 4,
      CODE_39: 5,
    },
  };
});

describe("useScanCamera", () => {
  it("initializes with no camera error", () => {
    const mockOnCodeScanned = vi.fn();

    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: mockOnCodeScanned }),
    );

    expect(result.current).toHaveProperty("scannerError");
    expect(result.current).toHaveProperty("isCameraActive");
    expect(result.current).toHaveProperty("setIsCameraActive");
  });

  it("exposes camera control methods", () => {
    const mockOnCodeScanned = vi.fn();

    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: mockOnCodeScanned }),
    );

    expect(typeof result.current.startCamera).toBe("function");
    expect(typeof result.current.resumeCamera).toBe("function");
    expect(typeof result.current.pauseCamera).toBe("function");
    expect(typeof result.current.toggleTorch).toBe("function");
    expect(typeof result.current.restartCamera).toBe("function");
  });

  it("does not start a camera nobody asked for when told to resume", () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() =>
        useScanCamera({ onCodeScanned: vi.fn() }),
      );
      act(() => result.current.setIsCameraActive(false));

      act(() => {
        result.current.resumeCamera();
        vi.advanceTimersByTime(500);
      });

      expect(result.current.isCameraActive).toBe(false);
    } finally {
      vi.useRealTimers();
    }
  });

  it("starts the camera again on resume when it was the wish", () => {
    vi.useFakeTimers();
    try {
      const { result } = renderHook(() =>
        useScanCamera({ onCodeScanned: vi.fn() }),
      );
      act(() => result.current.setIsCameraActive(true));

      act(() => {
        result.current.resumeCamera();
      });
      // The restart switches it off for a beat, then back on.
      expect(result.current.isCameraActive).toBe(false);
      act(() => {
        vi.advanceTimersByTime(500);
      });
      expect(result.current.isCameraActive).toBe(true);
    } finally {
      vi.useRealTimers();
    }
  });

  it("exposes torch state", () => {
    const mockOnCodeScanned = vi.fn();

    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: mockOnCodeScanned }),
    );

    expect(typeof result.current.isTorchOn).toBe("boolean");
  });

  it("can toggle camera active state", () => {
    const mockOnCodeScanned = vi.fn();

    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: mockOnCodeScanned }),
    );

    const initialState = result.current.isCameraActive;

    act(() => {
      result.current.setIsCameraActive(!initialState);
    });

    expect(result.current.isCameraActive).toBe(!initialState);
  });

  it("maps html5-qrcode string rejections to translated errors", async () => {
    // html5-qrcode rejects with a plain string, not an Error — the
    // err.name mapping used to miss and leak the raw English message.
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = "NotAllowedError: Permission denied";

    document.body.innerHTML = '<div id="qr-reader"></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );

    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    expect(result.current.scannerError).toBe(
      "Camera access was blocked. Allow camera permission in your browser settings to scan codes.",
    );
    expect(result.current.scannerError).not.toContain("NotAllowedError");

    MockQr.rejectError = null;
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  // `cameraErrors` was tested as a pure function and nothing held the hook to
  // it: reverting the hook left all four files green. This walks the whole
  // path — the hook's own catch, the catalogue, the reader's language — and
  // checks the state the screen draws its indicator from.
  it("reaches the reader with the constraint refusal, and reports the device as not running", async () => {
    await withLanguage("pl", async () => {
      const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
      MockQr.rejectError = new DOMException(
        "Constraints not satisfied",
        "OverconstrainedError",
      );

      document.body.innerHTML = '<div id="qr-reader"></div>';
      const { result } = renderHook(() =>
        useScanCamera({ onCodeScanned: vi.fn() }),
      );

      act(() => {
        result.current.setIsCameraActive(true);
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 600));
      });

      expect(result.current.scannerError).toBe(
        "Ta kamera nie spełnia wymagań skanera. Wybierz inną kamerę albo wpisz kod ręcznie poniżej.",
      );
      expect(result.current.scannerError).not.toContain("Nie znaleziono");
      expect(result.current.isCameraRunning).toBe(false);

      MockQr.rejectError = null;
      await act(async () => {
        document.body.innerHTML = "";
      });
    });
  });

  it("calls the camera running only while it is actually delivering", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;

    document.body.innerHTML = '<div id="qr-reader"></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );

    expect(result.current.isCameraRunning).toBe(false);

    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    expect(result.current.isCameraRunning).toBe(true);

    act(() => {
      result.current.setIsCameraActive(false);
    });

    expect(result.current.isCameraRunning).toBe(false);

    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  // A start that is still pending when its run is torn down (a restart, the
  // wish switched off, the component gone) fails later, into a run nobody is
  // waiting on. What that late failure writes — the device state and the
  // error sentence — belongs to the run that owns the screen now.
  describe("a camera start that fails after its run was torn down", () => {
    const pendingStart = () => {
      let fail: (error: unknown) => void = () => {};
      const start = vi
        .spyOn(Html5Qrcode.prototype, "start")
        .mockImplementationOnce(
          () => new Promise<null>((_, reject) => (fail = reject)),
        );
      const logged = vi.spyOn(logger, "error").mockImplementation(() => {});
      return {
        fail: (error: unknown) => fail(error),
        logged,
        restore: () => {
          start.mockRestore();
          logged.mockRestore();
        },
      };
    };

    it("leaves the state of the run that replaced it alone", async () => {
      vi.useFakeTimers();
      const pending = pendingStart();
      try {
        const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
        MockQr.rejectError = null;
        document.body.innerHTML = '<div id="qr-reader"></div>';
        const { result } = renderHook(() =>
          useScanCamera({ onCodeScanned: vi.fn() }),
        );
        act(() => result.current.setIsCameraActive(true));
        // The first run's start is now in flight and never answers by itself.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(600);
        });
        expect(result.current.isCameraRunning).toBe(false);

        // A restart tears that run down; the second run starts and delivers.
        act(() => result.current.restartCamera());
        // Inside one act React renders once at the end, so the cooldown and
        // the start delay that follows it are waited out in separate steps.
        await act(async () => {
          await vi.advanceTimersByTimeAsync(150);
        });
        await act(async () => {
          await vi.advanceTimersByTimeAsync(600);
        });
        expect(result.current.isCameraRunning).toBe(true);

        // The first run's start now fails. It must not blank the second
        // run's "running" nor print its error over a camera that works.
        await act(async () => {
          pending.fail("NotAllowedError: Permission denied");
          await vi.advanceTimersByTimeAsync(0);
        });
        expect(pending.logged).toHaveBeenCalled();
        expect(result.current.scannerError).toBeNull();
        expect(result.current.isCameraRunning).toBe(true);

        await act(async () => {
          document.body.innerHTML = "";
        });
      } finally {
        pending.restore();
        vi.useRealTimers();
      }
    });

    it("is only logged when the hook was unmounted meanwhile", async () => {
      vi.useFakeTimers();
      const pending = pendingStart();
      try {
        document.body.innerHTML = '<div id="qr-reader"></div>';
        const { result, unmount } = renderHook(() =>
          useScanCamera({ onCodeScanned: vi.fn() }),
        );
        act(() => result.current.setIsCameraActive(true));
        await act(async () => {
          await vi.advanceTimersByTimeAsync(600);
        });

        unmount();
        // Rejecting into an unmounted hook must end in the log and nowhere
        // else: no throw out of the catch, no unhandled rejection (vitest
        // fails the run on one).
        await act(async () => {
          pending.fail(new Error("camera gone"));
          await vi.advanceTimersByTimeAsync(0);
        });
        expect(pending.logged).toHaveBeenCalledWith(
          "Camera start error:",
          expect.any(Error),
        );
        document.body.innerHTML = "";
      } finally {
        pending.restore();
        vi.useRealTimers();
      }
    });
  });

  it("stops the scanner when its reader leaves the page and restarts it when it returns", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");

    document.body.innerHTML = '<div id="qr-reader"></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(result.current.isCameraRunning).toBe(true);
    expect(start).toHaveBeenCalledTimes(1);

    // The panel closes; the hook stays mounted and the wish stays on.
    await act(async () => {
      document.body.innerHTML = "";
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    expect(result.current.isCameraRunning).toBe(false);
    expect(result.current.isCameraActive).toBe(true);

    await act(async () => {
      document.body.innerHTML = '<div id="qr-reader"></div>';
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(start).toHaveBeenCalledTimes(2);
    expect(result.current.isCameraRunning).toBe(true);

    start.mockRestore();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  it("releases the camera while the page is hidden and restarts it on return", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");
    const setVisibility = (state: "hidden" | "visible") => {
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        get: () => state,
      });
      document.dispatchEvent(new Event("visibilitychange"));
    };

    document.body.innerHTML = '<div id="qr-reader"></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(result.current.isCameraRunning).toBe(true);

    await act(async () => setVisibility("hidden"));
    expect(result.current.isCameraRunning).toBe(false);

    await act(async () => setVisibility("visible"));
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(start).toHaveBeenCalledTimes(2);
    expect(result.current.isCameraRunning).toBe(true);

    start.mockRestore();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  it("restarts the camera when the system ends the video track", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");

    document.body.innerHTML =
      '<div id="qr-reader"><video id="v"></video></div>';
    const track = new EventTarget();
    const video = document.getElementById("v") as HTMLVideoElement;
    Object.defineProperty(video, "srcObject", {
      value: { getVideoTracks: () => [track] },
    });
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(start).toHaveBeenCalledTimes(1);

    await act(async () => {
      track.dispatchEvent(new Event("ended"));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 200));
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(start).toHaveBeenCalledTimes(2);
    expect(result.current.isCameraRunning).toBe(true);

    start.mockRestore();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  it("publishes the region it decodes for the screen to draw its frame from", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");

    document.body.innerHTML = '<div><div id="qr-reader"></div></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    const config = start.mock.calls[0][1] as {
      qrbox: (w: number, h: number) => { width: number; height: number };
    };
    const region = config.qrbox(412, 232);
    const holder = document.getElementById("qr-reader")!.parentElement!;
    expect(holder.style.getPropertyValue("--aim-w")).toBe(`${region.width}px`);
    expect(holder.style.getPropertyValue("--aim-h")).toBe(`${region.height}px`);

    start.mockRestore();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  it("asks the camera for a real picture and wires the decode canvas when the library makes it", async () => {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");

    document.body.innerHTML = '<div><div id="qr-reader"></div></div>';
    const { result } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    const config = start.mock.calls[0][1] as {
      videoConstraints: { width: { ideal: number } };
    };
    expect(config.videoConstraints.width.ideal).toBe(1280);

    // The library creates the canvas after start() has resolved.
    const canvas = document.createElement("canvas");
    canvas.id = "qr-canvas";
    const draw = vi.fn();
    vi.spyOn(canvas, "getContext").mockReturnValue({
      drawImage: draw,
    } as unknown as CanvasRenderingContext2D);
    document.getElementById("qr-reader")!.appendChild(canvas);
    await vi.waitFor(() =>
      expect(canvas.getContext("2d")!.drawImage).not.toBe(draw),
    );

    start.mockRestore();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  it("clears every timer it scheduled when it goes away", () => {
    // A test environment (or a screen) that goes away inside the restart
    // cooldown used to take the callback with it: the timer fired after
    // teardown, state was set on a dead world, and vitest reported an
    // unhandled error — green tests, exit 1.
    const setTimeoutSpy = vi.spyOn(window, "setTimeout");
    const clearTimeoutSpy = vi.spyOn(window, "clearTimeout");

    const { result, unmount } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );

    act(() => {
      result.current.startCamera();
    });

    const scheduled = setTimeoutSpy.mock.results.map((entry) => entry.value);
    expect(scheduled.length).toBeGreaterThan(0);

    unmount();

    const cleared = clearTimeoutSpy.mock.calls.flat();
    for (const id of scheduled) {
      expect(cleared, `timer outlived the hook`).toContain(id);
    }
  });
});

// The library hands the hook a callback per decoded frame and another per
// frame it could not read; between them they say whether a code is still in
// front of the camera, which is what these walk.
describe("useScanCamera — one presence is one read", () => {
  const EAN = "5901234123457";
  const OTHER_EAN = "4006381333931";
  // Frames with nothing to read before a reported code counts as gone: the
  // hook's own allowance, mirrored here so the test says what it means.
  const AWAY = 40;

  async function boot(onCodeScanned: (code: string) => void) {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    const start = vi.spyOn(Html5Qrcode.prototype, "start");
    document.body.innerHTML = '<div id="qr-reader"></div>';
    const { result, unmount } = renderHook(() =>
      useScanCamera({ onCodeScanned }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });

    const current = () => {
      const call = start.mock.calls[start.mock.calls.length - 1] as unknown as [
        unknown,
        unknown,
        (text: string) => void,
        () => void,
      ];
      return { read: call[2], miss: call[3] };
    };

    return {
      ...current(),
      current,
      start,
      unmount: async () => {
        start.mockRestore();
        unmount();
        await act(async () => {
          document.body.innerHTML = "";
        });
      },
    };
  }

  it("reports a code held in the frame once, however long it is held", async () => {
    const onCodeScanned = vi.fn();
    const scanner = await boot(onCodeScanned);

    act(() => {
      for (let frame = 0; frame < 200; frame++) scanner.read(EAN);
    });

    expect(onCodeScanned).toHaveBeenCalledTimes(1);
    expect(onCodeScanned).toHaveBeenCalledWith(EAN);
    await scanner.unmount();
  });

  it("reports the same code again once it has been out of the frame", async () => {
    const onCodeScanned = vi.fn();
    const scanner = await boot(onCodeScanned);

    act(() => {
      for (let frame = 0; frame < 4; frame++) scanner.read(EAN);
    });
    expect(onCodeScanned).toHaveBeenCalledTimes(1);

    // Taken out of view: the decoder reads nothing for as long as the hook
    // waits before it would call the same code still showing.
    act(() => {
      for (let attempt = 0; attempt < AWAY; attempt++) scanner.miss();
    });
    act(() => {
      for (let frame = 0; frame < 4; frame++) scanner.read(EAN);
    });

    expect(onCodeScanned).toHaveBeenCalledTimes(2);
    await scanner.unmount();
  });

  it("reports a different code without the first one coming back", async () => {
    const onCodeScanned = vi.fn();
    const scanner = await boot(onCodeScanned);

    act(() => {
      for (let frame = 0; frame < 4; frame++) scanner.read(EAN);
    });
    act(() => {
      for (let frame = 0; frame < 4; frame++) scanner.read(OTHER_EAN);
    });

    expect(onCodeScanned).toHaveBeenCalledTimes(2);
    expect(onCodeScanned).toHaveBeenNthCalledWith(1, EAN);
    expect(onCodeScanned).toHaveBeenNthCalledWith(2, OTHER_EAN);
    await scanner.unmount();
  });

  it("reads the code in view again once the reader has been closed and reopened", async () => {
    const onCodeScanned = vi.fn();
    const scanner = await boot(onCodeScanned);

    act(() => {
      for (let frame = 0; frame < 4; frame++) scanner.read(EAN);
    });
    expect(onCodeScanned).toHaveBeenCalledTimes(1);

    // The panel closes: its reader element leaves the page. Reopening it
    // starts the camera again with the same code still in front of it.
    await act(async () => {
      document.body.innerHTML = "";
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    await act(async () => {
      document.body.innerHTML = '<div id="qr-reader"></div>';
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
    // The camera comes back on the reader's own delay; wait for the start
    // rather than for a guess at how long that is.
    await act(async () => {
      const until = Date.now() + 3000;
      while (scanner.start.mock.calls.length < 2 && Date.now() < until) {
        await new Promise((resolve) => setTimeout(resolve, 50));
      }
    });
    expect(scanner.start).toHaveBeenCalledTimes(2);

    const reopened = scanner.current();
    act(() => {
      for (let frame = 0; frame < 4; frame++) reopened.read(EAN);
    });

    expect(onCodeScanned).toHaveBeenCalledTimes(2);
    await scanner.unmount();
  });

  it("reports a code held through a turn of the phone once", async () => {
    // A turn restarts the camera to size its frame for the new screen. The
    // code in front of it never left: the restart is not a second presence.
    const turn = new EventTarget();
    const originalMatchMedia = window.matchMedia;
    window.matchMedia = vi
      .fn()
      .mockImplementation((query: string) =>
        query === "(orientation: portrait)"
          ? Object.assign(turn, { matches: true, media: query })
          : originalMatchMedia(query),
      );
    try {
      const onCodeScanned = vi.fn();
      const scanner = await boot(onCodeScanned);

      act(() => {
        for (let frame = 0; frame < 4; frame++) scanner.read(EAN);
      });
      expect(onCodeScanned).toHaveBeenCalledTimes(1);

      act(() => {
        turn.dispatchEvent(new Event("change"));
      });
      // The restart's cooldown ends in a render, which act holds back until
      // its scope closes: one scope for the cooldown, another for the start.
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 200));
      });
      await act(async () => {
        const until = Date.now() + 3000;
        while (scanner.start.mock.calls.length < 2 && Date.now() < until) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      });
      expect(scanner.start).toHaveBeenCalledTimes(2);

      const turned = scanner.current();
      act(() => {
        for (let frame = 0; frame < 200; frame++) turned.read(EAN);
      });
      expect(onCodeScanned).toHaveBeenCalledTimes(1);

      // Carried over, not frozen: taken away and shown again after the turn,
      // it is the second piece it is.
      act(() => {
        for (let attempt = 0; attempt < AWAY; attempt++) turned.miss();
        for (let frame = 0; frame < 4; frame++) turned.read(EAN);
      });
      expect(onCodeScanned).toHaveBeenCalledTimes(2);
      await scanner.unmount();
    } finally {
      window.matchMedia = originalMatchMedia;
    }
  });

  describe("when the window is resized with the camera running", () => {
    // A window that stays landscape raises no orientation event, yet the
    // box the frame was sized for is a different one.
    const sizeReader = (width: number, height: number) => {
      const reader = document.getElementById("qr-reader")!;
      Object.defineProperty(reader, "clientWidth", {
        configurable: true,
        value: width,
      });
      Object.defineProperty(reader, "clientHeight", {
        configurable: true,
        value: height,
      });
    };

    const bootAt = async (width: number, height: number) => {
      const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
      MockQr.rejectError = null;
      const start = vi.spyOn(Html5Qrcode.prototype, "start");
      document.body.innerHTML = '<div id="qr-reader"></div>';
      sizeReader(width, height);
      const { result, unmount } = renderHook(() =>
        useScanCamera({ onCodeScanned: vi.fn() }),
      );
      act(() => {
        result.current.setIsCameraActive(true);
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 600));
      });
      // The library sizes its box once, at start, through this callback.
      const qrbox = (
        start.mock.calls[0][1] as {
          qrbox: (w: number, h: number) => unknown;
        }
      ).qrbox;
      act(() => {
        qrbox(width, height);
      });
      return { start, unmount, result };
    };

    // The resize is debounced, the restart's cooldown ends in a render that
    // act holds back until its scope closes, and the start follows on the
    // reader's own delay: one scope for each, then wait for the start.
    const settle = async (
      start: { mock: { calls: unknown[] } },
      wanted: number,
    ) => {
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 300));
      });
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 200));
      });
      await act(async () => {
        const until = Date.now() + 3000;
        while (start.mock.calls.length < wanted && Date.now() < until) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
      });
    };

    it("starts the camera again so the frame is sized for the new box", async () => {
      const camera = await bootAt(1280, 720);
      expect(camera.start).toHaveBeenCalledTimes(1);

      sizeReader(863, 360);
      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      await settle(camera.start, 2);

      expect(camera.start).toHaveBeenCalledTimes(2);
      camera.start.mockRestore();
      camera.unmount();
    });

    it("leaves the camera alone when the box did not change", async () => {
      const camera = await bootAt(1280, 720);

      act(() => {
        window.dispatchEvent(new Event("resize"));
      });
      await settle(camera.start, 2);

      expect(camera.start).toHaveBeenCalledTimes(1);
      camera.start.mockRestore();
      camera.unmount();
    });
  });
});

// html5-qrcode draws the frame from this box and decodes the same pixels, so
// it has to stay inside the picture and inside what the screen shows, for
// every stream shape.
describe("decodeRegion", () => {
  it.each([
    ["square stream", 412, 412, 719],
    ["16:9 stream in portrait", 412, 232, 719],
    ["tall stream", 412, 719, 719],
    ["landscape strip", 863, 485, 360],
  ])("stays inside the visible picture: %s", (_n, w, h, visible) => {
    const box = decodeRegion(w, h, visible);
    expect(box.width).toBeLessThanOrEqual(w);
    expect(box.height).toBeLessThanOrEqual(Math.min(h, visible));
  });

  it("keeps a barcode-sized decode area on a thin 16:9 picture", () => {
    expect(decodeRegion(412, 232, 719).width).toBeGreaterThan(300);
  });
});

describe("decodeAtCameraResolution", () => {
  const setup = () => {
    const draw = vi.fn();
    const canvas = document.createElement("canvas");
    canvas.width = 288;
    canvas.height = 173;
    vi.spyOn(canvas, "getContext").mockReturnValue({
      drawImage: draw,
      getImageData: (_x: number, _y: number, w: number, h: number) => ({
        width: w,
        height: h,
        data: new Uint8ClampedArray(w * h * 4),
      }),
      putImageData: vi.fn(),
    } as unknown as CanvasRenderingContext2D);
    decodeAtCameraResolution(canvas);
    return { canvas, draw, context: canvas.getContext("2d")! };
  };

  it("sizes the decode canvas to the camera pixels the box covers", () => {
    const { canvas, draw, context } = setup();
    const video = document.createElement("video");
    context.drawImage(video, 10, 20, 648, 389, 0, 0, 288, 173);
    expect([canvas.width, canvas.height]).toEqual([648, 389]);
    expect(draw).toHaveBeenCalledWith(video, 10, 20, 648, 389, 0, 0, 648, 389);
  });

  it("caps the longest edge of a very large camera picture", () => {
    const { canvas, context } = setup();
    context.drawImage(
      document.createElement("video"),
      0,
      0,
      2560,
      1000,
      0,
      0,
      1,
      1,
    );
    expect([canvas.width, canvas.height]).toEqual([1280, 500]);
  });

  // `binarizeLocally` is tested on its own; nothing else sees that the
  // wrapper hands the wide-run pass to the right frame. Each frame the
  // camera draws goes by in a cycle of three: as seen, thresholded, and
  // thresholded with the wide ink of a dark package edge dropped.
  it("drops the wide ink of a dark surround on the third frame only", () => {
    const draw = vi.fn();
    const canvas = document.createElement("canvas");
    const width = 123;
    const height = 8;
    // black package edge | white label with a black bar | black package edge
    const row = [
      ...Array(40).fill(0),
      ...Array(20).fill(255),
      ...Array(3).fill(0),
      ...Array(20).fill(255),
      ...Array(40).fill(0),
    ];
    const put: ImageData[] = [];
    vi.spyOn(canvas, "getContext").mockReturnValue({
      drawImage: draw,
      getImageData: () => {
        const data = new Uint8ClampedArray(width * height * 4);
        for (let y = 0; y < height; y++)
          row.forEach((v, x) =>
            data.fill(v, (y * width + x) * 4, (y * width + x) * 4 + 3),
          );
        return { width, height, data } as unknown as ImageData;
      },
      putImageData: (picture: ImageData) => put.push(picture),
    } as unknown as CanvasRenderingContext2D);
    decodeAtCameraResolution(canvas);
    const video = document.createElement("video");
    const context = canvas.getContext("2d")!;
    for (let frame = 0; frame < 3; frame++) {
      context.drawImage(video, 0, 0, width, height, 0, 0, 1, 1);
    }

    // The first frame is left as the camera saw it: nothing is put back.
    expect(put).toHaveLength(2);
    // The pixel beside the label, in the black edge's wide run of ink.
    const beside = (3 * width + 39) * 4;
    expect(put[0].data[beside]).toBe(0);
    expect(put[1].data[beside]).toBe(255);
    // The bar itself is ink in both passes.
    const bar = (3 * width + 61) * 4;
    expect(put[0].data[bar]).toBe(0);
    expect(put[1].data[bar]).toBe(0);
  });
});

describe("binarizeLocally", () => {
  const paint = (rows: number[][]) => {
    const height = rows.length;
    const width = rows[0].length;
    const data = new Uint8ClampedArray(width * height * 4);
    rows.forEach((row, y) =>
      row.forEach((v, x) =>
        data.fill(v, (y * width + x) * 4, (y * width + x) * 4 + 3),
      ),
    );
    return { width, height, data } as unknown as ImageData;
  };

  it("keeps the bars as ink and a flat mid-tone surround as paper", () => {
    // gray surround | white label with a black bar | gray surround
    const row = [
      ...Array(40).fill(140),
      ...Array(20).fill(255),
      ...Array(3).fill(0),
      ...Array(20).fill(255),
      ...Array(40).fill(140),
    ];
    const image = paint(Array(8).fill(row));
    binarizeLocally(image);
    const at = (x: number) => image.data[(3 * 123 + x) * 4];
    expect(at(10)).toBe(255);
    expect(at(41)).toBe(255);
    expect(at(60)).toBe(0);
    expect(at(110)).toBe(255);
  });
});

describe("binarizeLocally on a dark surround", () => {
  it("drops an ink run too wide to be a bar, keeps the bars", () => {
    // black package edge | white label with a black bar | black package edge
    const row = [
      ...Array(40).fill(0),
      ...Array(20).fill(255),
      ...Array(3).fill(0),
      ...Array(20).fill(255),
      ...Array(40).fill(0),
    ];
    const data = new Uint8ClampedArray(123 * 8 * 4);
    for (let y = 0; y < 8; y++)
      row.forEach((v, x) =>
        data.fill(v, (y * 123 + x) * 4, (y * 123 + x) * 4 + 3),
      );
    const image = { width: 123, height: 8, data } as unknown as ImageData;
    binarizeLocally(image, true);
    const at = (x: number) => image.data[(3 * 123 + x) * 4];
    expect(at(10)).toBe(255);
    expect(at(39)).toBe(255);
    expect(at(61)).toBe(0);
    expect(at(110)).toBe(255);
  });
});

describe("binarizeLocally on faint print", () => {
  it("keeps grey ink on white paper as ink", () => {
    const row = [
      ...Array(20).fill(255),
      ...Array(3).fill(140),
      ...Array(20).fill(255),
    ];
    const data = new Uint8ClampedArray(43 * 8 * 4);
    for (let y = 0; y < 8; y++)
      row.forEach((v, x) =>
        data.fill(v, (y * 43 + x) * 4, (y * 43 + x) * 4 + 3),
      );
    const image = { width: 43, height: 8, data } as unknown as ImageData;
    binarizeLocally(image);
    expect(image.data[(3 * 43 + 21) * 4]).toBe(0);
    expect(image.data[(3 * 43 + 5) * 4]).toBe(255);
  });
});

describe("whenDecodeCanvas", () => {
  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("hands over the decode canvas when it appears after the call", async () => {
    const onCanvas = vi.fn();
    whenDecodeCanvas(onCanvas);
    const reader = document.createElement("div");
    reader.id = "qr-reader";
    const canvas = document.createElement("canvas");
    canvas.id = "qr-canvas";
    reader.appendChild(canvas);
    document.body.appendChild(reader);
    await vi.waitFor(() => expect(onCanvas).toHaveBeenCalledWith(canvas));
    expect(onCanvas).toHaveBeenCalledTimes(1);
  });

  it("stops watching when cancelled", async () => {
    const onCanvas = vi.fn();
    whenDecodeCanvas(onCanvas)();
    const reader = document.createElement("div");
    reader.id = "qr-reader";
    const canvas = document.createElement("canvas");
    canvas.id = "qr-canvas";
    reader.appendChild(canvas);
    document.body.appendChild(reader);
    await new Promise((r) => setTimeout(r, 20));
    expect(onCanvas).not.toHaveBeenCalled();
  });
});

describe("useScanCamera — the flashlight", () => {
  afterEach(async () => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    await act(async () => {
      document.body.innerHTML = "";
    });
  });

  async function runCamera(stream?: object) {
    const MockQr = Html5Qrcode as unknown as { rejectError: unknown };
    MockQr.rejectError = null;
    document.body.innerHTML = '<div id="qr-reader"><video></video></div>';
    if (stream) {
      Object.defineProperty(document.querySelector("video"), "srcObject", {
        value: stream,
        configurable: true,
      });
    }
    const hook = renderHook(() => ({
      ...useScanCamera({ onCodeScanned: vi.fn() }),
      hasTorch: useTorchAvailable(),
    }));
    act(() => {
      hook.result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(hook.result.current.isCameraRunning).toBe(true);
    return hook;
  }

  it.each([
    ["has a torch", true],
    ["has none", false],
  ])("knows before any tap whether the camera %s", async (_, torch) => {
    const { result } = await runCamera({
      getVideoTracks: () => [
        {
          addEventListener: () => {},
          getCapabilities: () => (torch ? { torch: true } : {}),
        },
      ],
    });

    expect(result.current.hasTorch).toBe(torch);
  });

  it("says the flashlight is not supported when the camera has no torch", async () => {
    const error = vi.spyOn(toast, "error").mockImplementation(() => "id");
    const { result } = await runCamera();

    await act(async () => {
      await result.current.toggleTorch();
    });

    expect(error).toHaveBeenCalledWith("Flashlight not supported");
    expect(result.current.isTorchOn).toBe(false);
  });

  it("switches the torch on through the camera's constraints when it has one", async () => {
    class FakeStream {
      getVideoTracks() {
        return [{ getCapabilities: () => ({ torch: true }) }];
      }
    }
    vi.stubGlobal("MediaStream", FakeStream);
    const error = vi.spyOn(toast, "error").mockImplementation(() => "id");
    const { result } = await runCamera();
    const video = document.querySelector("video") as HTMLVideoElement;
    Object.defineProperty(video, "srcObject", {
      value: new FakeStream(),
      configurable: true,
    });
    const MockQr = Html5Qrcode as unknown as { constraints: unknown[] };
    MockQr.constraints.length = 0;

    await act(async () => {
      await result.current.toggleTorch();
    });

    expect(MockQr.constraints).toEqual([{ advanced: [{ torch: true }] }]);
    expect(result.current.isTorchOn).toBe(true);
    expect(error).not.toHaveBeenCalled();
  });
});

describe("absorbReaderPlayAbort", () => {
  const original = HTMLVideoElement.prototype.play;
  const unhandled: unknown[] = [];
  const onUnhandled = (reason: unknown) => unhandled.push(reason);

  afterEach(() => {
    HTMLVideoElement.prototype.play = original;
    process.off("unhandledRejection", onUnhandled);
    unhandled.length = 0;
    document.body.innerHTML = "";
  });

  const removedWhileStarting = () =>
    Object.assign(new Error("The play() request was interrupted"), {
      name: "AbortError",
    });

  async function playAndDrain(video: HTMLVideoElement) {
    process.off("unhandledRejection", onUnhandled);
    process.on("unhandledRejection", onUnhandled);
    video.play();
    // Node reports an unhandled rejection after the microtask queue drains.
    await new Promise((resolve) => setTimeout(resolve, 20));
  }

  it("keeps the reader's interrupted play() from surfacing as an unhandled rejection", async () => {
    HTMLVideoElement.prototype.play = () =>
      Promise.reject(removedWhileStarting());
    absorbReaderPlayAbort();
    absorbReaderPlayAbort();
    document.body.innerHTML = '<div id="qr-reader"><video></video></div>';

    await playAndDrain(document.querySelector("video")!);

    expect(unhandled).toEqual([]);
  });

  it("is in place by the time the camera starts, so a cancelled start leaves no unhandled rejection", async () => {
    HTMLVideoElement.prototype.play = () =>
      Promise.reject(removedWhileStarting());
    // The library plays the video it puts in the reader while start() runs.
    const start = vi
      .spyOn(Html5Qrcode.prototype, "start")
      .mockImplementation(async () => {
        document.querySelector("video")!.play();
        return null;
      });
    process.on("unhandledRejection", onUnhandled);
    document.body.innerHTML = '<div id="qr-reader"><video></video></div>';

    const { result, unmount } = renderHook(() =>
      useScanCamera({ onCodeScanned: vi.fn() }),
    );
    act(() => {
      result.current.setIsCameraActive(true);
    });
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 600));
    });
    expect(start).toHaveBeenCalled();
    // Node reports an unhandled rejection after the microtask queue drains.
    await new Promise((resolve) => setTimeout(resolve, 20));
    unmount();
    vi.restoreAllMocks();

    expect(unhandled).toEqual([]);
  });

  it("leaves a failure other than the interruption, and any other video, alone", async () => {
    HTMLVideoElement.prototype.play = () =>
      Promise.reject(new DOMException("denied", "NotAllowedError"));
    absorbReaderPlayAbort();
    document.body.innerHTML =
      '<div id="qr-reader"><video id="a"></video></div><video id="b"></video>';

    await playAndDrain(document.getElementById("a") as HTMLVideoElement);
    expect(unhandled).toHaveLength(1);

    HTMLVideoElement.prototype.play = () =>
      Promise.reject(removedWhileStarting());
    absorbReaderPlayAbort();
    unhandled.length = 0;
    await playAndDrain(document.getElementById("b") as HTMLVideoElement);
    expect(unhandled).toHaveLength(1);
  });
});
