// Sharing (공유) without the DOM: what the share window says, how comments hang together, and what
// the viewer page (share.html) draws from a snapshot. Used by the app's share window (share.js),
// the table's comment pins (table-comments.js) and the viewer (share-view.js).
// tests/webui/share-model.test.mjs checks it.

import { blockCorners, massPolygons } from './board-model.js';

const COUNT_WORDS = [['mass', '매스안', '개'], ['tracing', '트레이싱', '장'], ['note', '메모', '개'], ['photo', '사진', '장']];
const LEFT_WORDS = {
  photo: '사진', pdf: 'PDF', expert: '전문가 결과', rhino: '라이노 작업', section: '단면',
};
export const MAX_NAME = 40;
export const MAX_TEXT = 1000;
export const EARTH_RADIUS = 6378137.0; // m, the same as sida/board.py site_plan

// "매스안 3개, 트레이싱 2장, 메모 4개" for what goes up; "" when the table is empty.
export function paperCounts(counts = {}) {
  return COUNT_WORDS.filter(([kind]) => counts[kind]).map(([kind, word, unit]) => `${word} ${counts[kind]}${unit}`).join(', ');
}

// What stays home, in a line ("전문가 결과 1개, PDF 2개는 올리지 않습니다"); "" when nothing.
export function leftOutLine(left = {}) {
  const parts = Object.entries(left).filter(([, n]) => n > 0).map(([kind, n]) => `${LEFT_WORDS[kind] || kind} ${n}개`);
  return parts.length ? `${parts.join(', ')}는 올리지 않습니다.` : '';
}

export function sizeLabel(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024 * 1024) return `${Math.max(1, Math.round(n / 1024))}KB`;
  return `${(n / (1024 * 1024)).toFixed(1)}MB`;
}

