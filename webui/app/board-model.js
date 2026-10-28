// Helpers for the drafting table (제도판) that touch neither the DOM nor three.js, so
// tests/webui/board-model.test.mjs can check them. The table is the x–y plane in metres,
// x east, y north, 0, 0 the middle of the site (GET .../board → site.plan).
// Figures (coverage, FAR) are never computed here: they come from the server (`figures`).

import { SECTION_LABELS } from './model.js';

export const PX = 0.1; // metres per CSS pixel of paper lying on the table
export const TILT = { plan: 0, axo: 35, eye: 68 };
export const MAX_TILT = 75;
export const FOLD_TILT = 10; // past this lean papers fold into pins, so the model reads (2026-10-26)
export const VIEW_LIMITS = { min: 12, max: 2500 }; // metres of table shown top to bottom
export const TRACE_MARGIN = 14; // metres of tracing paper around the site
export const PAPER_SIZE = { site: [300, 250], mass: [300, 210], note: [200, 140], expert: [320, 270] };
export const MAX_BLOCKS = 20;
export const MAX_CONTEXT = 8; // papers one message may carry (board.MAX_CONTEXT)

const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const rad = (d) => (d * Math.PI) / 180;

export const fmt = (n, digits = 0) => Number(n).toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits });

// ------------------------------------------------------------------ camera
// One camera, as plain numbers. tilt 0° looks straight down (a plan), 35° reads as an
// axonometric, 68° is near eye level. A long lens at low tilt keeps the plan flat.

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
  const fy = Math.cos(rad(v.turn)); // the direction the viewer faces on the table
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

// Drawing scale for the corner, for a 96 dpi screen: "1:500".
export function drawingScale(span, viewportPx) {
  const n = span / Math.max(1, viewportPx) / 0.0002646;
  const nice = [50, 100, 200, 250, 500, 1000, 1200, 2000, 2500, 5000, 10000, 25000];
  return `1:${nice.reduce((a, b) => (Math.abs(b - n) < Math.abs(a - n) ? b : a))}`;
}

export function lerpView(a, b, k) {
  const dt = ((b.turn - a.turn + 540) % 360) - 180;
  return {
    x: a.x + (b.x - a.x) * k, y: a.y + (b.y - a.y) * k, span: a.span + (b.span - a.span) * k,
    tilt: a.tilt + (b.tilt - a.tilt) * k, turn: a.turn + dt * k,
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

// A block's footprint on the table: blocks stand in the site's frame (u along its long side).
export function blockCorners(frame, b) {
  const f = frame || { x: 0, y: 0, angle: 0 };
  const c = Math.cos(f.angle);
  const s = Math.sin(f.angle);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([su, sv]) => {
    const u = b.u + (su * b.w) / 2;
    const v = b.v + (sv * b.d) / 2;
    return [f.x + u * c - v * s, f.y + u * s + v * c];
  });
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
  return { x: (x0 + x1) / 2, y: (y0 + y1) / 2, span: Math.min(VIEW_LIMITS.max, Math.max(VIEW_LIMITS.min, span)), tilt: 0, turn: 0 };
}

// ------------------------------------------------------------------ pins in 3D
// Lying papers can't be read once the table leans and they hide the masses, so in 3D each
// paper folds into a small upright pin at its place; a pin opens the paper as a card beside it.

export const folded = (tilt) => tilt >= FOLD_TILT;

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

export const KIND_LABELS = { site: '대지', mass: '매스안', note: '메모', tracing: '트레이싱지', expert: '전문가 결과' };

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
    if (!(w > 0 && w <= 1000) || !(d > 0 && d <= 1000)) return { error: `${at}: 가로·세로는 0보다 크고 1000m 이하로 적어 주세요.` };
    if (!Number.isInteger(floors) || floors < 1 || floors > 200) return { error: `${at}: 층수는 1~200 사이 정수로 적어 주세요.` };
    if (!Number.isFinite(u) || !Number.isFinite(v)) return { error: `${at}: 위치는 숫자로 적어 주세요.` };
    blocks.push({ u, v, w, d, floors });
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
    u: String(b.u), v: String(b.v), w: String(b.w), d: String(b.d), floors: String(b.floors),
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

// For the chips above a composer: the names of the picked papers.
export function pickedNames(ids, board) {
  const all = [...(board?.papers || []), ...(board?.tray || [])];
  return ids.map((id) => ({ id, name: paperName(all.find((p) => p.id === id)) || id }));
}
