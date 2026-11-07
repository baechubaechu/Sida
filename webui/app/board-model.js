// Helpers for the drafting table (제도판) that touch neither the DOM nor three.js, so
// tests/webui/board-model.test.mjs can check them. The table is the x–y plane in metres,
// x east, y north, 0, 0 the middle of the site (GET .../board → site.plan).
// Figures (coverage, FAR) are never computed here: they come from the server (`figures`).

import { SECTION_LABELS } from './model.js';

export const PX = 0.1; // metres per CSS pixel of paper lying on the table
// Two views, as in Rhino's Top and Perspective (2026-11-01 지훈): the plan, and one 3D view whose
// angle the right mouse button sets. `persp` is where the 3D button lands from a plan.
export const TILT = { plan: 0, persp: 35 };
export const MAX_TILT = 90; // lying flat to the table shows elevations (2026-11-01 지훈)
export const FOLD_TILT = 10; // past this lean papers fold into pins, so the model reads (2026-10-26)
export const VIEW_LIMITS = { min: 12, max: 2500 }; // metres of table shown top to bottom
export const TRACE_MARGIN = 14; // metres of tracing paper around the site
// A paper dragged by a corner keeps its size between these (CSS px of paper; 1 px is 0.1 m).
export const PAPER_LIMITS = { min: 60, max: 4000 };
export const PAPER_SIZE = { site: [300, 250], mass: [300, 210], note: [200, 140], expert: [320, 270], photo: [300, 225] };
export const MAX_BLOCKS = 20;
export const MAX_CONTEXT = 8; // papers one message may carry (board.MAX_CONTEXT)

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const rad = (d) => (d * Math.PI) / 180;

export const fmt = (n, digits = 0) => Number(n).toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits });

// Which papers a corner drag resizes: not a tracing sheet (it is the size of the site, to lie in
// register over it) and not one folded into a name tag.
export function resizable(p) {
  return Boolean(p) && p.kind !== 'tracing' && !p.folded;
}

// A paper {x, y, w, h} (middle in metres, size in CSS px) dragged by its corner `corner`
// ('nw', 'ne', 'sw', 'se', as the paper reads: n is +y) to the table point {x, y}. The opposite
// corner stays where it is. `ratio` keeps the paper's shape (a photo), taking the larger pull.
export function resizedPaper(from, corner, point, { ratio = false, min = PAPER_LIMITS.min, max = PAPER_LIMITS.max } = {}) {
  const sx = corner.includes('e') ? 1 : -1;
  const sy = corner.includes('n') ? 1 : -1;
  const fixed = { x: from.x - (sx * from.w * PX) / 2, y: from.y - (sy * from.h * PX) / 2 };
  const clamp = (v) => Math.min(max, Math.max(min, v));
  let w = clamp((sx * (point.x - fixed.x)) / PX);
  let h = clamp((sy * (point.y - fixed.y)) / PX);
  if (ratio && from.w > 0 && from.h > 0) {
    const k = Math.max(w / from.w, h / from.h);
    const lo = Math.max(min / from.w, min / from.h);
    const hi = Math.min(max / from.w, max / from.h);
    const kk = Math.min(hi, Math.max(lo, k));
    w = from.w * kk;
    h = from.h * kk;
  }
  w = Math.round(w);
  h = Math.round(h);
  return { x: fixed.x + (sx * w * PX) / 2, y: fixed.y + (sy * h * PX) / 2, w, h };
}

// ------------------------------------------------------------------ camera
// One camera, as plain numbers. tilt 0° looks straight down (a plan); leaning further goes from a
// bird's-eye view toward eye level. A long lens at low tilt keeps the plan flat.

export function lensFor(tilt) {
  return 6 + 32 * smooth(0, 40, tilt); // field of view in degrees
}

// How far masses stand up: flat footprints in plan, full height once the table leans.
export function riseFor(tilt) {
  return Math.max(0.004, smooth(3, 28, tilt));
}

// Camera position, up vector and lens for a view {x, y, span, tilt, turn, z}. The camera turns
// about one fixed point, the target (x, y, z), as in Rhino: no angle moves it (2026-11-02 지훈:
// the pivot seemed to change part way through an orbit). z (metres, 0 when left out) lifts the
// target off the table, so an elevation can be panned up a tower.
export function cameraFor(v) {
  const z = v.z || 0;
  const fov = lensFor(v.tilt);
  const dist = v.span / 2 / Math.tan(rad(fov) / 2);
  const t = rad(v.tilt);
  const fx = Math.sin(rad(v.turn));
  const fy = Math.cos(rad(v.turn)); // the direction the viewer faces on the table
  return {
    fov, dist,
    position: [v.x - fx * dist * Math.sin(t), v.y - fy * dist * Math.sin(t), z + dist * Math.cos(t)],
    up: [fx * Math.cos(t), fy * Math.cos(t), Math.sin(t)],
    target: [v.x, v.y, z],
  };
}

// How much of the ground (grid, shadows, site outline, tracings) shows, 0 to 1: lying flat for an
// elevation it fades away, so only the buildings stand (2026-11-02 지훈: no ground in an elevation).
export function groundFor(tilt) {
  return 1 - smooth(80, 88, tilt);
}

// Pan by (dx, dy) screen pixels so the picture follows the mouse, measured at the point looked at:
// for a view seen near edge-on (an elevation), where the table under the cursor is too far off or
// not there at all. Moving up the screen in an elevation climbs the building (z), never below 0.
export function panBy(v, dx, dy, heightPx) {
  const k = v.span / Math.max(1, heightPx); // metres per pixel at the target
  const c = cameraFor(v);
  const right = [Math.cos(rad(v.turn)), -Math.sin(rad(v.turn)), 0];
  const move = right.map((r, i) => -r * dx * k + c.up[i] * dy * k);
  return { ...v, x: v.x + move[0], y: v.y + move[1], z: Math.max(0, (v.z || 0) + move[2]) };
}

// Zoom by `factor` around a table point (gx, gy) that stays under the cursor.
export function zoomAround(v, gx, gy, factor) {
  const span = Math.min(VIEW_LIMITS.max, Math.max(VIEW_LIMITS.min, v.span * factor));
  const k = span / v.span;
  return { ...v, span, x: gx + (v.x - gx) * k, y: gy + (v.y - gy) * k };
}

// Mouse like Rhino (2026-11-01 지훈): which view move a drag makes. The right button orbits, in
// plan too, so a plan tips straight into 3D (2026-11-02 지훈); Shift+right pans and Ctrl+right
// zooms. The middle button always pans, and Alt+left orbits for a trackpad.
// null: the left button's own work (select, move, draw; on empty table a selection box).
export const PLAN_TILT = 4; // below this lean the view counts as a plan
export const EDGE_TILT = 70; // past this lean the table is seen near edge-on: pan and zoom on the screen, not the table
export function dragMode({ button = 0, shift = false, ctrl = false, alt = false } = {}) {
  if (button === 1) return 'pan';
  if (button === 2) {
    if (ctrl) return 'zoom';
    if (shift) return 'pan';
    return 'orbit';
  }
  if (button === 0 && alt) return 'orbit';
  return null;
}

// Turn and tilt after an orbit drag of (dx, dy) screen pixels from the view `v`, Rhino's way:
// the model follows the mouse, so dragging right brings its near side right (turn grows) and
// dragging down brings its top toward the viewer (tilt shrinks toward a plan).
export function orbitBy(v, dx, dy) {
  return { turn: v.turn + dx * 0.3, tilt: Math.min(MAX_TILT, Math.max(0, v.tilt - dy * 0.25)) };
}

// Which view button is lit: 'plan' near 0°, '3d' at any other lean.
export function viewName(tilt) {
  return tilt < PLAN_TILT ? 'plan' : '3d';
}

// Where a view button (or the keys 1 and 2, or the plan/persp commands) takes the view `v`.
// The plan faces north. The 3D button leaves a 3D view as it is, and from a plan stands the
// table up to TILT.persp, turned a little so the masses read. null: nothing to do.
export function viewFor(name, v) {
  if (name === 'plan') return { tilt: TILT.plan, turn: 0, z: 0 };
  if (name !== '3d' || viewName(v.tilt) === '3d') return null;
  return { tilt: TILT.persp, turn: v.turn || -30 };
}

// Zoom factor for one wheel event: rolling forward (deltaY < 0) zooms in. A mouse notch is
// about 100 px and zooms ~16%; a trackpad pinch (ctrlKey) sends small steps and gets more.
export function wheelZoom(deltaY, deltaMode = 0, pinch = false) {
  const px = deltaMode === 1 ? deltaY * 16 : deltaMode === 2 ? deltaY * 400 : deltaY;
  return Math.exp(px * (pinch ? 0.01 : 0.0015));
}

