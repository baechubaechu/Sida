// Drafting table helpers (webui/app/board-model.js): run with `node --test tests/webui/`.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PX, TILT, cameraFor, riseFor, zoomAround, drawingScale, lerpView, siteBounds, traceHome,
  isOverlaid, blockCorners, unplaced, placeUnplaced, freeSpot, fitView, paperName, originLabel,
  figureLines, readScheme, schemeRows, keepSelected, toggleSelected, pickedNames, MAX_CONTEXT,
  folded, foldedInPlan, pinnedPapers, peekSpot, resultPreview,
} from '../../webui/app/board-model.js';

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);
const SITE = { plan: { bounds: { min_x: -30, min_y: -50, max_x: 30, max_y: 50 }, frame: { x: 5, y: -10, angle: Math.PI / 2 } } };

test('a plan looks straight down and masses lie flat; leaning raises them', () => {
  const plan = cameraFor({ x: 10, y: 20, span: 100, tilt: TILT.plan, turn: 0 });
  close(plan.position[0], 10);
  close(plan.position[1], 20);
  assert.deepEqual(plan.target, [10, 20, 0]);
  assert.ok(riseFor(0) < 0.01 && riseFor(TILT.axo) === 1);
  const axo = cameraFor({ x: 0, y: 0, span: 100, tilt: TILT.axo, turn: 0 });
  assert.ok(axo.position[1] < 0, 'the viewer stands south of the target when facing north');
});

test('zooming keeps the point under the cursor and stays within limits', () => {
  const v = zoomAround({ x: 0, y: 0, span: 100, tilt: 0, turn: 0 }, 50, 0, 0.5);
  assert.equal(v.span, 50);
  close(v.x, 25);
  assert.equal(zoomAround(v, 0, 0, 1e-6).span, 12);
  assert.equal(drawingScale(100, 400), '1:1000');
  assert.equal(lerpView({ x: 0, y: 0, span: 10, tilt: 0, turn: 350 }, { x: 0, y: 0, span: 10, tilt: 0, turn: 10 }, 0.5).turn, 360);
});

test('without site facts the table still has a site-sized area; tracing covers the site', () => {
  assert.deepEqual(siteBounds(null), { minX: -30, minY: -30, maxX: 30, maxY: 30 });
  const b = siteBounds(SITE);
  assert.deepEqual(b, { minX: -30, minY: -50, maxX: 30, maxY: 50 });
  const home = traceHome(b);
  assert.deepEqual([home.x, home.y], [0, 0]);
  close(home.w * PX, 60 + 28);
  assert.ok(isOverlaid({ kind: 'tracing', x: 0, y: 0 }, home));
  assert.ok(!isOverlaid({ kind: 'tracing', x: 1, y: 0 }, home));
  assert.ok(!isOverlaid({ kind: 'note', x: 0, y: 0 }, home));
});

test('blocks stand in the site frame: u runs along the long side', () => {
  const corners = blockCorners(SITE.plan.frame, { u: 10, v: 0, w: 4, d: 2, floors: 1 });
  const xs = corners.map((c) => c[0]);
  const ys = corners.map((c) => c[1]);
  close(Math.min(...xs), 4); close(Math.max(...xs), 6); // across (v) is now east–west, 2 m
  close(Math.min(...ys), -2); close(Math.max(...ys), 2); // along (u) is north, centred 10 m up
});

test('papers the server left at 0, 0 are laid beside the site, the site paper to the west', () => {
  const b = siteBounds(SITE);
  const papers = [
    { id: 'site', kind: 'site', x: 0, y: 0, w: 300, h: 250 },
    { id: 'm', kind: 'mass', x: 0, y: 0, w: 300, h: 210 },
    { id: 'kept', kind: 'note', x: 100, y: 0, w: 200, h: 140 },
    { id: 'trace', kind: 'tracing', x: 0, y: 0, w: 880, h: 1280 },
  ];
  assert.ok(!unplaced(papers[3]), 'a tracing sheet at 0, 0 lies on the site');
  const moves = placeUnplaced(papers, b);
  assert.deepEqual(moves.map((m) => m.id), ['site', 'm']);
  assert.ok(moves[0].x + 15 < b.minX, 'the site paper sits west of the site');
  assert.ok(moves[1].x - 15 > 110, 'a new paper goes east of every placed one');
  const spot = freeSpot(papers.slice(2), b, 200, 140);
  close(spot.x, 110 + 4 + 10);
  const view = fitView(papers, b, 1);
  assert.ok(view.span >= 100 && view.tilt === 0);
});

test('paper names match the server and AI papers say who made them', () => {
  assert.equal(paperName({ kind: 'site' }), '대지');
  assert.equal(paperName({ kind: 'note', text: '북측   인접 대지 일조를 꼭 확인할 것 그리고 더' }), '메모: 북측 인접 대지 일조를 꼭 확인할 것…');
  assert.equal(paperName({ kind: 'mass' }), '매스안');
  assert.equal(paperName({ kind: 'expert', title: '법규 검토자', agent: 'regulation_checker' }), '법규 검토자 결과');
  const experts = [{ id: 'regulation_checker', name: '법규 검토자' }];
  assert.equal(originLabel({ origin: 'conductor' }, experts), 'Conductor 제안');
  assert.equal(originLabel({ origin: 'regulation_checker' }, experts), '법규 검토자 결과');
  assert.equal(originLabel({}, experts), '');
});

