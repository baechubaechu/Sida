// The drafting table's one camera, as plain numbers. Ground is the x–y plane in metres, z is up,
// +y is north. `tilt` 0° looks straight down (a plan); 35° reads as an axonometric; 70° is near eye
// level. A long lens at low tilt keeps the plan free of perspective; it widens as the table tilts.

export const TILT = { plan: 0, axo: 35, eye: 68 };
export const MAX_TILT = 75;
export const VIEW_LIMITS = { min: 12, max: 2500 }; // metres of table shown top to bottom

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const rad = (d) => (d * Math.PI) / 180;

export function lensFor(tilt) {
  return 6 + 32 * smooth(0, 40, tilt); // field of view in degrees
}

// How far masses stand up: flat footprints in plan, full height once the table leans.
export function riseFor(tilt) {
  return Math.max(0.004, smooth(3, 28, tilt));
}

// Camera position, up vector and lens for a view {x, y, span, tilt, turn}.
export function cameraFor(v) {
  const fov = lensFor(v.tilt);
  const dist = v.span / 2 / Math.tan(rad(fov) / 2);
  const t = rad(v.tilt);
  const fx = Math.sin(rad(v.turn));
  const fy = Math.cos(rad(v.turn)); // direction the viewer faces on the table
  return {
    fov, dist,
    position: [v.x - fx * dist * Math.sin(t), v.y - fy * dist * Math.sin(t), dist * Math.cos(t)],
    up: [fx * Math.cos(t), fy * Math.cos(t), Math.sin(t)],
    target: [v.x, v.y, 0],
  };
}

// Zoom by `factor` around a table point (gx, gy) that stays under the cursor.
export function zoomAround(v, gx, gy, factor) {
  const span = Math.min(VIEW_LIMITS.max, Math.max(VIEW_LIMITS.min, v.span * factor));
  const k = span / v.span;
  return { ...v, span, x: gx + (v.x - gx) * k, y: gy + (v.y - gy) * k };
}

// Drawing scale shown in the corner, for a 96 dpi screen: "1:500".
export function drawingScale(span, viewportPx) {
  const metresPerPx = span / viewportPx;
  const n = metresPerPx / 0.0002646;
  const nice = [50, 100, 200, 250, 500, 1000, 1200, 2000, 2500, 5000, 10000, 25000];
  return `1:${nice.reduce((a, b) => (Math.abs(b - n) < Math.abs(a - n) ? b : a))}`;
}

export function lerpView(a, b, k) {
  let dt = ((b.turn - a.turn + 540) % 360) - 180;
  return { x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, span: a.span + (b.span - a.span) * k, tilt: a.tilt + (b.tilt - a.tilt) * k, turn: a.turn + dt * k };
}
