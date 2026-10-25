// Board state as plain data: items (cards, notes) and pen strokes in world coordinates,
// a camera, and pure helpers. No DOM here, so these can be tested on their own.

export const MIN_ZOOM = 0.15;
export const MAX_ZOOM = 3;

export const clampZoom = (z) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z));

// Screen point → world point for camera {x, y, zoom} (x, y: world point at the screen's top-left).
export const toWorld = (cam, sx, sy) => ({ x: cam.x + sx / cam.zoom, y: cam.y + sy / cam.zoom });

// Zoom by `factor` keeping the world point under screen point (sx, sy) where it is.
export function zoomAt(cam, sx, sy, factor) {
  const zoom = clampZoom(cam.zoom * factor);
  const p = toWorld(cam, sx, sy);
  return { zoom, x: p.x - sx / zoom, y: p.y - sy / zoom };
}

export function boundsOf(items) {
  if (!items.length) return null;
  const minX = Math.min(...items.map((i) => i.x));
  const minY = Math.min(...items.map((i) => i.y));
  const maxX = Math.max(...items.map((i) => i.x + i.w));
  const maxY = Math.max(...items.map((i) => i.y + i.h));
  return { x: minX, y: minY, w: maxX - minX, h: maxY - minY };
}

// Camera that shows `box` inside a viewport of (vw, vh) with a margin.
export function fitCamera(box, vw, vh, margin = 60, maxZoom = 1) {
  if (!box) return { x: -vw / 2, y: -vh / 2, zoom: 1 };
  const zoom = clampZoom(Math.min((vw - margin * 2) / box.w, (vh - margin * 2) / box.h, maxZoom));
  return { zoom, x: box.x + box.w / 2 - vw / 2 / zoom, y: box.y + box.h / 2 - vh / 2 / zoom };
}

export const intersects = (a, b) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;

export function rectFrom(p, q) {
  return { x: Math.min(p.x, q.x), y: Math.min(p.y, q.y), w: Math.abs(p.x - q.x), h: Math.abs(p.y - q.y) };
}

// A free spot to the right of everything on the board, top-aligned with it.
export function nextSpot(items, gap = 40) {
  const b = boundsOf(items);
  return b ? { x: b.x + b.w + gap, y: b.y } : { x: 0, y: 0 };
}

// Undo history: past and future snapshots of {items, strokes}.
export function pushHistory(history, snapshot, limit = 100) {
  return { past: [...history.past, snapshot].slice(-limit), future: [] };
}