test('figures come from the server; a missing site area says so', () => {
  const known = figureLines({ footprint_m2: 864, floor_area_m2: 4320, height_m: 21, coverage_pct: 30.8, far_pct: 154.1 });
  assert.match(known[1], /건폐율 30\.8% · 용적률 154\.1%/);
  const unknown = figureLines({ footprint_m2: 864, floor_area_m2: 4320, height_m: 21, coverage_pct: null, far_pct: null });
  assert.match(unknown[1], /미확인/);
  assert.deepEqual(figureLines(undefined), []);
});

test('the scheme form catches typing slips before the server does', () => {
  const ok = readScheme({ title: ' 안 B ', floorHeight: '4', rows: [{ w: '40', d: '12', floors: '7', u: '', v: '6' }] });
  assert.deepEqual(ok, { title: '안 B', floor_height: 4, blocks: [{ u: 0, v: 6, w: 40, d: 12, floors: 7 }] });
  assert.match(readScheme({ rows: [{ w: '0', d: '12', floors: '3' }] }).error, /1동: 가로·세로/);
  assert.match(readScheme({ rows: [{ w: '10', d: '12', floors: '2.5' }] }).error, /층수/);
  assert.match(readScheme({ rows: [] }).error, /하나 이상/);
  assert.match(readScheme({ floorHeight: '0', rows: [{ w: '10', d: '10', floors: '1' }] }).error, /층고/);
  assert.equal(schemeRows({ blocks: [{ u: 1, v: 2, w: 3, d: 4, floors: 5 }] })[0].floors, '5');
  assert.equal(schemeRows(null).length, 1);
});

test('the picked papers stay in order, at most eight, and drop when gone', () => {
  let picked = toggleSelected([], 'a', true);
  picked = toggleSelected(picked, 'b', true);
  assert.deepEqual(picked, ['a', 'b']);
  assert.deepEqual(toggleSelected(picked, 'a', true), ['b']);
  assert.deepEqual(toggleSelected(picked, 'c', false), ['c']);
  const many = Array.from({ length: 12 }, (_, i) => `p${i}`).reduce((s, id) => toggleSelected(s, id, true), []);
  assert.equal(many.length, MAX_CONTEXT);
  const board = { papers: [{ id: 'a', kind: 'site' }], tray: [{ id: 'b', kind: 'mass', title: '안 A 수정안' }] };
  assert.deepEqual(keepSelected(['b', 'gone', 'a'], board), ['b', 'a']);
  assert.deepEqual(pickedNames(['a', 'b', 'x'], board), [{ id: 'a', name: '대지' }, { id: 'b', name: '안 A 수정안' }, { id: 'x', name: 'x' }]);
});

test('papers lie flat in plan and fold into pins once the table leans', () => {
  assert.ok(!folded(TILT.plan) && !folded(9));
  assert.ok(folded(TILT.axo) && folded(TILT.eye));
  const home = traceHome(siteBounds(SITE));
  const papers = [
    { id: 'site', kind: 'site', x: -50, y: 0 },
    { id: 'on', kind: 'tracing', x: home.x, y: home.y },
    { id: 'off', kind: 'tracing', x: 80, y: 0 },
  ];
  assert.deepEqual(pinnedPapers(papers, home).map((p) => p.id), ['site', 'off'], 'a sheet on the site draws on the ground instead');
});

test('a pin opens its card beside it and inside the table, never over the side panels', () => {
  const box = { left: 12, top: 12, right: 700, bottom: 500 };
  const size = { w: 300, h: 200 };
  assert.deepEqual(peekSpot({ x: 100, y: 200, w: 80 }, size, box), { x: 152, y: 100 });
  const flipped = peekSpot({ x: 600, y: 200, w: 80 }, size, box);
  assert.equal(flipped.x, 600 - 40 - 12 - 300, 'no room on the right: it opens to the left of the pin');
  assert.equal(peekSpot({ x: 100, y: 20, w: 80 }, size, box).y, 12);
  assert.equal(peekSpot({ x: 100, y: 490, w: 80 }, size, box).y, 300);
  const cramped = peekSpot({ x: 50, y: 50, w: 40 }, { w: 900, h: 900 }, box);
  assert.deepEqual(cramped, { x: 12, y: 12 }, 'a card bigger than the table starts at its corner');
});

test('an expert result paper previews plain lines with Korean section names, no markdown marks', () => {
  const text = '# Site Reader\n## Facts\n- 대지 면적 **1,014.3㎡** — source: site facts\n\n## Interpretations\n1. `역` 접근\n## Custom Part\nplain';
  assert.equal(resultPreview(text), '[사실]\n· 대지 면적 1,014.3㎡ — source: site facts\n[해석]\n· 역 접근\n[Custom Part]\nplain');
  assert.equal(resultPreview(text, 2), '[사실]\n· 대지 면적 1,014.3㎡ — source: site facts');
  assert.equal(resultPreview(''), '');
  assert.equal(resultPreview(undefined), '');
});

test('papers the designer folded stay pins in plan, except a tracing laid over the site', () => {
  const home = { x: 0, y: 0, w: 600, h: 500 };
  const papers = [
    { id: 'n1', kind: 'note', x: 40, y: 0, folded: true },
    { id: 'n2', kind: 'note', x: 60, y: 0 },
    { id: 't1', kind: 'tracing', x: 0, y: 0, w: 600, h: 500, folded: true },
    { id: 't2', kind: 'tracing', x: 90, y: 0, w: 600, h: 500, folded: true },
  ];
  assert.deepEqual(foldedInPlan(papers, home), ['n1', 't2']);
  assert.deepEqual(foldedInPlan([], home), []);
});
