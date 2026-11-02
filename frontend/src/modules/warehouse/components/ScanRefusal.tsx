/**
 * The answer to a scan the screen refused, beside the field that was scanned
 * into. A toast is gone in seconds, while the worker is still looking at the
 * viewfinder; this stays until the next scan answers.
 */
export default function ScanRefusal({ message }: { message: string }) {
  return (
    <p
      role="alert"
      className="rounded-lg bg-red-50 px-3 py-2 text-sm text-on-danger"
    >
      {message}
    </p>
  );
}