// CSS screen scale at the camera target plane. CSS px are 1/96 inch; a physical
// monitor's pixel density is not available to a web page. Never snap the reading to a preset.
const CSS_METRE = 0.0254 / 96;
export function drawingScale(span, viewportPx) {
  return `1:${Math.round(span / Math.max(1, viewportPx) / CSS_METRE)}`;
}

export function scaleSpan(value, viewportPx) {
  const match = String(value).trim().match(/^(?:1\s*:\s*)?(\d+(?:\.\d+)?)$/);
  const denominator = match ? Number(match[1]) : NaN;
  const span = denominator * CSS_METRE * viewportPx;
  if (!Number.isFinite(span) || viewportPx <= 0 || span < VIEW_LIMITS.min || span > VIEW_LIMITS.max) {
    return { error: '현재 화면에서 사용할 수 있는 축척을 입력하세요.',
      min: Math.ceil(VIEW_LIMITS.min / (CSS_METRE * viewportPx)),
      max: Math.floor(VIEW_LIMITS.max / (CSS_METRE * viewportPx)) };
  }
  return { span };
}

// A bar in screen pixels is also valid when browser zoom changes the CSS pixel size.
export function scaleBar(span, viewportPx) {
  const target = span / Math.max(1, viewportPx) * 80;
  const power = 10 ** Math.floor(Math.log10(target));
  const metres = [1, 2, 5, 10].map(n => n * power).reduce((a, b) => Math.abs(b - target) < Math.abs(a - target) ? b : a);
  return { metres, pixels: metres / span * viewportPx };
}

export function lerpView(a, b, k) {
  const dt = ((b.turn - a.turn + 540) % 360) - 180;
  return {
    x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, span: a.span + (b.span - a.span) * k,
    tilt: a.tilt + (b.tilt - a.tilt) * k, turn: a.turn + dt * k, z: (a.z || 0) + ((b.z || 0) - (a.z || 0)) * k,
  };
}

// ------------------------------------------------------------------ the site and papers

// The site's bounds; without site facts, a 60 m square around 0, 0 so the table still works.
export function siteBounds(site) {
  const b = site?.plan?.bounds;
  if (!b) return { minX: -30, minY: -30, maxX: 30, maxY: 30 };
  return { minX: b.min_x, minY: b.min_y, maxX: b.max_x, maxY: b.max_y };
}

// Where a tracing sheet lies when it covers the site.
export function traceHome(bounds) {
  return {
    x: (bounds.minX + bounds.maxX) / 2,
    y: (bounds.minY + bounds.maxY) / 2,
    w: (bounds.maxX - bounds.minX + TRACE_MARGIN * 2) / PX,
    h: (bounds.maxY - bounds.minY + TRACE_MARGIN * 2) / PX,
  };
}

export function isOverlaid(paper, home) {
  return paper.kind === 'tracing' && Math.hypot(paper.x - home.x, paper.y - home.y) < 0.01;
}

// A block's footprint on the table: blocks stand in the site's frame (u along its long side),
// each turned by its own `a` (degrees, counter-clockwise; the rotate tool) about its middle.
export function blockCorners(frame, b) {
  const f = frame || { x: 0, y: 0, angle: 0 };
  const c = Math.cos(f.angle);
  const s = Math.sin(f.angle);
  const ca = Math.cos(rad(b.a || 0));
  const sa = Math.sin(rad(b.a || 0));
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([su, sv]) => {
    const lu = (su * b.w) / 2;
    const lv = (sv * b.d) / 2;
    const u = b.u + lu * ca - lv * sa;
    const v = b.v + lu * sa + lv * ca;
    return [f.x + u * c - v * s, f.y + u * s + v * c];
  });
}

// A table point (x, y) in the site's frame (u, v).
export function toFrame(frame, x, y) {
  const f = frame || { x: 0, y: 0, angle: 0 };
  const { du, dv } = frameDelta(f, x - f.x, y - f.y);
  return { u: du, v: dv };
}

// ------------------------------------------------------------------ blocks and the gumball
// Each building (block, 동) of a scheme is picked and edited on its own, as geometry in Rhino
// (2026-11-02 지훈). A picked block is named `paperId#index`.
export const blockKey = (id, index) => `${id}#${index}`;
export function parseBlockKey(key) {
  const at = key.lastIndexOf('#');
  return { id: key.slice(0, at), index: Number(key.slice(at + 1)) };
}

// The picked blocks still on the table, grouped by scheme: [{ paper, indices }].
export function pickedBlocks(papers, keys) {
  const out = [];
  for (const key of keys) {
    const { id, index } = parseBlockKey(key);
    const paper = papers.find((p) => p.id === id && p.kind === 'mass');
    if (!paper?.blocks?.[index]) continue;
    let group = out.find((g) => g.paper === paper);
    if (!group) out.push((group = { paper, indices: [] }));
    group.indices.push(index);
  }
  return out;
}

// The gumball on the picked blocks, as in Rhino: arrows along the site's u (red) and v (green)
// and a square in the middle move them on the ground; the blue arrow raises or lowers them a
// floor at a time; the small squares on the u and v arrows widen or narrow them about their
// middles. Blocks stand in the site's frame, so a move on the table becomes a move in u and v.
export const GUMBALL_PX = 72; // arrow length on the screen
export const GUMBALL_SCALE_PX = 44; // where the size squares sit on the arrows

// A move (dx, dy) on the table as a move along the site's u and v.
export function frameDelta(frame, dx, dy) {
  const a = frame?.angle || 0;
  return { du: dx * Math.cos(a) + dy * Math.sin(a), dv: -dx * Math.sin(a) + dy * Math.cos(a) };
}

// The blocks at `indices` moved by (du, dv), widened by dw and dd (metres, in steps of 10 cm,
// never under 1 m) and raised by df floors (whole floors, 1 to 200); the others as they were.
export function editBlocks(blocks, indices, { du = 0, dv = 0, dw = 0, dd = 0, df = 0 } = {}) {
  const step = (n) => Math.round(n * 10) / 10;
  const cm = (n) => Math.round(n * 100) / 100;
  return blocks.map((b, i) => (indices.includes(i) ? {
    ...b,
    u: cm(b.u + step(du)),
    v: cm(b.v + step(dv)),
    w: Math.max(1, cm(b.w + step(dw))),
    d: Math.max(1, cm(b.d + step(dd))),
    floors: Math.min(200, Math.max(1, b.floors + Math.round(df))),
  } : b));
}

// Metres along an arrow for a pointer move (dx, dy) in pixels, given where one metre along it
// goes on the screen (sx, sy). An arrow seen end-on (shorter than half a pixel) does not move.
export function axisDrag([sx, sy], dx, dy) {
  const len2 = sx * sx + sy * sy;
  return len2 < 0.25 ? 0 : (dx * sx + dy * sy) / len2;
}

// ------------------------------------------------------------------ SketchUp's tools on blocks
// The basic tools of SketchUp (2026-11-02 지훈), on blocks: rectangle, push/pull, move (and copy),
// rotate, scale, eraser and the tape measure. What a drag does to the blocks is worked out here.
const cm2 = (n) => Math.round(n * 100) / 100;

// Screen-space tolerance stays usable at every zoom. Return real 3D coordinates, not
// the flattened display coordinates. Perspective interpolation uses the clip-space w.
export function snapTape(pointer, segments, project, radius = 10) {
  const shown = segments.map(([a, b]) => ({ a, b, pa: project(a), pb: project(b) }))
    .filter(({ pa, pb }) => pa && pb);
  let best = null;
  for (const { a, b, pa, pb } of shown) {
    for (const [point, screen] of [[a, pa], [b, pb]]) {
      const distance = Math.hypot(pointer.x - screen.x, pointer.y - screen.y);
      if (distance <= radius && (!best || distance < best.distance)) best = { point, screen, distance, type: '꼭짓점' };
    }
  }
  if (best) return best;
  for (const { a, b, pa, pb } of shown) {
    const dx = pb.x - pa.x, dy = pb.y - pa.y;
    const length = dx * dx + dy * dy;
    if (!length) continue;
    const t = Math.max(0, Math.min(1, ((pointer.x - pa.x) * dx + (pointer.y - pa.y) * dy) / length));
    const screen = { x: pa.x + t * dx, y: pa.y + t * dy };
    const distance = Math.hypot(pointer.x - screen.x, pointer.y - screen.y);
    if (distance > radius || (best && distance >= best.distance)) continue;
    const u = t * (pa.w || 1) / ((1 - t) * (pb.w || 1) + t * (pa.w || 1));
    const point = { x: a.x + u * (b.x - a.x), y: a.y + u * (b.y - a.y), z: (a.z || 0) + u * ((b.z || 0) - (a.z || 0)) };
    best = { point, screen, distance, type: '모서리·선' };
  }
  return best;
}
const step10 = (n) => Math.round(n * 10) / 10;

