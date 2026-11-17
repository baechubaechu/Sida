// Sharing helpers (webui/app/share-model.js): the share window's words, comment threads and what
// the viewer page draws from a snapshot.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  paperCounts, leftOutLine, sizeLabel, keptUntil, usageView, shareStatus, uploadLabel, commentThreads,
  unreadComments, targetLabel, targetPaper, conductorQuestion, commentProblem, commentTime, viewerSchemes,
  figureRows, schemeBoxes, localRings, siteRows, commentSpot, prismTriangles, orbitCamera, startDistance,
  MAX_NAME, MAX_TEXT, EARTH_RADIUS,
} from '../../webui/app/share-model.js';

const near = (a, b, eps = 1e-6) => Math.abs(a - b) < eps;

test('what goes up and what stays home, in words', () => {
  assert.equal(paperCounts({ mass: 3, tracing: 2, note: 0, photo: 1 }), '매스안 3개, 트레이싱 2장, 사진 1장');
  assert.equal(paperCounts({}), '');
  assert.equal(leftOutLine({ expert: 1, pdf: 2, photo: 0 }), '전문가 결과 1개, PDF 2개는 올리지 않습니다.');
  assert.equal(leftOutLine({}), '');
});

test('sizes, expiry and comment times', () => {
  assert.equal(sizeLabel(10), '1KB');
  assert.equal(sizeLabel(512 * 1024), '512KB');
  assert.equal(sizeLabel(3.25 * 1024 * 1024), '3.3MB');
  assert.equal(keptUntil('2026-12-17T10:00:00+09:00'), '12월 17일까지 보관');
  assert.equal(keptUntil(''), '');
  assert.equal(commentTime('2026-11-17T21:40:05+09:00'), '11월 17일 21:40');
  assert.equal(commentTime(null), '');
});

test('usage bars against the server limits', () => {
  const view = usageView({
    on: true, bytes: 5 * 1024 * 1024,
    usage: { bytes: 50 * 1024 * 1024, shares: 3, new_shares: 2, limits: { share_mb: 20, owner_mb: 100, owner_shares: 10, new_shares: 10, period_days: 14 } },
  });
  assert.equal(view.project.pct, 25);
  assert.equal(view.mine.pct, 50);
  assert.equal(view.line, '내 공유 3개 / 10개 · 새 공유 2개 / 14일에 10개');
  assert.equal(usageView({}).project.pct, 0);
});

test('status and the upload button', () => {
  assert.deepEqual(shareStatus(null), { text: '공유 꺼짐', on: false });
  assert.equal(shareStatus({ on: true, version: 2, comment_url: 'a', view_url: 'b' }).text, '공유 중 · 2번째 판 · 링크 2개');
  assert.equal(uploadLabel(null), '공유하기');
  assert.equal(uploadLabel({ on: true, version: 2 }), '새 판 올리기 (3번째)');
});

test('comments become numbered threads; orphan replies drop', () => {
  const threads = commentThreads([
    { id: 'c1', text: 'a' }, { id: 'c2', text: 'b' }, { id: 'r1', parent: 'c1', text: 'ra' }, { id: 'r2', parent: 'gone', text: 'x' },
  ]);
  assert.deepEqual(threads.map((t) => [t.id, t.number, t.replies.map((r) => r.id)]), [['c1', 1, ['r1']], ['c2', 2, []]]);
});

test('unread skips the designer, resolved and seen ones', () => {
  const unread = unreadComments([
    { id: 'c1' }, { id: 'c2', by_owner: true }, { id: 'c3', resolved: true }, { id: 'c4' },
  ], ['c4']);
  assert.deepEqual(unread.map((c) => c.id), ['c1']);
});

test('a target names the scheme and its block', () => {
  const papers = [
    { id: 'mass-a', kind: 'mass', title: 'A안', blocks: [{ floors: 5 }, { floors: 12 }] },
    { id: 'mass-b', kind: 'mass', title: '', blocks: [{ floors: 7 }] },
    { id: 'note-1', kind: 'note', title: '메모' },
  ];
  assert.equal(targetLabel('mass-a#1', papers), 'A안 · 2동 12층');
  assert.equal(targetLabel('mass-b#0', papers), '매스안 · 7층');
  assert.equal(targetLabel('mass-a', papers), 'A안');
  assert.equal(targetLabel('mass-a#9', papers), 'A안');
  assert.equal(targetLabel('nope#0', papers), '');
  assert.equal(targetPaper('mass-a#1'), 'mass-a');
  assert.equal(targetPaper(''), '');
});

test('the Conductor question quotes the comment on one line', () => {
  const q = conductorQuestion({ author: '이 교수', text: '타워가\n  높네요' }, 'A안 · 5층');
  assert.ok(q.startsWith('공유한 안에 이 교수님이 남긴 의견 (A안 · 5층): "타워가 높네요"'));
});

test('a viewer comment needs a name and text within limits', () => {
  assert.equal(commentProblem({ name: ' ', text: 'x' }), '이름을 적어 주세요.');
  assert.equal(commentProblem({ name: 'a'.repeat(MAX_NAME + 1), text: 'x' }), `이름은 ${MAX_NAME}자까지입니다.`);
  assert.equal(commentProblem({ name: '김', text: '' }), '댓글을 적어 주세요.');
  assert.equal(commentProblem({ name: '김', text: 'x'.repeat(MAX_TEXT + 1) }), `댓글은 ${MAX_TEXT}자까지입니다.`);
  assert.equal(commentProblem({ name: '김', text: '좋아요' }), '');
});