// "12월 17일까지 보관" from the server's expiry (an ISO time); "" without one.
export function keptUntil(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${Number(m[2])}월 ${Number(m[3])}일까지 보관` : '';
}

// The share's usage against its limits, for the window's bars: {project, mine, shares, line}.
export function usageView(share = {}) {
  const usage = share.usage || {};
  const limits = usage.limits || {};
  const shareMb = limits.share_mb || 20;
  const ownerMb = limits.owner_mb || 100;
  const project = Number(share.bytes) || 0;
  const mine = Number(usage.bytes) || project;
  const pct = (part, whole) => Math.min(100, Math.round((part / whole) * 100));
  return {
    project: { text: `${sizeLabel(project)} / ${shareMb}MB`, pct: pct(project, shareMb * 1024 * 1024) },
    mine: { text: `${sizeLabel(mine)} / ${ownerMb}MB`, pct: pct(mine, ownerMb * 1024 * 1024) },
    line: `내 공유 ${usage.shares ?? (share.on ? 1 : 0)}개 / ${limits.owner_shares || 10}개 · 새 공유 ${usage.new_shares ?? 0}개 / ${limits.period_days || 14}일에 ${limits.new_shares || 10}개`,
  };
}

// The status line under the window's title.
export function shareStatus(share) {
  if (!share?.on) return { text: '공유 꺼짐', on: false };
  const links = share.comment_url && share.view_url ? ' · 링크 2개' : '';
  return { text: `공유 중 · ${share.version || 1}번째 판${links}`, on: true };
}

// The upload button: a first share or the next version.
export function uploadLabel(share) {
  return share?.on ? `새 판 올리기 (${(share.version || 0) + 1}번째)` : '공유하기';
}

// Comments as threads: each first comment with its replies, oldest first (as the server keeps
// them). A reply whose comment is gone is dropped.
export function commentThreads(comments = []) {
  const firsts = comments.filter((c) => !c.parent);
  const ids = new Set(firsts.map((c) => c.id));
  return firsts.map((c, i) => ({
    ...c,
    number: i + 1,
    replies: comments.filter((r) => r.parent === c.id && ids.has(r.parent)),
  }));
}

// Comments not yet seen by the designer (their own answers never count; resolved ones neither).
export function unreadComments(comments = [], seen = []) {
  const known = new Set(seen);
  return comments.filter((c) => !c.by_owner && !c.resolved && !known.has(c.id));
}

// What a comment is about, from its target ("mass-b#0": the scheme's block) and the shared papers:
// "B안 · 1동"; the scheme alone for a whole scheme; "" when it names nothing known.
export function targetLabel(target, papers = []) {
  if (!target) return '';
  const at = String(target).lastIndexOf('#');
  const id = at >= 0 ? target.slice(0, at) : target;
  const paper = papers.find((p) => p.id === id);
  if (!paper) return '';
  const name = paper.kind === 'mass' ? paper.title || '매스안' : paper.title || '';
  if (at < 0 || paper.kind !== 'mass') return name;
  const index = Number(target.slice(at + 1));
  const block = paper.blocks?.[index];
  if (!block) return name;
  return paper.blocks.length > 1 ? `${name} · ${index + 1}동 ${block.floors}층` : `${name} · ${block.floors}층`;
}

// The paper id a comment's target names ("mass-b#0" → "mass-b").
export function targetPaper(target) {
  if (!target) return '';
  const at = String(target).lastIndexOf('#');
  return at >= 0 ? target.slice(0, at) : target;
}

// The question "Conductor에게 묻기" puts in the command line.
export function conductorQuestion(comment, label = '') {
  const about = label ? ` (${label})` : '';
  const text = String(comment?.text || '').replace(/\s+/g, ' ').trim();
  return `공유한 안에 ${comment?.author || '보는 사람'}님이 남긴 의견${about}: "${text}" — 이 의견을 어떻게 반영하면 좋을지 지금 수치와 함께 검토해 줘.`;
}

// Checking a viewer's comment before it is sent: an error message, or ''.
export function commentProblem({ name = '', text = '' } = {}) {
  if (!String(name).trim()) return '이름을 적어 주세요.';
  if (String(name).trim().length > MAX_NAME) return `이름은 ${MAX_NAME}자까지입니다.`;
  if (!String(text).trim()) return '댓글을 적어 주세요.';
  if (String(text).trim().length > MAX_TEXT) return `댓글은 ${MAX_TEXT}자까지입니다.`;
  return '';
}

// "11월 17일 21:40" for a comment's time (the server keeps Korean time).
export function commentTime(iso) {
  const m = /^\d{4}-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || '');
  return m ? `${Number(m[1])}월 ${Number(m[2])}일 ${m[3]}:${m[4]}` : '';
}

// ------------------------------------------------------------------ the viewer

// The snapshot's massing schemes, in table order, each named "A안" or as the designer titled it.
export function viewerSchemes(snapshot) {
  const papers = snapshot?.board?.papers || [];
  return papers.filter((p) => p.kind === 'mass' && p.blocks?.length).map((p, i) => ({
    id: p.id, title: p.title || `${String.fromCharCode(65 + (i % 26))}안`, paper: p,
    figures: snapshot.board.figures?.[p.id] || null,
  }));
}

// The figures strip of a scheme: [label, value] pairs from the server's numbers (none made here).
export function figureRows(figures, siteArea) {
  if (!figures) return [];
  const rows = [];
  const num = (v, digits = 0) => Number(v).toLocaleString('ko-KR', { maximumFractionDigits: digits });
  if (siteArea) rows.push(['대지면적', `${num(siteArea, 1)}㎡`]);
  if (figures.footprint_m2 != null) rows.push(['건축면적', `${num(figures.footprint_m2, 1)}㎡`]);
  if (figures.floor_area_m2 != null) rows.push(['연면적', `${num(figures.floor_area_m2, 1)}㎡`]);
  if (figures.coverage_pct != null) rows.push(['건폐율', `${num(figures.coverage_pct, 1)}%`]);
  if (figures.far_pct != null) rows.push(['용적률', `${num(figures.far_pct, 1)}%`]);
  if (figures.height_m != null) rows.push(['최고 높이', `${num(figures.height_m, 1)}m`]);
  return rows;
}

// The boxes of a scheme in the site plan's metres: {key, corners [[x, y]×4], top} per block, on
// flat ground (the viewer has no terrain).
export function schemeBoxes(paper, frame) {
  const h = paper?.floor_height || 4.2;
  return (paper?.blocks || []).map((b, i) => ({
    key: `${paper.id}#${i}`, corners: blockCorners(frame, b), top: b.floors * h, floors: b.floors,
  }));
}

