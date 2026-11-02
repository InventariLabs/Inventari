import { expect, type Page, type Request } from '@playwright/test';

import { test as authTest } from './auth';
import { ean13Modules, qrModules } from '../helpers/barcode';

/**
 * A camera the test controls.
 *
 * Chromium's --use-fake-device-for-media-stream shows a fixed pattern in
 * Chromium alone. This replaces `navigator.mediaDevices.getUserMedia` with the
 * `captureStream()` of a canvas, so the same spec runs in every project the
 * config has — the iPhone ones included — and can take the code out of view
 * in the middle of a run.
 *
 * The page sees a real MediaStream. The fixture counts the streams it handed
 * out and how many of them were released, and the scan lookups the app sent.
 */

const SCAN_URL = /\/api\/v1\/labels\/scan\//;

interface FakeCameraState {
  opened: number;
  live: number;
  frames: number;
}

/** Runs in the page before any app code. Kept self-contained. */
function installFakeCamera() {
  const canvas = document.createElement('canvas');
  // A phone held upright delivers a portrait frame. The reader looks at a box
  // in the middle of it, so the code is drawn small.
  canvas.width = 720;
  canvas.height = 1280;
  // WebKit only produces frames for a canvas that is in the document.
  canvas.style.cssText = 'position:fixed;left:0;top:0;width:1px;height:1px;opacity:0;pointer-events:none';
  document.addEventListener('DOMContentLoaded', () => document.body.appendChild(canvas));
  const ctx = canvas.getContext('2d')!;
  let drawing: (() => void) | null = null;
  const state = { opened: 0, live: 0, frames: 0 };

  const blank = () => {
    ctx.fillStyle = '#808080';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  };
  blank();
  // A canvas only produces frames when it changes; repaint steadily.
  let tick = 0;
  setInterval(() => {
    state.frames++;
    if (drawing) drawing();
    else blank();
    // A pixel that changes every frame: WebKit sends no frame for a canvas it
    // sees unchanged, and the video would stay at readyState 0.
    ctx.fillStyle = tick++ % 2 ? '#fe0000' : '#ff0000';
    ctx.fillRect(0, 0, 1, 1);
  }, 33);

  const control = {
    state,
    showBars(bars: string) {
      const unit = 3;
      const width = bars.length * unit;
      const height = 200;
      const x0 = Math.floor((canvas.width - width) / 2);
      const y0 = Math.floor((canvas.height - height) / 2);
      drawing = () => {
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#000';
        for (let i = 0; i < bars.length; i++) {
          if (bars[i] === '1') ctx.fillRect(x0 + i * unit, y0, unit, height);
        }
      };
    },
    showMatrix(rows: boolean[][]) {
      const quiet = 4;
      const unit = 6;
      const side = (rows.length + 2 * quiet) * unit;
      const x0 = Math.floor((canvas.width - side) / 2);
      const y0 = Math.floor((canvas.height - side) / 2);
      drawing = () => {
        ctx.fillStyle = '#fff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.fillStyle = '#000';
        rows.forEach((row, r) =>
          row.forEach((on, c) => {
            if (on) ctx.fillRect(x0 + (c + quiet) * unit, y0 + (r + quiet) * unit, unit, unit);
          }),
        );
      };
    },
    hide() {
      drawing = null;
    },
  };
  (window as unknown as { __fakeCamera: typeof control }).__fakeCamera = control;

  // The fake's tracks, by id. Patched on the prototype, not on each track:
  // WebKit drops a track's JS wrapper — and anything set on it — once the
  // page holds no reference to it, so a per-track override was gone by the
  // time the reader stopped the track, and the stream read as never released.
  const fakeTracks = new Set<string>();
  const liveTracks = new Set<string>();
  const proto = MediaStreamTrack.prototype;
  const nativeStop = proto.stop;
  const nativeApplyConstraints = proto.applyConstraints;
  proto.stop = function (this: MediaStreamTrack) {
    if (liveTracks.delete(this.id)) state.live--;
    nativeStop.call(this);
  };
  proto.applyConstraints = function (this: MediaStreamTrack, constraints?: MediaTrackConstraints) {
    if (!fakeTracks.has(this.id)) return nativeApplyConstraints.call(this, constraints);
    // WebKit ignores the aspect-ratio constraint the reader applies;
    // Chromium would crop the canvas to a square. Keep the frame as drawn.
    //
    // The reader puts its <video> in the page, awaits this call, then starts
    // playback. Linux WebKit (GStreamer) suspends a muted player that is not
    // known to be in the viewport when it starts, and never resumes it; a
    // video added in the same task has not been through a rendering update
    // yet, so it counts as out of view. A real camera takes a moment here
    // too: resolve after two frames.
    return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(() => resolve())));
  };

  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: async () => {
        const stream = canvas.captureStream(30);
        state.opened++;
        for (const track of stream.getTracks()) {
          fakeTracks.add(track.id);
          liveTracks.add(track.id);
          state.live++;
        }
        return stream;
      },
      enumerateDevices: async () => [
        { deviceId: 'fake', kind: 'videoinput', label: 'Fake camera', groupId: 'fake' },
      ],
      addEventListener: () => {},
      removeEventListener: () => {},
    },
  });
}