test('the viewer lists schemes with blocks, named A안, B안 when untitled', () => {
  const snapshot = { board: {
    papers: [
      { id: 'm1', kind: 'mass', blocks: [{}] }, { id: 'n', kind: 'note' }, { id: 'm2', kind: 'mass', title: '타워', blocks: [{}] },
      { id: 'm3', kind: 'mass', blocks: [] },
    ],
    figures: { m1: { far_pct: 200 } },
  } };
  const schemes = viewerSchemes(snapshot);
  assert.deepEqual(schemes.map((s) => [s.id, s.title]), [['m1', 'A안'], ['m2', '타워']]);
  assert.deepEqual(schemes[0].figures, { far_pct: 200 });
  assert.equal(schemes[1].figures, null);
  assert.deepEqual(viewerSchemes(null), []);
});

test('figure rows come only from the server numbers', () => {
  const rows = figureRows({ footprint_m2: 600, floor_area_m2: 3000, coverage_pct: 60, far_pct: 300, height_m: 21 }, 1000);
  assert.deepEqual(rows.map((r) => r[0]), ['대지면적', '건축면적', '연면적', '건폐율', '용적률', '최고 높이']);
  assert.equal(rows[2][1], '3,000㎡');
  assert.deepEqual(figureRows(null, 1000), []);
  assert.deepEqual(figureRows({ far_pct: 120 }).map((r) => r[0]), ['용적률']);
});

test('scheme boxes sit in the site frame with floors × floor height', () => {
  const boxes = schemeBoxes({ id: 'm', floor_height: 3, blocks: [{ u: 0, v: 0, w: 20, d: 10, floors: 5 }] }, { x: 100, y: 50, angle: 0 });
  assert.equal(boxes[0].key, 'm#0');
  assert.equal(boxes[0].top, 15);
  assert.deepEqual(boxes[0].corners, [[90, 45], [110, 45], [110, 55], [90, 55]]);
  assert.equal(schemeBoxes({ id: 'm', blocks: [{ u: 0, v: 0, w: 1, d: 1, floors: 2 }] }, null)[0].top, 8.4);
});

test('parcel rings go to metres around the origin as the site plan does', () => {
  const origin = { lon: 127, lat: 37.5 };
  const rings = localRings({ type: 'Polygon', coordinates: [[[127, 37.5], [127.001, 37.5], [127.001, 37.501]]] }, origin);
  const k = Math.PI / 180;
  assert.deepEqual(rings[0][0], [0, 0]);
  assert.ok(near(rings[0][1][0], 0.001 * EARTH_RADIUS * k * Math.cos(37.5 * k)));
  assert.ok(near(rings[0][2][1], 0.001 * EARTH_RADIUS * k, 1e-6));
  assert.equal(localRings({ type: 'MultiPolygon', coordinates: [[[[127, 37.5]]], [[[127, 37.5]]]] }, origin).length, 2);
  assert.deepEqual(localRings(null, origin), []);
  assert.deepEqual(localRings({ type: 'Point', coordinates: [0, 0] }, origin), []);
});

test('site lines split at the first colon', () => {
  assert.deepEqual(siteRows({ lines: ['용도지역: 일반상업지역', '메모 없음'] }), [
    { label: '용도지역', text: '일반상업지역' }, { label: '', text: '메모 없음' },
  ]);
  assert.deepEqual(siteRows(null), []);
});

test('a comment spot keeps the block key and rounds to centimetres', () => {
  assert.deepEqual(commentSpot({ key: 'm#0', x: 1.234, y: 2.345, z: 9.999 }), { target: 'm#0', at: { x: 1.23, y: 2.35, z: 10 } });
  assert.deepEqual(commentSpot({ x: 1, y: 2 }), { target: '', at: { x: 1, y: 2, z: 0 } });
  assert.equal(commentSpot(null), null);
});

test('a prism has two triangles per side and a fan roof', () => {
  const flat = prismTriangles([[0, 0], [1, 0], [1, 1], [0, 1]], 10);
  assert.equal(flat.length, (4 * 2 + 2) * 9);
  const zs = flat.filter((_, i) => i % 3 === 2);
  assert.ok(zs.every((z) => z === 0 || z === 10));
});

test('the orbit camera looks from the south when turned 0 and from above when tilted 0', () => {
  const south = orbitCamera({ turn: 0, tilt: 90, dist: 100 });
  assert.ok(near(south.position[0], 0) && near(south.position[1], -100) && near(south.position[2], 0));
  const top = orbitCamera({ x: 5, y: 6, z: 1, tilt: 0, dist: 50 });
  assert.ok(near(top.position[0], 5) && near(top.position[1], 6) && near(top.position[2], 51));
  assert.deepEqual(top.target, [5, 6, 1]);
});

test('the start distance fits the site and the tallest scheme', () => {
  assert.equal(startDistance(null), 150);
  assert.equal(startDistance({ min_x: 0, max_x: 10, min_y: 0, max_y: 10 }), 60);
  assert.ok(near(startDistance({ min_x: 0, max_x: 100, min_y: 0, max_y: 50 }), 220));
  assert.ok(near(startDistance({ min_x: 0, max_x: 10, min_y: 0, max_y: 10 }, 100), 240));
  assert.equal(startDistance({ min_x: 0, max_x: 1e5, min_y: 0, max_y: 0 }), 4000);
});
