// A section (단면) through the drafting table, as pure functions (tested in
// tests/webui/section-model.test.mjs). The same rules as the server's sida/board_section.py, so
// the drawing on the table and the file it exports agree:
//
// - The line runs from A (its first point) to A′; `s` is the distance along it. It looks to its
//   right (walking from A to A′), or to its left when flipped; drawn as the viewer sees it, a
//   section that looks to the right of its line reads from A′ on the left to A on the right.
// - The ground is read every PROFILE_STEP metres along the line (and at its end); where it is not
//   known (off the grid, outside a round or oblong range) the profile has a gap.
// - A solid whose footprint the line crosses is cut where the line runs inside it. One it misses
//   that stands wholly on the looked-at side, no further than `depth`, is seen beyond the cut.
// - A block stands on the lowest ground under it and rises its floors × the floor height; a
//   building around runs from the bottom of its foundation to its roof. The building standing on
//   the site now is left out: the scheme takes its place.

import { blockCorners, massBase, isEstimate, OUTSIDE } from './board-model.js';

export const PROFILE_STEP = 1;
export const MIN_SPAN = 0.05;
export const SECTION_SCALES = [100, 200, 300, 500, 600, 1000, 1200, 2000, 2500, 5000];
export const SECTION_DEFAULTS = { depth: 60, scale: 500, flip: false };
export const SECTION_DEPTHS = [0, 30, 60, 120, 1000]; // the depth menu: 0 is only what the line cuts
export const MIN_SECTION_LENGTH = 2; // metres: a shorter drag draws no section

const dot = (a, b) => a[0] * b[0] + a[1] * b[1];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1]];
const r3 = (v) => Math.round(v * 1000) / 1000;

// The next free name: A, B, … Z, then A2, B2, …
export function nextSectionName(papers) {
  const taken = new Set((papers || []).filter((p) => p.kind === 'section').map((p) => p.title || 'A'));
  for (let round = 1; ; round += 1) {
    for (const letter of 'ABCDEFGHIJKLMNOPQRSTUVWXYZ') {
      const name = round === 1 ? letter : `${letter}${round}`;
      if (!taken.has(name)) return name;
    }
  }
}

// Length, direction d, the looked-toward side n (unit vectors) and whether the drawing reads A′ to A.
export function sectionFrame(line, flip = false) {
  const [[x0, y0], [x1, y1]] = line;
  const length = Math.hypot(x1 - x0, y1 - y0);
  if (!(length > 0)) return null;
  const d = [(x1 - x0) / length, (y1 - y0) / length];
  let n = [d[1], -d[0]];
  if (flip) n = [-n[0], -n[1]];
  const right = [n[1], -n[0]];
  return { length, d, n, mirror: dot(d, right) < 0 };
}

function inside(x, y, ring) {
  let hit = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
    const [x1, y1] = ring[j];
    const [x2, y2] = ring[i];
    if ((y1 > y) !== (y2 > y) && x < x1 + ((y - y1) * (x2 - x1)) / (y2 - y1)) hit = !hit;
  }
  return hit;
}

// Where the line p0 + s·d (0 ≤ s ≤ length) runs inside the polygon `ring`: [[a, b]].
export function spans(p0, d, length, ring) {
  const cuts = [0, length];
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    const ex = x2 - x1, ey = y2 - y1;
    const den = d[0] * ey - d[1] * ex;
    if (Math.abs(den) < 1e-12) continue;
    const wx = x1 - p0[0], wy = y1 - p0[1];
    const s = (wx * ey - wy * ex) / den;
    const t = (wx * d[1] - wy * d[0]) / den;
    if (t >= -1e-9 && t <= 1 + 1e-9 && s > 0 && s < length) cuts.push(s);
  }
  cuts.sort((a, b) => a - b);
  const out = [];
  for (let k = 0; k + 1 < cuts.length; k += 1) {
    const a = cuts[k], b = cuts[k + 1];
    if (b - a < 1e-9) continue;
    const m = (a + b) / 2;
    if (!inside(p0[0] + d[0] * m, p0[1] + d[1] * m, ring)) continue;
    if (out.length && Math.abs(out[out.length - 1][1] - a) < 1e-9) out[out.length - 1][1] = b;
    else out.push([a, b]);
  }
  return out;
}

// The ground's height at (x, y) on the surroundings' grid {min, step, n, z, classes}, bilinear;
// null off the grid or where the nearest point is outside the range.
export function groundHeight(terrain, x, y) {
  if (!terrain?.n || !terrain.z?.length) return null;
  const { min, step, n, z, classes } = terrain;
  const u = (x - min) / step, v = (y - min) / step;
  if (u < -1e-9 || v < -1e-9 || u > n - 1 + 1e-9 || v > n - 1 + 1e-9) return null;
  if (classes && classes[Math.round(v) * n + Math.round(u)] === OUTSIDE) return null;
  const i = Math.min(Math.max(0, Math.floor(u)), n - 2), j = Math.min(Math.max(0, Math.floor(v)), n - 2);
  const a = u - i, b = v - j, k = j * n + i;
  return (1 - b) * ((1 - a) * z[k] + a * z[k + 1]) + b * ((1 - a) * z[k + n] + a * z[k + n + 1]);
}

