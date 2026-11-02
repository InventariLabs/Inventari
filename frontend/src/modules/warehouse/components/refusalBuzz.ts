/**
 * A short, uneven buzz for a scan the screen refused. A good scan buzzes once
 * and evenly; a worker who is looking at the product and not at the screen
 * feels the difference. Phones without a vibration motor ignore it.
 */
export function buzzRefusal() {
  if ("vibrate" in navigator) navigator.vibrate([80, 60, 80]);
}