// A new block from a rectangle dragged on the table between p0 and p1 (table points), lying
// square to the site (u, v), one floor high as a face in SketchUp before it is pulled up.
// null when either side is under 1 m.
export function rectBlock(frame, p0, p1, floors = 1) {
  const a = toFrame(frame, p0.x, p0.y);
  const b = toFrame(frame, p1.x, p1.y);
  const w = step10(Math.abs(b.u - a.u));
  const d = step10(Math.abs(b.v - a.v));
  if (w < 1 || d < 1) return null;
  return { u: cm2((a.u + b.u) / 2), v: cm2((a.v + b.v) / 2), w, d, floors };
}

// Push/pull a face of a block by m metres: 'top' adds floors (m over the floor height), a side
// ('w+', 'w-', 'd+', 'd-': the face at the block's +u, −u, +v or −v, turned with it) moves
// out or in while the opposite side stays put.
export function pushBlock(b, face, m, floorHeight = 4.2) {
  if (face === 'top') return editBlocks([b], [0], { df: m / floorHeight })[0];
  return pushFaceToSize(b, face, Math.max(1, cm2(b[face[0] === 'w' ? 'w' : 'd'] + step10(m))));
}

function pushFaceToSize(b, face, size) {
  const along = face[0] === 'w' ? 'w' : 'd';
  const sign = face[1] === '+' ? 1 : -1;
  const shift = (sign * (size - b[along])) / 2; // the middle follows the moved side by half
  const t = rad(b.a || 0);
  const [lu, lv] = along === 'w' ? [shift, 0] : [0, shift];
  return { ...b, [along]: size, u: cm2(b.u + lu * Math.cos(t) - lv * Math.sin(t)), v: cm2(b.v + lu * Math.sin(t) + lv * Math.cos(t)) };
}

// Copies of the blocks at `indices`, moved by (du, dv), added after the others; `indices` of the result are the copies.
export function copyBlocks(blocks, indices, du, dv) {
  const copies = editBlocks(indices.map((i) => blocks[i]), indices.map((_, k) => k), { du, dv });
  return { blocks: [...blocks, ...copies], indices: copies.map((_, k) => blocks.length + k) };
}

// The blocks at `indices` turned by `deg` (counter-clockwise) about the point (cu, cv) in the
// site's frame: their middles go round it and each block turns with them.
export function turnBlocks(blocks, indices, center, deg) {
  const t = rad(deg);
  const c = Math.cos(t);
  const s = Math.sin(t);
  const norm = (n) => { const r = ((n % 360) + 540) % 360 - 180; return cm2(r === -180 ? 180 : r); };
  return blocks.map((b, i) => {
    if (!indices.includes(i)) return b;
    const du = b.u - center.u;
    const dv = b.v - center.v;
    const out = { ...b, u: cm2(center.u + du * c - dv * s), v: cm2(center.v + du * s + dv * c) };
    const a = norm((b.a || 0) + deg);
    if (a) out.a = a;
    else delete out.a;
    return out;
  });
}

// The blocks at `indices` scaled by k about the point (cu, cv) in the site's frame: their
// middles spread or gather and their sizes follow (10 cm steps, never under 1 m); floors stay.
export function scaleBlocks(blocks, indices, center, k) {
  return blocks.map((b, i) => (indices.includes(i) ? {
    ...b,
    u: cm2(center.u + (b.u - center.u) * k),
    v: cm2(center.v + (b.v - center.v) * k),
    w: Math.max(1, step10(b.w * k)),
    d: Math.max(1, step10(b.d * k)),
  } : b));
}

// A click opens a number input; crossing the drag threshold keeps the existing drag workflow.
export function numericToolClick(gesture, cancelled = false) {
  return Boolean(!cancelled && gesture && !gesture.moved && !gesture.dragged && (gesture.kind === 'push'
    || (gesture.kind === 'gumball' && gesture.grip === 'scale' && gesture.numeric)));
}

const toolNumber = (value) => String(value ?? '').trim() === '' ? NaN : Number(value);

export function numericPushBlock(block, face, value) {
  const number = toolNumber(value);
  if (face === 'top') {
    if (!Number.isInteger(number) || number < 1 || number > 200) return { error: '층수는 1~200 사이 정수로 입력해 주세요.' };
    return { block: { ...block, floors: number } };
  }
  if (!['w+', 'w-', 'd+', 'd-'].includes(face)) return { error: '조절할 면을 다시 선택해 주세요.' };
  if (!Number.isFinite(number) || number < 1 || number > 1000) return { error: '길이는 1~1000m 사이 숫자로 입력해 주세요.' };
  return { block: pushFaceToSize(block, face, number) };
}

export function numericScaleBlocks(blocks, indices, center, value) {
  const k = toolNumber(value);
  if (!Number.isFinite(k) || k <= 0) return { error: '배율은 0보다 큰 숫자로 입력해 주세요. 예: 1.2' };
  if (!indices.length || indices.some((i) => !blocks[i])) return { error: '크기를 조절할 동을 다시 선택해 주세요.' };
  if (indices.some((i) => [blocks[i].w * k, blocks[i].d * k].some((size) => !Number.isFinite(size) || size < 1 || size > 1000))) {
    return { error: '조절 후 모든 동의 가로·세로가 1~1000m 안에 들어오게 배율을 입력해 주세요.' };
  }
  const result = scaleBlocks(blocks, indices, center, k);
  if (indices.some((i) => !Number.isFinite(result[i].u) || !Number.isFinite(result[i].v))) return { error: '조절 후 위치가 너무 큽니다. 배율을 줄여 주세요.' };
  return { blocks: result };
}

// An angle kept to steps (5° by default), as SketchUp's protractor snaps.
export function snapAngle(deg, step = 5) {
  return Math.round(deg / step) * step;
}

// Where the gumball stands: the middle of the picked blocks on the table, or null.
export function blocksCenter(frame, blocks) {
  const pts = blocks.flatMap((b) => blockCorners(frame, b));
  if (!pts.length) return null;
  const xs = pts.map(([x]) => x);
  const ys = pts.map(([, y]) => y);
  return { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: (Math.min(...ys) + Math.max(...ys)) / 2 };
}

// A paper's extent on the table, in metres.
export function paperBox(p) {
  const w = (p.w * PX) / 2;
  const h = (p.h * PX) / 2;
  return { x0: p.x - w, x1: p.x + w, y0: p.y - h, y1: p.y + h };
}

// The server lays new papers at 0, 0 (the site paper, the AI's papers); the screen puts them
// beside the site instead. A paper exactly at 0, 0 has never been placed, except a tracing
// sheet, whose place over the site is the middle of the site: 0, 0.
export function unplaced(paper) {
  return paper.kind !== 'tracing' && paper.x === 0 && paper.y === 0;
}

// A free spot east of the site and every paper, top-aligned with the site.
export function freeSpot(papers, bounds, w, h) {
  const east = Math.max(bounds.maxX, ...papers.filter((p) => !unplaced(p)).map((p) => paperBox(p).x1));
  return { x: east + 4 + (w * PX) / 2, y: bounds.maxY - (h * PX) / 2 };
}

// Where to put each unplaced paper: the site paper west of the site, the rest east of it.
export function placeUnplaced(papers, bounds) {
  const placed = papers.filter((p) => !unplaced(p));
  const moves = [];
  for (const p of papers) {
    if (!unplaced(p)) continue;
    const spot = p.kind === 'site'
      ? { x: bounds.minX - 6 - (p.w * PX) / 2, y: bounds.maxY - (p.h * PX) / 2 }
      : freeSpot(placed, bounds, p.w, p.h);
    const moved = { ...p, ...spot };
    placed.push(moved);
    moves.push({ id: p.id, x: spot.x, y: spot.y });
  }
  return moves;
}

// The view that shows the site and every paper.
export function fitView(papers, bounds, aspect) {
  const boxes = papers.filter((p) => !unplaced(p)).map(paperBox);
  const x0 = Math.min(bounds.minX, ...boxes.map((b) => b.x0));
  const x1 = Math.max(bounds.maxX, ...boxes.map((b) => b.x1));
  const y0 = Math.min(bounds.minY, ...boxes.map((b) => b.y0));
  const y1 = Math.max(bounds.maxY, ...boxes.map((b) => b.y1));
  const span = Math.max(y1 - y0, (x1 - x0) / Math.max(0.2, aspect)) * 1.12;
  return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, span: Math.min(VIEW_LIMITS.max, Math.max(VIEW_LIMITS.min, span)), tilt: 0, turn: 0, z: 0 };
}

// ------------------------------------------------------------------ pins in 3D
// Lying papers can't be read once the table leans and they hide the masses, so in 3D each
// paper folds into a small upright pin at its place; a pin opens the paper as a card beside it.