// A parcel boundary (GeoJSON from VWorld, lon/lat) in the site plan's metres around `origin`,
// as sida/board.py site_plan does it: [[x, y], …] per outer ring.
export function localRings(shape, origin) {
  if (!shape || !origin) return [];
  const k = Math.PI / 180;
  const east = EARTH_RADIUS * k * Math.cos(origin.lat * k);
  const north = EARTH_RADIUS * k;
  const polygons = shape.type === 'MultiPolygon' ? shape.coordinates : shape.type === 'Polygon' ? [shape.coordinates] : [];
  return polygons.filter((p) => p?.[0]?.length).map((p) => p[0].map(([lon, lat]) => [(lon - origin.lon) * east, (lat - origin.lat) * north]));
}

// The outer rings of a parcel boundary (GeoJSON, lon/lat) as they are: [[lon, lat], …] per ring.
export function outerRings(shape) {
  const polygons = shape?.type === 'MultiPolygon' ? shape.coordinates : shape?.type === 'Polygon' ? [shape.coordinates] : [];
  return polygons.filter((p) => p?.[0]?.length).map((p) => p[0].map(([lon, lat]) => [lon, lat]));
}

// How the surroundings look in the viewer: VWorld's buildings and ground in one colour, no names
// (vworld3d-frame.js setLook), as the table's white model.
export const AROUND_LOOK = Object.freeze({ white: true, plain: true, noNames: true });

// What the VWorld 3D page needs for a scheme (vworld3d-frame.js show/setMasses/findSite): the
// site's middle, the scheme's blocks as lon/lat prisms, and the parcels' rings (to find and hide
// the buildings standing on the site now). Null when the snapshot has no place on the map.
export function aroundScene(snapshot, schemeId, parcels = []) {
  const plan = snapshot?.site?.plan;
  if (!plan?.origin) return null;
  const paper = viewerSchemes(snapshot).find((s) => s.id === schemeId)?.paper || null;
  return {
    center: { lon: plan.origin.lon, lat: plan.origin.lat },
    polygons: massPolygons(paper, plan),
    rings: (parcels || []).flatMap((p) => outerRings(p?.shape)),
  };
}

// The site card's fact lines for the viewer ("용도지역: 일반상업지역" → label and text); the rules
// ("이 대지에 걸리는 것") go through model.js siteRuleRows, as on the app's card.
export function siteRows(site) {
  return (site?.lines || []).map((line) => {
    const at = line.indexOf(':');
    return at > 0 ? { label: line.slice(0, at).trim(), text: line.slice(at + 1).trim() } : { label: '', text: line };
  });
}

// Where a viewer's comment on the model points, from a hit on a block: the block key and the
// spot (metres), or a spot on the ground.
export function commentSpot(hit) {
  if (!hit) return null;
  const at = { x: Math.round(hit.x * 100) / 100, y: Math.round(hit.y * 100) / 100, z: Math.round((hit.z || 0) * 100) / 100 };
  return { target: hit.key || '', at };
}

// A block as a closed prism for three.js: the triangles of its sides and roof (flat positions,
// x y z), the corners going round as blockCorners gives them.
export function prismTriangles(corners, top, base = 0) {
  const out = [];
  const n = corners.length;
  for (let i = 0; i < n; i++) {
    const [ax, ay] = corners[i];
    const [bx, by] = corners[(i + 1) % n];
    out.push(ax, ay, base, bx, by, base, bx, by, top, ax, ay, base, bx, by, top, ax, ay, top);
  }
  for (let i = 1; i < n - 1; i++) {
    const [ax, ay] = corners[0];
    const [bx, by] = corners[i];
    const [cx, cy] = corners[i + 1];
    out.push(ax, ay, top, bx, by, top, cx, cy, top);
  }
  return out;
}

// The viewer's camera about its target: `turn` degrees clockwise from looking north, `tilt`
// degrees down from straight above, `dist` metres away. Z is up, as on the table.
export function orbitCamera({ x = 0, y = 0, z = 0, turn = 30, tilt = 55, dist = 150 } = {}) {
  const t = (tilt * Math.PI) / 180;
  const a = (turn * Math.PI) / 180;
  const flat = Math.sin(t) * dist;
  return { position: [x - Math.sin(a) * flat, y - Math.cos(a) * flat, z + Math.cos(t) * dist], target: [x, y, z] };
}

// How far the viewer's camera starts: enough to see the site and the tallest scheme.
export function startDistance(bounds, tallest = 0) {
  if (!bounds) return 150;
  const span = Math.max(bounds.max_x - bounds.min_x, bounds.max_y - bounds.min_y, 20);
  return Math.min(4000, Math.max(60, span * 2.2, tallest * 2.4));
}
