/**
 * Scrolls the scrollable box `field` sits in — and nothing around it — so the
 * field lands in the middle of it.
 *
 * `scrollIntoView` also scrolls every ancestor, including the fixed overlay a
 * sheet slides in on, which leaves the sheet's header above the screen.
 */
export function centerInScrollBody(field: Element): void {
  let body = field.parentElement;
  while (body && !/(auto|scroll)/.test(getComputedStyle(body).overflowY)) {
    body = body.parentElement;
  }
  if (!body) return;
  const at = field.getBoundingClientRect();
  const within = body.getBoundingClientRect();
  body.scrollTop += at.top - within.top - (body.clientHeight - at.height) / 2;
}