export const folded = (tilt) => tilt >= FOLD_TILT;

// Papers the designer folded into their pins, so they stay pins in plan too (2026-10-28):
// ids. A tracing laid over the site never folds (its lines are the drawing).
export function foldedInPlan(papers, home) {
  return papers.filter((p) => p.folded && !isOverlaid(p, home)).map((p) => p.id);
}

// Papers that get a pin. A tracing sheet on the site has none: its lines lie on the ground.
export function pinnedPapers(papers, home) {
  return papers.filter((p) => !isOverlaid(p, home));
}

// Where the card for a pin opens (px in the table): beside the pin `{x, y, w}` (its middle and
// width), to the right if it fits, else to the left, and inside `box` {left, top, right, bottom},
// the table less its control panels.
export function peekSpot(pin, size, box, gap = 12) {
  const clamp = (n, lo, hi) => Math.max(lo, Math.min(n, hi));
  let x = pin.x + pin.w / 2 + gap;
  if (x + size.w > box.right) x = pin.x - pin.w / 2 - gap - size.w;
  return {
    x: Math.max(box.left, clamp(x, box.left, box.right - size.w)),
    y: Math.max(box.top, clamp(pin.y - size.h / 2, box.top, box.bottom - size.h)),
  };
}

// ------------------------------------------------------------------ names and words

// The short name a chip shows (board.paper_name on the server says the same).
export function paperName(paper) {
  if (!paper) return '';
  if (paper.kind === 'site') return '대지';
  if (paper.kind === 'note') {
    const text = String(paper.text || '').split(/\s+/).filter(Boolean).join(' ');
    return text ? `메모: ${text.slice(0, 20)}${text.length > 20 ? '…' : ''}` : '메모';
  }
  if (paper.kind === 'mass') return paper.title || '매스안';
  if (paper.kind === 'tracing') return paper.title || '트레이싱지';
  if (paper.kind === 'expert') return `${paper.title || paper.agent} 결과`;
  if (paper.kind === 'photo') return paper.title || '사진';
  return paper.title || paper.kind;
}