// The ground along the line as runs of [s, z].
export function sectionProfile(line, terrain, length, d) {
  if (!terrain) return [];
  const steps = Math.max(1, Math.ceil(length / PROFILE_STEP - 1e-9));
  const runs = [];
  let run = [];
  for (let k = 0; k <= steps; k += 1) {
    const s = Math.min(length, k * PROFILE_STEP);
    const z = groundHeight(terrain, line[0][0] + d[0] * s, line[0][1] + d[1] * s);
    if (z === null) { if (run.length) runs.push(run); run = []; continue; }
    run.push([r3(s), r3(z)]);
  }
  if (run.length) runs.push(run);
  return runs.filter((r) => r.length >= 2);
}

// The section: {length, mirror, profile, cut, beyond (far first)}; solids are {outline, base, top, kind, …}.
export function sectionCut(line, solids, terrain, { flip = false, depth = SECTION_DEFAULTS.depth, from = 0, to = null } = {}) {
  const f = sectionFrame(line, flip);
  if (!f) return null;
  const { d, n } = f;
  const length = f.length;
  const s0 = from, s1 = to ?? length; // the 3D cut runs past the line's ends, across the whole range
  const p0 = [line[0][0] + d[0] * s0, line[0][1] + d[1] * s0];
  const cut = [], beyond = [];
  for (const solid of solids) {
    const pieces = spans(p0, d, s1 - s0, solid.outline).filter(([a, b]) => b - a > MIN_SPAN);
    if (pieces.length) {
      for (const [a, b] of pieces) cut.push({ ...solid, a: r3(a + s0), b: r3(b + s0) });
      continue;
    }
    const dist = solid.outline.map((p) => dot(sub(p, line[0]), n));
    const near = Math.min(...dist);
    if (near < 0 || near > depth) continue;
    const along = solid.outline.map((p) => dot(sub(p, line[0]), d));
    const a = Math.max(s0, Math.min(...along)), b = Math.min(s1, Math.max(...along));
    if (b - a > MIN_SPAN) beyond.push({ ...solid, a: r3(a), b: r3(b), dist: r3(near) });
  }
  beyond.sort((x, y) => y.dist - x.dist);
  const profileLine = [p0, [p0[0] + d[0] * (s1 - s0), p0[1] + d[1] * (s1 - s0)]];
  const profile = sectionProfile(profileLine, terrain, s1 - s0, d).map((run) => run.map(([s, z]) => [r3(s + s0), z]));
  return { length: r3(length), mirror: f.mirror, profile, cut, beyond };
}

// What the section cuts on the table: the blocks of the scheme shown in 3D (standing on the ground
// when the surroundings are on) and the buildings around, less the parts turned off in 레이어 and
// the building on the site now.
export function sectionSolids({ scheme = null, frame = null, terrain = null, buildings = [], hiddenParts = new Set() } = {}) {
  const solids = [];
  const storey = scheme?.floor_height || 4.2;
  for (const [i, b] of (scheme?.blocks || []).entries()) {
    const outline = blockCorners(frame, b);
    const base = massBase(outline, terrain);
    solids.push({ kind: 'mass', outline, base, top: base + b.floors * storey, floors: b.floors, storey, name: `${i + 1}동` });
  }
  for (const b of buildings || []) {
    if (b.on_site) continue;
    const estimate = isEstimate(b);
    if (hiddenParts.has(estimate ? 'estimated' : 'buildings')) continue;
    solids.push({ kind: 'building', outline: b.outline, base: b.base, top: b.top, estimate });
  }
  return solids;
}

// The numbers a section shows under its drawing.
export function sectionFigures(result) {
  if (!result) return [];
  const zs = result.profile.flat().map(([, z]) => z);
  const masses = result.cut.filter((c) => c.kind === 'mass');
  const buildings = result.cut.filter((c) => c.kind === 'building');
  const f1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
  const rows = [`길이 ${f1(result.length)}m`];
  if (zs.length) rows.push(`지형 높이차 ${f1(Math.max(...zs) - Math.min(...zs))}m`);
  if (masses.length) rows.push(`자른 매스 ${masses.map((c) => `${f1(c.top - c.base)}m`).join(', ')}`);
  if (buildings.length) rows.push(`자른 주변 건물 ${buildings.length}동`);
  return rows;
}