export interface FakeCamera {
  /** Put an EAN-13 in front of the camera. */
  showEan13(code: string): Promise<void>;
  /** Put a QR code (up to 32 bytes of text) in front of the camera. */
  showQr(text: string): Promise<void>;
  /** Take the code out of view. */
  hide(): Promise<void>;
  /** GET /labels/scan/* requests the app sent since the last `resetScanRequests`. */
  scanRequests(): string[];
  resetScanRequests(): void;
  /** Resolves once the camera has shown `count` more frames — time the app gets to read. */
  runFrames(count: number): Promise<void>;
  /** Streams handed to the app, and how many of their tracks are still live. */
  streams(): Promise<FakeCameraState>;
}

interface Control {
  state: FakeCameraState;
  showBars(bars: string): void;
  showMatrix(rows: boolean[][]): void;
  hide(): void;
}

async function attach(page: Page): Promise<FakeCamera> {
  const scans: string[] = [];
  page.on('request', (req: Request) => {
    if (req.method() === 'GET' && SCAN_URL.test(req.url())) {
      scans.push(decodeURIComponent(new URL(req.url()).pathname.split('/labels/scan/')[1]));
    }
  });
  await page.addInitScript(installFakeCamera);
  const frames = () =>
    page.evaluate(() => (window as unknown as { __fakeCamera: Control }).__fakeCamera.state.frames);
  return {
    showEan13: (code) => page.evaluate((bars) => (window as unknown as { __fakeCamera: Control }).__fakeCamera.showBars(bars), ean13Modules(code)),
    showQr: (text) => page.evaluate((rows) => (window as unknown as { __fakeCamera: Control }).__fakeCamera.showMatrix(rows), qrModules(text)),
    hide: () => page.evaluate(() => (window as unknown as { __fakeCamera: Control }).__fakeCamera.hide()),
    scanRequests: () => [...scans],
    resetScanRequests: () => {
      scans.length = 0;
    },
    runFrames: async (count) => {
      // The frames are the condition, not the clock: a loaded machine draws
      // fewer of them a second, and a deadline of its own failed the wait
      // after 156 of 240 while the app had done nothing wrong. The test's own
      // timeout bounds it.
      const target = (await frames()) + count;
      await page.waitForFunction(
        (n) => (window as unknown as { __fakeCamera: Control }).__fakeCamera.state.frames >= n,
        target,
        { timeout: 0, polling: 100 },
      );
    },
    streams: () => page.evaluate(() => (window as unknown as { __fakeCamera: Control }).__fakeCamera.state),
  };
}

export const test = authTest.extend<{ camera: FakeCamera }>({
  camera: async ({ page, authenticatedPage: _auth }, use) => {
    await use(await attach(page));
  },
});

export { expect };