// An expert result's preview on its paper as plain lines: the "# Name" title goes (the paper
// has its own), "## Facts" reads "[사실]", list and emphasis marks are dropped.
export function resultPreview(text, maxLines = Infinity) {
  const out = [];
  for (const raw of String(text || '').split('\n')) {
    if (out.length >= maxLines) break;
    const line = raw.trim();
    if (!line || /^#\s/.test(line)) continue;
    const heading = line.match(/^#{2,6}\s+(.+)$/);
    if (heading) {
      const name = heading[1].replace(/[*_`]/g, '').trim();
      out.push(`[${SECTION_LABELS[name] || name}]`);
    } else {
      out.push(line.replace(/^(?:[-*+]|\d+[.)])\s+/, '· ').replace(/\*\*|__|`/g, ''));
    }
  }
  return out.join('\n');
}

export const KIND_LABELS = { site: '대지', mass: '매스안', note: '메모', tracing: '트레이싱지', expert: '전문가 결과', photo: '사진' };

// Who made an AI paper: "Conductor 제안", "법규 검토자 결과"; '' for the designer's own.
export function originLabel(paper, experts = []) {
  if (!paper?.origin) return '';
  if (paper.origin === 'conductor') return 'Conductor 제안';
  const expert = experts.find((e) => e.id === paper.origin);
  return `${expert?.name || paper.origin} 결과`;
}

// Coverage and FAR from the server's figures, or why they are missing.
export function figureLines(f) {
  if (!f) return [];
  const lines = [`건축면적 ${fmt(f.footprint_m2, 1)}㎡ · 연면적 ${fmt(f.floor_area_m2, 1)}㎡ · 최고 ${fmt(f.height_m, 1)}m`];
  lines.push(f.coverage_pct == null
    ? '건폐율·용적률 미확인 (대지 면적을 모름)'
    : `건폐율 ${fmt(f.coverage_pct, 1)}% · 용적률 ${fmt(f.far_pct, 1)}%`);
  return lines;
}

// ------------------------------------------------------------------ the scheme form

// Rows typed into the scheme form → a mass paper's fields, or {error}. The server checks
// again; this only catches typing slips before sending.
export function readScheme({ title = '', floorHeight = '4.2', rows = [] }) {
  const number = (value) => (String(value).trim() === '' ? NaN : Number(value));
  const blocks = [];
  for (const [i, row] of rows.entries()) {
    const at = `${i + 1}동`;
    const w = number(row.w);
    const d = number(row.d);
    const floors = number(row.floors);
    const u = String(row.u ?? '').trim() === '' ? 0 : number(row.u);
    const v = String(row.v ?? '').trim() === '' ? 0 : number(row.v);
    const a = String(row.a ?? '').trim() === '' ? 0 : number(row.a);
    if (!(w > 0 && w <= 1000) || !(d > 0 && d <= 1000)) return { error: `${at}: 가로·세로는 0보다 크고 1000m 이하로 적어 주세요.` };
    if (!Number.isInteger(floors) || floors < 1 || floors > 200) return { error: `${at}: 층수는 1~200 사이 정수로 적어 주세요.` };
    if (!Number.isFinite(u) || !Number.isFinite(v)) return { error: `${at}: 위치는 숫자로 적어 주세요.` };
    if (!Number.isFinite(a) || Math.abs(a) > 360) return { error: `${at}: 회전은 -360~360도 사이 숫자로 적어 주세요.` };
    blocks.push(a ? { u, v, w, d, floors, a } : { u, v, w, d, floors });
  }
  if (!blocks.length) return { error: '동을 하나 이상 넣어 주세요.' };
  if (blocks.length > MAX_BLOCKS) return { error: `동은 ${MAX_BLOCKS}개까지입니다.` };
  const floorHeightValue = number(floorHeight);
  if (!(floorHeightValue > 0 && floorHeightValue <= 20)) return { error: '층고는 0보다 크고 20m 이하로 적어 주세요.' };
  return { title: String(title).trim().slice(0, 120), floor_height: floorHeightValue, blocks };
}

// A mass paper → rows for the form.
export function schemeRows(paper) {
  return (paper?.blocks || [{ u: 0, v: 0, w: 30, d: 20, floors: 4 }]).map((b) => ({
    u: String(b.u), v: String(b.v), w: String(b.w), d: String(b.d), floors: String(b.floors), a: String(b.a || 0),
  }));
}

// ------------------------------------------------------------------ selection

// Paper ids still on the table or in the AI section, in the order they were picked.
export function keepSelected(selected, board) {
  const ids = new Set([...(board?.papers || []), ...(board?.tray || [])].map((p) => p.id));
  return [...selected].filter((id) => ids.has(id)).slice(0, MAX_CONTEXT);
}

// Shift+click toggles a paper in the selection; a plain click selects it alone.
export function toggleSelected(selected, id, add) {
  if (!add) return [id];
  return selected.includes(id) ? selected.filter((x) => x !== id) : [...selected, id].slice(-MAX_CONTEXT);
}

// Box selection, as in Rhino (2026-11-02 지훈): a left drag on empty table draws a box from
// `from` to `to` (screen points). Dragged left to right it picks what lies wholly inside (window),
// right to left what it touches (crossing). Shift (`add`) adds to the selection, Ctrl (`remove`)
// takes away, and otherwise the box replaces it. `items`: screen rectangles {id, left, top, right, bottom};
// one id may have several, and any of them counts. Papers are picked at most MAX_CONTEXT at a
// time (one message carries them); blocks pass `limit: Infinity`.
export function boxMode(from, to) {
  return to.x < from.x ? 'crossing' : 'window';
}
export function boxPick(selected, from, to, items, { add = false, remove = false, limit = MAX_CONTEXT } = {}) {
  const b = { left: Math.min(from.x, to.x), right: Math.max(from.x, to.x), top: Math.min(from.y, to.y), bottom: Math.max(from.y, to.y) };
  const crossing = boxMode(from, to) === 'crossing';
  const hit = items.filter((r) => (crossing
    ? r.left <= b.right && r.right >= b.left && r.top <= b.bottom && r.bottom >= b.top
    : r.left >= b.left && r.right <= b.right && r.top >= b.top && r.bottom <= b.bottom)).map((r) => r.id)
    .filter((id, i, all) => all.indexOf(id) === i);
  if (remove) return selected.filter((id) => !hit.includes(id));
  const kept = add ? selected.filter((id) => !hit.includes(id)) : [];
  return [...kept, ...hit].slice(-limit);
}

// For the chips above a composer: the names of the picked papers.
export function pickedNames(ids, board) {
  const all = [...(board?.papers || []), ...(board?.tray || [])];
  return ids.map((id) => ({ id, name: paperName(all.find((p) => p.id === id)) || id }));
}

// The masses on the table (not in the AI section), for "매스안 선택".
export function massIds(board) {
  return (board?.papers || []).filter((p) => p.kind === 'mass').map((p) => p.id);
}

// Two or more picked schemes: the selection bar offers to ask for a comparison.
export function canCompare(ids, board) {
  const all = [...(board?.papers || []), ...(board?.tray || [])];
  return ids.filter((id) => all.find((p) => p.id === id)?.kind === 'mass').length >= 2;
}

export const COMPARE_QUESTION = '선택한 두 매스안의 배치와 건폐율·용적률을 비교하고, 검토할 차이점을 알려줘.';

// A question prepared from the selection bar goes under what is already typed.
export function addQuestion(draft, text) {
  if (!text) return draft;
  return String(draft || '').trim() ? `${draft}\n${text}` : text;
}

// ------------------------------------------------------------------ undo and redo
// The table saves each edit through the API, so undoing an edit sends its inverse. One step is
// the edits of one gesture (a drag of several papers is one step):
//   {op: 'update', id, before, after}  fields before and after
//   {op: 'add', paper} / {op: 'remove', paper}  the whole paper
// Only the designer's kinds come back after a delete (POST /papers takes mass, note, tracing,
// and a photo whose file the server still keeps).

export const HISTORY_LIMIT = 100;
export const UNDOABLE_KINDS = ['mass', 'note', 'tracing', 'photo'];

export const createHistory = () => ({ past: [], future: [] });

const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);

// Only the fields that changed, before and after.
export function changedFields(before, after) {
  const was = {};
  const now = {};
  for (const key of Object.keys(after)) {
    if (same(before[key], after[key])) continue;
    was[key] = before[key];
    now[key] = after[key];
  }
  return { before: was, after: now };
}

function worthKeeping(edit) {
  if (edit.op === 'update') return Object.keys(edit.after || {}).length > 0 && !same(edit.before, edit.after);
  return UNDOABLE_KINDS.includes(edit.paper?.kind);
}

export function recordStep(history, edits) {
  const step = edits.filter(worthKeeping);
  if (!step.length) return history;
  return { past: [...history.past, step].slice(-HISTORY_LIMIT), future: [] };
}

export function invertStep(step) {
  return [...step].reverse().map((e) => {
    if (e.op === 'update') return { op: 'update', id: e.id, before: e.after, after: e.before };
    return { op: e.op === 'add' ? 'remove' : 'add', paper: e.paper };
  });
}

// {history, step}: the edits to send now (null when there is nothing to undo or redo).
export function undoStep(history) {
  if (!history.past.length) return { history, step: null };
  const last = history.past[history.past.length - 1];
  return { history: { past: history.past.slice(0, -1), future: [last, ...history.future] }, step: invertStep(last) };
}

export function redoStep(history) {
  if (!history.future.length) return { history, step: null };
  const next = history.future[0];
  return { history: { past: [...history.past, next].slice(-HISTORY_LIMIT), future: history.future.slice(1) }, step: next };
}

// ------------------------------------------------------------------ the plan in a paper's card

// A small site plan for the card of the site or a mass (SVG, y down): lot outlines, the
// scheme's blocks with their floors, a scale bar. null when there is nothing to draw.
export function planDrawing(site, paper = null) {
  const lots = (site?.plan?.parcels || []).flatMap((parcel) => parcel.rings || []);
  const frame = site?.plan?.frame || { x: 0, y: 0, angle: 0 };
  const blocks = paper?.kind === 'mass'
    ? (paper.blocks || []).map((b) => ({ corners: blockCorners(frame, b), floors: b.floors }))
    : [];
  const points = [...lots.flat(), ...blocks.flatMap((b) => b.corners)];
  if (!points.length) return null;
  const xs = points.map(([x]) => x);
  const ys = points.map(([, y]) => y);
  const pad = 6;
  const x0 = Math.min(...xs) - pad;
  const x1 = Math.max(...xs) + pad;
  const y0 = Math.min(...ys) - pad;
  const y1 = Math.max(...ys) + pad + 8; // room for the scale bar
  const path = (ring) => `${ring.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ')} Z`;
  const width = x1 - x0;
  const bar = [5, 10, 20, 50, 100, 200].reduce((a, b) => (Math.abs(b - width / 4) < Math.abs(a - width / 4) ? b : a));
  return {
    viewBox: [x0, -y1, width, y1 - y0].map((n) => Number(n.toFixed(2))).join(' '),
    lots: lots.map(path),
    blocks: blocks.map((b) => {
      const cx = b.corners.reduce((s, [x]) => s + x, 0) / 4;
      const cy = b.corners.reduce((s, [, y]) => s + y, 0) / 4;
      return { d: path(b.corners), floors: b.floors, x: Number(cx.toFixed(2)), y: Number((-cy).toFixed(2)) };
    }),
    scale: { x: Number((x0 + 3).toFixed(2)), y: Number((-y0 - 3).toFixed(2)), length: bar, label: `${bar}m` },
    size: Math.max(width, y1 - y0),
  };
}

// ------------------------------------------------------------------ photos
// A photo (a site photo, a hand sketch, a reference) laid on the table as a paper. The server
// takes PNG, JPEG, GIF, WebP and PDF up to 20 MB (board.MAX_PHOTO_BYTES); anything else the browser
// can open (an iPhone HEIC in Safari) or a very large picture is redrawn as a smaller JPEG first.

export const PHOTO_TYPES = ['image/png', 'image/jpeg', 'image/gif', 'image/webp'];
export const MAX_PHOTO_BYTES = 20 * 1024 * 1024;
export const PHOTO_KEEP_BYTES = 8 * 1024 * 1024; // larger pictures are redrawn smaller
export const PHOTO_MAX_SIDE = 2560; // px of the longest side after redrawing
export const PHOTO_SIZES = { small: 200, medium: 300, large: 500 }; // px of the paper's longest side
export const MAX_PHOTOS_AT_ONCE = 10;

// 'keep' (upload the file as it is) or 'shrink' (redraw it as a JPEG of at most PHOTO_MAX_SIDE).
// A GIF is kept while the server takes it, so an animation stays.
export function photoPlan(type, bytes, width, height) {
  if (!PHOTO_TYPES.includes(type)) return 'shrink';
  if (type === 'image/gif') return bytes <= MAX_PHOTO_BYTES ? 'keep' : 'shrink';
  return bytes <= PHOTO_KEEP_BYTES && Math.max(width, height) <= PHOTO_MAX_SIDE * 1.6 ? 'keep' : 'shrink';
}

// The size of a redrawn picture: the longest side at most PHOTO_MAX_SIDE, never enlarged.
export function shrunkSize(width, height, side = PHOTO_MAX_SIDE) {
  const k = Math.min(1, side / Math.max(width, height, 1));
  return { width: Math.max(1, Math.round(width * k)), height: Math.max(1, Math.round(height * k)) };
}

// The paper for a picture of width × height: its longest side `longest` px, the picture's shape
// kept (a very long panorama still gets a paper at least 40 px across).
export function photoPaperSize(width, height, longest = PHOTO_SIZES.medium) {
  const ratio = width > 0 && height > 0 ? width / height : 4 / 3;
  const w = ratio >= 1 ? longest : Math.max(40, Math.round(longest * ratio));
  const h = ratio >= 1 ? Math.max(40, Math.round(longest / ratio)) : longest;
  return { w, h };
}

// The canvas size (device pixels) for a PDF page on a paper w × h CSS px, shown at `zoom` screen
// px per paper px on a screen of `dpr`: as sharp as the screen, but never past `side` px on its
// longest side or `area` px in all (a canvas that large is slow and may not draw at all).
export const PDF_MAX_SIDE = 4096;
export const PDF_MAX_AREA = 16e6;
export function pdfCanvasSize(w, h, zoom, dpr = 1, side = PDF_MAX_SIDE, area = PDF_MAX_AREA) {
  const want = Math.max(0.05, Number(zoom) || 1) * Math.max(1, Number(dpr) || 1);
  const k = Math.min(want, side / Math.max(w, h, 1), Math.sqrt(area / Math.max(1, w * h)));
  return { width: Math.max(1, Math.round(w * k)), height: Math.max(1, Math.round(h * k)) };
}

// Whether a page drawn at `have` should be drawn again for `want`: when the paper is shown much
// sharper than it was drawn (it would blur), or much smaller (it wastes memory).
export function pdfNeedsRedraw(have, want) {
  if (!have?.width) return true;
  return want.width > have.width * 1.15 || want.width < have.width * 0.4;
}

// The paper's title from the file name: without its extension, at most 120 characters, and ''
// for the names a pasted screenshot gets ("image.png").
export function photoTitle(fileName) {
  const base = String(fileName || '').replace(/\.[A-Za-z0-9]{1,5}$/, '').trim();
  if (!base || /^(image|unknown|blob|clipboard)$/i.test(base)) return '';
  return base.slice(0, 120);
}

// A PDF (a drawing exported from CAD) goes up as it is and lies on the table as one page, drawn
// from the PDF at the size it is shown, so its lines stay sharp however large the paper grows.
export function isPdfFile(file) {
  return file?.type === 'application/pdf' || (!file?.type && /\.pdf$/i.test(String(file?.name || '')));
}

export function isPdfPaper(p) {
  return p?.kind === 'photo' && /\.pdf$/i.test(String(p.file || ''));
}

// Which of the dropped or pasted files are pictures or PDFs (by type, or by extension when the
// browser gave no type), at most MAX_PHOTOS_AT_ONCE; `skipped` counts the rest.
export function pickPhotoFiles(files) {
  const all = [...(files || [])];
  const pictures = all.filter((f) => String(f.type || '').startsWith('image/') || isPdfFile(f)
    || (!f.type && /\.(png|jpe?g|gif|webp|heic|heif|avif|bmp)$/i.test(String(f.name || ''))));
  const taken = pictures.slice(0, MAX_PHOTOS_AT_ONCE);
  return { files: taken, skipped: all.length - taken.length };
}

// ------------------------------------------------------------------ the site's surroundings
// GET .../site/context (docs/board-api.md): the ground as heights on a grid around the site
// (rows south to north, z = 0 at the site's middle), what the ground is at each point, nearby
// buildings and the contour lines the screen draws at an interval the designer picks.

export const CONTOUR_STEPS = [1, 2, 5];
export const GROUND_COLORS = { g: 0xd9d1bf, r: 0xb3b3b0, s: 0xe6e1d6, w: 0x9cc7d9 };
export const GROUND_NAMES = { g: '대지', r: '도로', s: '인도', w: '수계' };

// The note on where the surroundings come from starts folded on a narrow table (under this many
// px wide), so it does not cover the drawing; the designer can open it.
export const NOTE_OPEN_WIDTH = 900;
export function noteStartsOpen(width) {
  return Number(width) >= NOTE_OPEN_WIDTH;
}

// The legend under the surroundings: only the ground kinds the grid has and the building kinds
// that are drawn ([kind, name]; kind is a ground letter, 'guess' or 'unknown'). Without a ground
// grid the ground is drawn flat as 대지.
export function aroundLegend(context) {
  if (!context) return [];
  const classes = context.terrain?.classes;
  const ground = Object.entries(GROUND_NAMES).filter(([k]) => (classes ? classes.includes(k) : k === 'g'));
  const c = context.counts || {};
  const guess = (context.buildings || []).some((b) => ESTIMATED.has(b.height_source));
  return [...ground, ...(guess ? [['guess', '추정 높이']] : []),
    ...(c.unknown || context.unknown_buildings?.length ? [['unknown', '높이 미확인(바닥선)']] : [])];
}

// The point at grid column i, row j of the ground.
export function groundPoint(terrain, i, j) {
  return [terrain.min + i * terrain.step, terrain.min + j * terrain.step, terrain.z[j * terrain.n + i]];
}

// Where a block of a mass stands (z of its floor), the same as board_export.mass_base(outline,
// ground) and with its argument order: the lowest ground under the footprint, sampled along
// the edges every half grid step and at every grid point inside; 0 without the ground or for a
// footprint entirely off it. `terrain` is the context's grid {min, step, n, z}.
export function massBase(outline, terrain) {
  if (!terrain || !outline?.length) return 0;
  const { min, step, n, z } = terrain;
  let low = Infinity;
  function sample(x, y) {
    const u = (x - min) / step, v = (y - min) / step;
    if (u < 0 || v < 0 || u > n - 1 || v > n - 1) return;
    const i = Math.min(Math.floor(u), n - 2), j = Math.min(Math.floor(v), n - 2);
    const a = u - i, b = v - j, k = j * n + i;
    const south = (1 - a) * z[k] + a * z[k + 1];
    const north = (1 - a) * z[k + n] + a * z[k + n + 1];
    low = Math.min(low, (1 - b) * south + b * north);
  }
  const edges = outline.map((p, i) => [p, outline[(i + 1) % outline.length]]);
  for (const [[x, y], [ex, ey]] of edges) {
    const count = Math.max(1, Math.ceil(2 * Math.hypot(ex - x, ey - y) / step));
    for (let s = 0; s < count; s++) sample(x + (ex - x) * s / count, y + (ey - y) * s / count);
  }
  const gridRange = axis => {
    const coords = outline.map(point => (point[axis] - min) / step);
    return [Math.max(0, Math.ceil(Math.min(...coords))), Math.min(n - 1, Math.floor(Math.max(...coords)))];
  };
  const [west, east] = gridRange(0), [south, north] = gridRange(1);
  for (let j = south; j <= north; j++) {
    for (let i = west; i <= east; i++) {
      const x = min + i * step, y = min + j * step;
      let inside = false;
      for (const [[ax, ay], [bx, by]] of edges) {
        if ((ay > y) !== (by > y) && x < ax + (y - ay) * (bx - ax) / (by - ay)) inside = !inside;
      }
      if (inside) low = Math.min(low, z[j * n + i]);
    }
  }
  return Number.isFinite(low) ? Number(low.toFixed(2)) : 0;
}

// Contour lines through the ground grid every `interval` m of height (marching squares): one
// entry per height, {z, index, segments: [[x1, y1, x2, y2], ...]}; every fifth height is an
// index contour. The very top height (which only touches the grid) is skipped.
// The range the surroundings are made in (GET/PUT .../site/context/range): the size as a radius
// (a square is ±radius) and the shape. A round range marks the ground outside it OUTSIDE.
export const RANGE_SIZES = [
  { key: 'small', label: '작게 · 반경 100m', radius: 100 },
  { key: 'medium', label: '중간 · 반경 200m', radius: 200 },
  { key: 'large', label: '크게 · 반경 300m', radius: 300 },
];
export const RANGE_SHAPES = [{ key: 'square', label: '정사각형' }, { key: 'circle', label: '원' }];
export const OUTSIDE = 'x';

// Whether the ground cell from point (i, j) to (i + 1, j + 1) is drawn: none of its corners outside.
export function cellOpen(terrain, i, j) {
  const c = terrain?.classes;
  if (!c) return true;
  const n = terrain.n;
  return c[j * n + i] !== OUTSIDE && c[j * n + i + 1] !== OUTSIDE && c[(j + 1) * n + i] !== OUTSIDE && c[(j + 1) * n + i + 1] !== OUTSIDE;
}

// The triangles of the ground mesh (three.js PlaneGeometry's vertex order: rows from the top,
// north) without the cells that have a corner outside the range.
export function terrainFaces(terrain) {
  const n = terrain.n;
  const out = [];
  for (let iy = 0; iy < n - 1; iy += 1) {
    const j = n - 2 - iy; // the cell's southern row of points
    for (let ix = 0; ix < n - 1; ix += 1) {
      if (!cellOpen(terrain, ix, j)) continue;
      const a = ix + n * iy, b = ix + n * (iy + 1), c = ix + 1 + n * (iy + 1), d = ix + 1 + n * iy;
      out.push(a, b, d, b, c, d);
    }
  }
  return out;
}

export function contourLines(terrain, interval) {
  if (!terrain || !terrain.n || !(interval > 0)) return [];
  const { n, z } = terrain;
  let lo = Infinity, hi = -Infinity;
  for (const v of z) { if (v < lo) lo = v; if (v > hi) hi = v; }
  const out = [];
  for (let level = Math.ceil(lo / interval) * interval; level < hi; level += interval) {
    const segments = [];
    const cut = (i1, j1, i2, j2) => {
      const a = z[j1 * n + i1], b = z[j2 * n + i2];
      const t = (level - a) / (b - a);
      return [terrain.min + (i1 + (i2 - i1) * t) * terrain.step, terrain.min + (j1 + (j2 - j1) * t) * terrain.step];
    };
    for (let j = 0; j < n - 1; j += 1) {
      for (let i = 0; i < n - 1; i += 1) {
        if (!cellOpen(terrain, i, j)) continue;
        const corners = [[i, j], [i + 1, j], [i + 1, j + 1], [i, j + 1]];
        const above = corners.map(([ci, cj]) => z[cj * n + ci] >= level);
        if (above.every(Boolean) || !above.some(Boolean)) continue;
        const points = [];
        for (let k = 0; k < 4; k += 1) {
          const [a, b] = [corners[k], corners[(k + 1) % 4]];
          if (above[k] !== above[(k + 1) % 4]) points.push(cut(a[0], a[1], b[0], b[1]));
        }
        for (let k = 0; k + 1 < points.length; k += 2) segments.push([...points[k], ...points[k + 1]]);
      }
    }
    const rounded = Math.round(level * 1000) / 1000;
    if (segments.length) out.push({ z: rounded, index: Math.abs(Math.round(rounded / (interval * 5)) * interval * 5 - rounded) < 1e-6, segments });
  }
  return out;
}

export const HEIGHT_SOURCES = {
  ledger: '건축물대장 높이', file: '건물통합정보 높이', vworld: '건축물정보 높이',
  estimate: '층수×층고 추정', api_estimate: '추정(브이월드 API 층수)', map_estimate: '추정(수치지형도 층수)',
};
const ESTIMATED = new Set(['estimate', 'api_estimate', 'map_estimate']);
export const OUTLINE_SOURCES = { file: '건물통합정보', vworld: '브이월드(화면 전용)', map: '1:5,000 수치지형도' };

// One line about a building around the site, for a click on it: its name, height and where the
// height came from, and which 건축물대장 동 sits on which outline (with the area ratio).
export function buildingInfo(b) {
  if (!b) return '';
  const parts = [b.name || '이름 없는 건물', `${Number(b.height).toFixed(1)}m`];
  if (b.floors) parts.push(`${b.floors}층`);
  parts.push(HEIGHT_SOURCES[b.height_source] || b.height_source);
  const m = b.match;
  if (m) {
    const ratio = m.ratio == null ? '' : `, 면적비 ${Number(m.ratio).toFixed(2)}`;
    parts.push(`대장 ${m.dong || '동'} ↔ ${OUTLINE_SOURCES[m.source] || m.source} 외곽선${ratio}`);
  } else {
    parts.push('대장과 짝지은 외곽선 아님');
  }
  if (b.display_only) parts.push('파일로 내보내지 않음');
  return parts.join(' · ');
}

// Whether a building's height is an estimate (drawn in its own colour, said so in the note).
export function isEstimate(building) {
  return ESTIMATED.has(building?.height_source);
}

// What the note under the surroundings says: where each part comes from (with the data's date),
// how many buildings got their height which way, and the warning that it is not a survey.
export function aroundNote(context) {
  if (!context) return [];
  const c = context.counts || {};
  const terrain = (context.terrain_sources || []).map((s) => `${s.name}${s.date ? ` (기준 ${s.date})` : ''}`);
  const lines = [
    terrain.length ? `지형: ${terrain.join(', ')}` : '지형: 이 지역 지형 자료가 없어 평지로 그렸습니다',
    `건물: ${context.building_source?.name || '브이월드 건축물정보'}${context.building_source?.date ? ` (기준 ${context.building_source.date})` : ''}`,
    `건물 높이: ${Object.entries(HEIGHT_SOURCES).filter(([k]) => c[k]).map(([k, name]) => `${name} ${c[k]}동`).join(', ') || '없음'}`
      + (c.unknown ? ` · 높이 미확인 ${c.unknown}동은 바닥선만` : ''),
    '필지·도로 필지: 브이월드 연속지적도 (화면 표시용, 저장하지 않음)',
  ];
  if (c.estimate || c.api_estimate || c.map_estimate) lines.push('추정 높이는 층수 × 층고(주거 2.9m, 업무·상업 3.8m, 그 밖 3.3m)로, 실제 높이가 아닙니다.');
  if (context.disclaimer) lines.push(context.disclaimer);
  return lines;
}

// ------------------------------------------------------------------ the idea board
// The designer's main ideas, in their order (board.ideas, saved by the server; 2026-11-05).
// The AI reads them and never changes them; an idea set aside (`off`) is not sent to it.

export const MAX_IDEA_TEXT = 600; // board.MAX_IDEA_TEXT
export const MAX_IDEA_PAPERS = 8; // board.MAX_IDEA_PAPERS

// Text taken from a conversation or a note for a new idea: each line trimmed, blank lines
// dropped, and cut to what the server keeps.
export function ideaText(text, limit = MAX_IDEA_TEXT) {
  const joined = String(text ?? '').split('\n').map((line) => line.trim()).filter(Boolean).join('\n');
  return joined.length > limit ? `${joined.slice(0, limit - 1).trimEnd()}…` : joined;
}

// The order after moving one idea up (step -1) or down (+1); the same order at either end.
export function moveIdea(ids, id, step) {
  const from = ids.indexOf(id);
  const to = from + step;
  if (from < 0 || to < 0 || to >= ids.length) return [...ids];
  const out = [...ids];
  [out[from], out[to]] = [out[to], out[from]];
  return out;
}

// The order after dragging `id` onto `target`: before it, or after it with `after`.
export function dropIdea(ids, id, target, after = false) {
  if (id === target || !ids.includes(id) || !ids.includes(target)) return [...ids];
  const out = ids.filter((x) => x !== id);
  out.splice(out.indexOf(target) + (after ? 1 : 0), 0, id);
  return out;
}

export const sameOrder = (a, b) => a.length === b.length && a.every((x, i) => x === b[i]);

// An idea's linked papers that are still on the table or in the AI section, by name.
export function ideaPapers(idea, board) {
  const all = [...(board?.papers || []), ...(board?.tray || []), ...heldPapers(board)];
  return (idea?.papers || []).flatMap((id) => {
    const paper = all.find((p) => p.id === id);
    return paper ? [{ id, name: paperName(paper) }] : [];
  });
}

// The papers an idea links after adding the picked ones (kept in order, at most MAX_IDEA_PAPERS).
export function linkPapers(current, picked) {
  return [...new Set([...(current || []), ...(picked || [])])].slice(0, MAX_IDEA_PAPERS);
}

// Picked notes with text, which "메모를 아이디어로" turns into ideas (each linked to its note).
export function pickedNotes(ids, board) {
  const all = [...(board?.papers || []), ...(board?.tray || [])];
  return ids.map((id) => all.find((p) => p.id === id))
    .filter((p) => p?.kind === 'note' && ideaText(p.text))
    .map((p) => ({ id: p.id, text: ideaText(p.text) }));
}

// The papers dragged off the table into the idea board (each held inside its idea).
export function heldPapers(board) {
  return (board?.ideas || []).map((i) => i.paper).filter((p) => p && typeof p === 'object');
}

const DOT_GLYPHS = { note: '✎', mass: '▣', tracing: '≈', expert: '◎', pdf: 'PDF', site: '◇' };

// What an idea's circle and its line in the open board show: its kind, a glyph for the circle,
// a name and a little of what it says. An idea of words shows its number.
export function ideaShape(idea, index = 0) {
  const p = idea?.paper;
  if (!p) return { kind: 'text', glyph: String(index + 1), name: '', text: idea?.text || '' };
  const kind = p.kind === 'photo' && /\.pdf$/i.test(p.file || '') ? 'pdf' : p.kind;
  const said = p.kind === 'note' || p.kind === 'expert' ? String(p.text || '').trim() : '';
  return { kind, glyph: DOT_GLYPHS[kind] || '•', name: paperName(p), text: said, photo: p.kind === 'photo' && kind !== 'pdf' };
}

// How many ideas the AI reads now (the ones not set aside).
export function ideasInPlay(board) {
  return (board?.ideas || []).filter((i) => !i.off).length;
}

// ------------------------------------------------------------------ the VWorld 3D map
// The board's masses shown inside VWorld's own WebGL 3D map (vworld-view.js), over VWorld's 3D
// buildings. VWorld's buildings are only shown there, never kept; what is kept is the list of
// buildings the designer hid, by VWorld's model id (board.hidden, PUT .../board/hidden).

export const EARTH_RADIUS = 6378137; // m: board.EARTH_RADIUS, the projection board.site_plan uses
export const MAX_HIDDEN = 300; // board.MAX_HIDDEN

// Board metres (x east, y north from the site's middle) back to [lon, lat] (board.site_plan).
export function toLonLat(origin, x, y) {
  const k = Math.PI / 180;
  const east = EARTH_RADIUS * k * Math.cos(origin.lat * k);
  const north = EARTH_RADIUS * k;
  return [origin.lon + x / east, origin.lat + y / north];
}

// What a massing scheme stands as on the map: one polygon per block, its footprint corners as
// [lon, lat] and its height (floors × the scheme's floor height), standing on the ground there.
export function massPolygons(paper, plan) {
  if (!paper || !plan?.origin) return [];
  const storey = paper.floor_height || 4.2;
  return (paper.blocks || []).map((b) => ({
    ring: blockCorners(plan.frame, b).map(([x, y]) => toLonLat(plan.origin, x, y)),
    height: Math.round(b.floors * storey * 100) / 100,
    floors: b.floors,
  }));
}

// The site's parcel boundaries as [lon, lat] rings (to find VWorld's buildings standing on it).
export function siteRings(plan) {
  if (!plan?.origin) return [];
  return (plan.parcels || []).flatMap((p) => p.rings || []).map((ring) => ring.map(([x, y]) => toLonLat(plan.origin, x, y)));
}

// The hidden list after hiding these buildings (each once, in the order hidden, at most MAX_HIDDEN).
export function hideBuildings(hidden, ids) {
  return [...new Set([...(hidden || []), ...(ids || []).filter((id) => typeof id === 'string' && id)])].slice(0, MAX_HIDDEN);
}

// The address of the VWorld 3D page for a frame (GET /api/site/map `webgl3d`): the app's own page
// with VWorld's script address after # when this PC has a VWorld key, or the Sida data server's
// page (the access key in its address) when it hasn't. After # also the site's middle (where the
// map starts) and the board's origin (`parent`, the only page the map talks to). `key` names
// the page and script, so the board loads a new page only when they change. Null without a page.
export function vworldFrame(webgl3d, origin, parent) {
  const page = typeof webgl3d?.page === 'string' ? webgl3d.page : '';
  if (!page || !origin) return null;
  const script = typeof webgl3d.script === 'string' ? webgl3d.script : '';
  const at = new URLSearchParams({ lon: String(origin.lon), lat: String(origin.lat), parent: String(parent || '') });
  if (script) at.set('script', script);
  return { src: `${page}#${at}`, key: `${page} ${script}` };
}

// How the viewer likes the VWorld map (vworld-view.js keeps it for the page, not the project):
// white: buildings as a white model, plain: the ground without the aerial photo, noNames:
// VWorld's name labels off. Anything unreadable is the default (photos and names on).
export function readLook(stored) {
  let v = null;
  try { v = JSON.parse(stored); } catch { v = null; }
  return { white: v?.white === true, plain: v?.plain === true, noNames: v?.noNames === true };
}

// The hiding steps on the VWorld map, for Ctrl+Z and Ctrl+Shift+Z: the hidden lists before
// (past), now (present) and undone (future). A new step clears what was undone; the same list
// again is no step. At most MAX_HIDE_STEPS steps back.
export const MAX_HIDE_STEPS = 50;
export function startHistory(present) {
  return { past: [], present: [...(present || [])], future: [] };
}
export function commitHistory(h, next) {
  if (sameOrder(h.present, next)) return h;
  return { past: [...h.past, h.present].slice(-MAX_HIDE_STEPS), present: [...next], future: [] };
}
export function undoHistory(h) {
  if (!h.past.length) return h;
  return { past: h.past.slice(0, -1), present: h.past.at(-1), future: [h.present, ...h.future] };
}
export function redoHistory(h) {
  if (!h.future.length) return h;
  return { past: [...h.past, h.present], present: h.future[0], future: h.future.slice(1) };
}

// What a key does on the VWorld map: 'hide' (Delete or Backspace with a building picked),
// 'cancel' (Esc with one picked), 'undo' (Ctrl+Z / ⌘Z), 'redo' (Ctrl+Shift+Z, Ctrl+Y), or ''.
export function hideKey({ key, ctrl, meta, shift }, picked) {
  const k = String(key || '').toLowerCase();
  if (ctrl || meta) {
    if (k === 'z') return shift ? 'redo' : 'undo';
    if (k === 'y') return 'redo';
    return '';
  }
  if (picked && (k === 'delete' || k === 'backspace')) return 'hide';
  if (picked && k === 'escape') return 'cancel';
  return '';
}

// ------------------------------------------------------------------ the floating idea window
// The idea board floats over the drafting table and holds to the corner it was left nearest
// (2026-11-07 지훈: "제도판 위에 한구석에 떠 있어야"), so it stays in that corner when panels
// open or close and the table changes size. `dx`, `dy` are the gaps to that corner's two edges.

export const IDEA_FLOAT = {
  corner: 'tr', dx: 76, dy: 16, width: 320, height: 440, // beside the table's view buttons (top right)
  minWidth: 240, minHeight: 180, margin: 6,
};

const fit = (value, low, high) => Math.max(low, Math.min(high, value));
const CORNERS = new Set(['tl', 'tr', 'bl', 'br']);

// A saved window state made safe to draw (anything missing or broken falls back to the default).
export function floatState(saved) {
  const s = saved && typeof saved === 'object' ? saved : {};
  const num = (v, d) => (Number.isFinite(v) && v >= 0 ? v : d);
  return {
    pinned: s.pinned === true, // kept open even without the pointer over it
    corner: CORNERS.has(s.corner) ? s.corner : IDEA_FLOAT.corner,
    dx: num(s.dx, IDEA_FLOAT.dx), dy: num(s.dy, IDEA_FLOAT.dy),
    width: Math.max(IDEA_FLOAT.minWidth, num(s.width, IDEA_FLOAT.width)),
    height: Math.max(IDEA_FLOAT.minHeight, num(s.height, IDEA_FLOAT.height)),
  };
}

// Where the window (of `size`) sits in the table area `box`: held to its corner, never larger
// than the area and never past its edges.
export function floatPlace(state, size, box) {
  const m = IDEA_FLOAT.margin;
  const width = Math.max(0, Math.min(size.width, box.width - 2 * m));
  const height = Math.max(0, Math.min(size.height, box.height - 2 * m));
  const left = state.corner.includes('l') ? state.dx : box.width - width - state.dx;
  const top = state.corner.includes('t') ? state.dy : box.height - height - state.dy;
  return {
    left: fit(left, m, Math.max(m, box.width - width - m)),
    top: fit(top, m, Math.max(m, box.height - height - m)),
    width, height,
  };
}

// The corner a window at `rect` (inside `box`) is nearest, with its gaps to that corner.
export function floatAnchor(rect, box) {
  const left = rect.left + rect.width / 2 < box.width / 2;
  const top = rect.top + rect.height / 2 < box.height / 2;
  return {
    corner: `${top ? 't' : 'b'}${left ? 'l' : 'r'}`,
    dx: Math.max(0, Math.round(left ? rect.left : box.width - rect.left - rect.width)),
    dy: Math.max(0, Math.round(top ? rect.top : box.height - rect.top - rect.height)),
  };
}

// ------------------------------------------------------------------ the model base (laser files)
// The stepped ground for a site model (GET .../site/model-base) and its laser files
// (GET .../site/model-base/files), in the range picked for the surroundings.

export const MODEL_SCALES = [200, 500, 1000];
export const MODEL_DEFAULTS = { scale: 500, thickness: 3, sheet: '600x400', hollow: 0 };

// The height one sheet of material stands for (m): its thickness at the model's scale.
export function stepInterval(scale, thickness) {
  return Math.round(Number(thickness) * Number(scale)) / 1000;
}

// A sheet size typed as WxH (mm, 50–3000 each) as [w, h], or null.
export function readSheet(text) {
  const m = /^\s*(\d+(?:\.\d+)?)\s*[x×*]\s*(\d+(?:\.\d+)?)\s*$/i.exec(String(text ?? ''));
  if (!m) return null;
  const [w, h] = [Number(m[1]), Number(m[2])];
  return w >= 50 && w <= 3000 && h >= 50 && h <= 3000 ? [w, h] : null;
}

// The query for the laser files: the model's settings and the surroundings' range.
export function modelBaseQuery(settings, range) {
  const s = { ...MODEL_DEFAULTS, ...(settings || {}) };
  const sheet = readSheet(s.sheet);
  const q = new URLSearchParams({
    scale: String(s.scale), thickness: String(s.thickness), sheet: sheet ? `${sheet[0]}x${sheet[1]}` : String(s.sheet),
    hollow: String(s.hollow || 0),
  });
  if (range?.size) q.set('size', range.size);
  if (range?.shape) q.set('shape', range.shape);
  return q.toString();
}

// The files' summary the server sends in the X-Model-Base header (k=v;k=v), and one line of it.
export function readModelSummary(header) {
  const out = {};
  for (const part of String(header || '').split(';')) {
    const [k, ...v] = part.split('=');
    if (k) out[k.trim()] = v.join('=').trim();
  }
  return out;
}

export function modelSummaryText(summary) {
  if (!summary || !summary.sheets) return '';
  const size = (summary.size_mm || '').split('x').map((v) => Math.round(Number(v))).filter(Boolean);
  const shape = summary.shape === 'circle' ? '원' : '정사각형';
  const name = { small: '작게', medium: '중간', large: '크게' }[summary.size] || `반경 ${Math.round(Number(summary.radius) || 0)}m`;
  return `판 ${summary.sheets}장 · 조각 ${summary.pieces}개 · 층 ${summary.layers}개`
    + (size.length === 2 ? ` · ${size[0]}×${size[1]} mm` : '') + ` (${name}, ${shape})`
    + (summary.buildings_left_out === 'True' ? ' · 실시간 건물은 파일에 넣지 않았습니다' : '');
}
