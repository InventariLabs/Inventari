import { logger } from "@/utils/logger";
import { ReadableError } from "@/lib/errors";
import i18n from "@/i18n/config";

export async function compressImage(
  file: File,

  maxWidth = 1024,

  quality = 0.8,
): Promise<File> {
  const options = {
    maxSizeMB: 0.8,

    maxWidthOrHeight: maxWidth,

    useWebWorker: true,

    initialQuality: quality,

    fileType: "image/jpeg",
  };

  try {
    const { default: imageCompression } =
      await import("browser-image-compression");
    const compressedFile = await imageCompression(file, options);

    return compressedFile;
  } catch (error) {
    logger.error("Compression failed, using original:", error);

    return file;
  }
}

const SHRINKABLE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const UPLOADABLE_TYPES = [...SHRINKABLE_TYPES, "image/gif"];

/** Longest side a stored photo keeps: sharp on a detail screen, a fraction of a phone original. */
const UPLOAD_IMAGE_MAX_SIDE = 1600;

/**
 * The one gate every picture upload passes before its size is checked: a
 * format the server cannot store is refused with the same sentence on every
 * screen, and a JPEG/PNG/WebP is shrunk in the browser (orientation kept,
 * type kept so a logo's transparency survives) — a 5–15 MB phone photo
 * becomes a few hundred KB instead of being served whole to a 94 px
 * thumbnail or refused for its size.
 *
 * `imageOnly` is for endpoints that take pictures and nothing else; the
 * attachment endpoints take documents too, so only a file that claims to be
 * a picture is held to the picture rules there.
 */
export async function prepareImageUpload(
  file: File,
  { imageOnly = true }: { imageOnly?: boolean } = {},
): Promise<File> {
  const isPicture = file.type.startsWith("image/");
  if (!isPicture && !imageOnly) return file;
  if (!UPLOADABLE_TYPES.includes(file.type)) {
    // Shown by whichever caller catches it, through extractApiError — one
    // sentence on every screen, not a toast plus each screen's own fallback.
    throw new ReadableError(i18n.t("common:errors.imageFormatUnsupported"));
  }
  if (!SHRINKABLE_TYPES.includes(file.type)) return file;
  try {
    // Loaded on first use: this module sits on the startup path through the
    // API clients, and the library is not needed until someone picks a photo.
    const { default: imageCompression } =
      await import("browser-image-compression");
    const shrunk = await imageCompression(file, {
      maxSizeMB: 1,
      maxWidthOrHeight: UPLOAD_IMAGE_MAX_SIDE,
      useWebWorker: true,
    });
    // The library hands back a Blob in some paths; multipart upload names a
    // Blob "blob", which the server's extension check and the stored
    // original_name then see instead of the picture's own name.
    return shrunk.size < file.size
      ? new File([shrunk], file.name, { type: shrunk.type || file.type })
      : file;
  } catch (error) {
    logger.error("Shrinking failed, using original:", error);
    return file;
  }
}