const esc = (text) => String(text).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// The section drawn as an SVG (for its paper and the 속성 panel): the cut ground, blocks and
// buildings filled, what is seen beyond as outlines (nearer ones cover farther ones), floor lines,
// ±0 and the A / A′ marks. Colours come from CSS classes (sec-*), so the screen's theme decides.
export function sectionSvg(result, { name = 'A', floors = true, heights = true } = {}) {
  if (!result) return '';
  const { length, mirror } = result;
  const u = (s) => (mirror ? length - s : s);
  const zs = result.profile.flat().map(([, z]) => z);
  const tops = [...result.cut, ...result.beyond].map((c) => c.top);
  const bases = result.cut.map((c) => c.base);
  const low = Math.min(0, ...zs, ...bases) - 4;
  const high = Math.max(0, ...zs, ...tops) + 3;
  const pad = Math.max(4, length * 0.06);
  const width = length + pad * 2 + (heights ? length * 0.08 : 0);
  const height = high - low + pad;
  const X = (s) => pad + u(s);
  const Y = (z) => high - z;
  const n2 = (v) => v.toFixed(2);
  const rect = (c, cls, extra = '') => {
    const a = Math.min(X(c.a), X(c.b)), w = Math.abs(X(c.b) - X(c.a));
    return `<rect class="${cls}" x="${n2(a)}" y="${n2(Y(c.top))}" width="${n2(w)}" height="${n2(Math.max(0, c.top - c.base))}"${extra}/>`;
  };
  const out = [];
  out.push(`<line class="sec-datum" x1="${n2(pad * 0.5)}" x2="${n2(width - pad * 0.5)}" y1="${n2(Y(0))}" y2="${n2(Y(0))}"/>`);
  for (const c of result.beyond) out.push(rect(c, `sec-beyond${c.estimate ? ' is-estimate' : ''}`));
  for (const run of result.profile) {
    const pts = run.map(([s, z]) => `${n2(X(s))},${n2(Y(z))}`);
    out.push(`<polygon class="sec-ground" points="${n2(X(run[0][0]))},${n2(Y(low))} ${pts.join(' ')} ${n2(X(run[run.length - 1][0]))},${n2(Y(low))}"/>`);
    out.push(`<polyline class="sec-ground-line" points="${pts.join(' ')}"/>`);
  }
  for (const c of result.cut) {
    if (c.kind === 'mass') {
      out.push(rect(c, 'sec-mass'));
      if (floors) {
        const a = Math.min(X(c.a), X(c.b)), b = Math.max(X(c.a), X(c.b));
        for (let f = 1; f < (c.floors || 0); f += 1) out.push(`<line class="sec-floor" x1="${n2(a)}" x2="${n2(b)}" y1="${n2(Y(c.base + f * c.storey))}" y2="${n2(Y(c.base + f * c.storey))}"/>`);
      }
    } else {
      out.push(rect(c, `sec-building${c.estimate ? ' is-estimate' : ''}`));
    }
  }
  const size = Math.max(1.6, height * 0.05, width * 0.03); // the marks stay readable on a long, low section
  if (heights) {
    for (const c of result.cut.filter((x) => x.kind === 'mass')) {
      const x = Math.max(X(c.a), X(c.b)) + size * 0.4;
      out.push(`<text class="sec-text" x="${n2(x)}" y="${n2(Y(c.top) + size)}" font-size="${n2(size)}">${esc(`${(Math.round((c.top - c.base) * 10) / 10).toFixed(1)}m`)}</text>`);
    }
  }
  const [left, right] = mirror ? [`${name}′`, name] : [name, `${name}′`];
  out.push(`<text class="sec-end" x="${n2(X(mirror ? length : 0))}" y="${n2(height - pad * 0.15)}" font-size="${n2(size * 1.3)}" text-anchor="middle">${esc(left)}</text>`);
  out.push(`<text class="sec-end" x="${n2(X(mirror ? 0 : length))}" y="${n2(height - pad * 0.15)}" font-size="${n2(size * 1.3)}" text-anchor="middle">${esc(right)}</text>`);
  return `<svg class="section-drawing" viewBox="0 0 ${n2(width)} ${n2(height)}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="단면 ${esc(name)}–${esc(name)}′">${out.join('')}</svg>`;
}

// Which end of a section line (0: A, 1: A′) lies within `tolerance` of a point, or -1.
export function nearEnd(line, point, tolerance) {
  let best = -1, gap = tolerance;
  line.forEach(([x, y], k) => {
    const g = Math.hypot(point.x - x, point.y - y);
    if (g <= gap) { gap = g; best = k; }
  });
  return best;
}

// A line dragged from `a` to `b` (table points): kept to the centimetre; with `snap` its angle
// goes to the nearest 15°.
export function draggedLine(a, b, snap = false) {
  let dx = b.x - a.x, dy = b.y - a.y;
  if (snap) {
    const len = Math.hypot(dx, dy);
    const ang = Math.round(Math.atan2(dy, dx) / (Math.PI / 12)) * (Math.PI / 12);
    dx = len * Math.cos(ang);
    dy = len * Math.sin(ang);
  }
  const cm = (v) => Math.round(v * 100) / 100;
  return [[cm(a.x), cm(a.y)], [cm(a.x + dx), cm(a.y + dy)]];
}

// The file of a section paper: GET .../board/sections/{id}/export, with the scheme shown in 3D.
export function sectionExport(name, id, format, active = '', label = name, title = 'A') {
  const query = new URLSearchParams({ format });
  if (active) query.set('active', active);
  const base = String(label || name).replace(/[\\/:*?"<>|]+/g, '_').trim() || 'sida';
  return {
    url: `/api/projects/${encodeURIComponent(name)}/board/sections/${encodeURIComponent(id)}/export?${query}`,
    filename: `${base}_단면_${title}-${title}.${format}`,
  };
}
