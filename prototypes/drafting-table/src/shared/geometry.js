// Site geometry for the prototype: lon/lat rings → local metres around the site's centre,
// polygon areas, and the coverage / floor-area figures a massing scheme gives.
import parcels from './parcels.json';

const R = 6378137;
const all = parcels.flatMap((p) => p.rings[0]);
const lon0 = all.reduce((s, [x]) => s + x, 0) / all.length;
const lat0 = all.reduce((s, [, y]) => s + y, 0) / all.length;

export function toLocal([lon, lat]) {
  const rad = Math.PI / 180;
  return [R * (lon - lon0) * rad * Math.cos(lat0 * rad), R * (lat - lat0) * rad];
}

export function polygonArea(ring) {
  let a = 0;
  for (let i = 0; i < ring.length; i += 1) {
    const [x1, y1] = ring[i];
    const [x2, y2] = ring[(i + 1) % ring.length];
    a += x1 * y2 - x2 * y1;
  }
  return Math.abs(a) / 2;
}

export const SITE = parcels.map((p) => ({ ...p, local: p.rings[0].map(toLocal) }));
export const SITE_AREA = SITE.reduce((s, p) => s + p.area_m2, 0); // registered areas (토지 특성)

function centroid(ring) {
  let a = 0; let cx = 0; let cy = 0;
  ring.forEach(([x1, y1], i) => {
    const [x2, y2] = ring[(i + 1) % ring.length];
    const f = x1 * y2 - x2 * y1;
    a += f; cx += (x1 + x2) * f; cy += (y1 + y2) * f;
  });
  return [cx / (3 * a), cy / (3 * a)];
}

// The site's main direction: the longest edge of the larger parcel, so masses line up with it.
const big = SITE.reduce((a, b) => (polygonArea(b.local) > polygonArea(a.local) ? b : a));
export const MASS_ORIGIN = centroid(big.local); // schemes sit on the larger parcel
let longest = 0;
export let SITE_ANGLE = 0;
big.local.forEach((p, i) => {
  const q = big.local[(i + 1) % big.local.length];
  const d = Math.hypot(q[0] - p[0], q[1] - p[1]);
  if (d > longest) { longest = d; SITE_ANGLE = Math.atan2(q[1] - p[1], q[0] - p[0]); }
});

// Example schemes. Each block: centre offset along/across the site direction, width, depth, floors.
export const FLOOR_HEIGHT = 4.2;
export const SCHEMES = {
  A: { name: '안 A · 판상형', blocks: [{ u: 0, v: 0, w: 36, d: 24, floors: 5 }] },
  B: { name: '안 B · ㄱ자형', blocks: [{ u: 0, v: 6, w: 40, d: 12, floors: 7 }, { u: -14, v: -7, w: 12, d: 14, floors: 3 }] },
};

export function schemeFigures(scheme) {
  const footprint = scheme.blocks.reduce((s, b) => s + b.w * b.d, 0);
  const floorArea = scheme.blocks.reduce((s, b) => s + b.w * b.d * b.floors, 0);
  return {
    footprint, floorArea,
    coverage: (footprint / SITE_AREA) * 100,
    far: (floorArea / SITE_AREA) * 100,
    height: Math.max(...scheme.blocks.map((b) => b.floors)) * FLOOR_HEIGHT,
  };
}

export const LIMITS = { zone: '일반공업지역', coverage: 70, farMin: 150, farMax: 350, ordinance: '군포시 도시계획 조례 제49조·제53조' };

export const fmt = (n, digits = 0) => n.toLocaleString('ko-KR', { maximumFractionDigits: digits, minimumFractionDigits: digits });

// A block's footprint as a plan polygon (metres, north up).
export function blockFootprint(b) {
  const c = Math.cos(SITE_ANGLE);
  const s = Math.sin(SITE_ANGLE);
  return [[-1, -1], [1, -1], [1, 1], [-1, 1]].map(([su, sv]) => {
    const u = b.u + (su * b.w) / 2;
    const v = b.v + (sv * b.d) / 2;
    return [MASS_ORIGIN[0] + u * c - v * s, MASS_ORIGIN[1] + u * s + v * c];
  });
}

const sitePoints = SITE.flatMap((p) => p.local);
export const SITE_BOUNDS = {
  minX: Math.min(...sitePoints.map((p) => p[0])), maxX: Math.max(...sitePoints.map((p) => p[0])),
  minY: Math.min(...sitePoints.map((p) => p[1])), maxY: Math.max(...sitePoints.map((p) => p[1])),
};
