// Drafting table helpers (webui/app/board-model.js): run with `node --test tests/webui/`.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PX, TILT, MAX_TILT, cameraFor, riseFor, groundFor, zoomAround, drawingScale, scaleSpan, scaleBar, lerpView, siteBounds, traceHome, massBase,
  isOverlaid, blockCorners, unplaced, placeUnplaced, freeSpot, fitView, paperName, originLabel,
  figureLines, readScheme, schemeRows, keepSelected, toggleSelected, boxPick, boxMode, pickedNames, MAX_CONTEXT,
  frameDelta, editBlocks, axisDrag, blocksCenter, blockKey, parseBlockKey, pickedBlocks,
  toFrame, rectBlock, pushBlock, copyBlocks, turnBlocks, scaleBlocks, snapAngle,
  numericToolClick, numericPushBlock, numericScaleBlocks,
  snapTape,
  folded, foldedInPlan, pinnedPapers, peekSpot, resultPreview,
  massIds, canCompare, COMPARE_QUESTION, addQuestion, createHistory, changedFields, recordStep, undoStep, redoStep,
  invertStep, HISTORY_LIMIT, planDrawing, dragMode, wheelZoom, orbitBy, viewName, viewFor, panBy,
  photoPlan, shrunkSize, photoPaperSize, photoTitle, pickPhotoFiles, PHOTO_MAX_SIDE, MAX_PHOTOS_AT_ONCE, KIND_LABELS,
  isPdfFile, isPdfPaper, pdfCanvasSize, pdfNeedsRedraw, PDF_MAX_SIDE, PDF_MAX_AREA, resizable, resizedPaper, PAPER_LIMITS,
} from '../../webui/app/board-model.js';

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);

test('mass base uses interpolated edges and interior ground points like CAD', () => {
  const t = {min: -10, n: 5, step: 5, z: Array.from({length: 25}, (_, k) => 10 - (k % 5) * 5)};
  const ring = [[-6,-6],[6,-6],[6,6],[-6,6]];
  assert.equal(massBase(ring, t), -6);
  t.z[12] = -12;
  assert.equal(massBase(ring, t), -12);
  assert.equal(massBase(ring, null), 0);
  assert.equal(massBase(ring.map(([x,y]) => [x+50,y]), t), 0);
});

test('changing site drops old 3D data and ignores late responses', async () => {
  const {DraftingTable} = await import('../../webui/app/table.js');
  const t = Object.create(DraftingTable.prototype);
  Object.assign(t, {selected:[], picked:[], root:{clientWidth:0}, view:{span:100}});
  for (const method of ['drawSite','drawMasses','syncPapers','drawTray','drawControls','fit','invalidate','drawAround','animateTo']) t[method] = () => {};
  const setSite = lon => t.setBoard({site:{plan:{origin:{lon,lat:37},parcels:[],bounds:{min_x:-10,min_y:-10,max_x:10,max_y:10}}}});
  let finish;
  t.hooks = {context: () => new Promise(resolve => { finish = resolve; })};
  setSite(127);
  const first = t.toggleAround();
  setSite(128);
  finish({lon:127, radius:200});
  await first;
  assert.ok(!t.around);
  t.hooks.context = async () => ({lon:128,radius:200});
  await t.toggleAround();
  assert.equal(t.around.lon, 128);
  setSite(129);
  assert.ok(!t.aroundOn && !t.around);
});
const SITE = { plan: { bounds: { min_x: -30, min_y: -50, max_x: 30, max_y: 50 }, frame: { x: 5, y: -10, angle: Math.PI / 2 } } };

test('tape snaps to endpoints before edges, and leaves distant geometry alone', () => {
  const a = { x: 0, y: 0, z: 0 }, b = { x: 100, y: 0, z: 20 };
  const project = p => ({ x: p.x, y: p.y, w: 1 });
  assert.deepEqual(snapTape({ x: 4, y: 3 }, [[a, b]], project).point, a);
  assert.deepEqual(snapTape({ x: 50, y: 5 }, [[a, b]], project).point, { x: 50, y: 0, z: 10 });
  assert.equal(snapTape({ x: 50, y: 11 }, [[a, b]], project), null);
  assert.equal(snapTape({ x: 0, y: 0 }, [[a, b]], () => null), null);
});

test('tape perspective snapping interpolates real height and is independent of world scale', () => {
  const a = { x: 0, y: 0, z: 0 }, b = { x: 30, y: 0, z: 60 };
  const hit = snapTape({ x: 50, y: 2 }, [[a, b]], p => p === a ? { x: 0, y: 0, w: 1 } : { x: 100, y: 0, w: 2 });
  close(hit.point.x, 10); close(hit.point.z, 20);
  const zoomed = snapTape({ x: 200, y: 9 }, [[a, b]], p => ({ x: p.x * 10, y: 0, w: 1 }));
  close(zoomed.point.x, 20);
});

test('push/pull and scale open numeric input only for a click on geometry, never after a drag or cancel', () => {
  assert.equal(numericToolClick({ kind: 'push', moved: false }), true);
  assert.equal(numericToolClick({ kind: 'gumball', grip: 'scale', numeric: true, moved: false }), true);
  assert.equal(numericToolClick({ kind: 'push', moved: true }), false);
  assert.equal(numericToolClick({ kind: 'gumball', grip: 'scale', numeric: true, moved: false, dragged: true }), false);
  assert.equal(numericToolClick({ kind: 'push', moved: false }, true), false);
  assert.equal(numericToolClick({ kind: 'gumball', grip: 'scale', moved: false }), false);
  assert.equal(numericToolClick({ kind: 'gumball', grip: 'free', numeric: true, moved: false }), false);
  assert.equal(numericToolClick(null), false);
});

test('numeric push/pull sets floors or an exact side length while keeping the opposite face fixed', () => {
  const b = { u: 0, v: 0, w: 10, d: 6, floors: 3, a: 90 };
  assert.deepEqual(numericPushBlock(b, 'top', '7').block, { ...b, floors: 7 });
  const wider = numericPushBlock(b, 'w+', '14.25').block;
  assert.equal(wider.w, 14.25);
  close(wider.u, 0);
  close(wider.v - wider.w / 2, -5, .006);
  const shorter = numericPushBlock({ ...b, a: 0 }, 'd-', '4').block;
  assert.equal(shorter.d, 4);
  assert.equal(shorter.v + shorter.d / 2, 3);
  assert.deepEqual(b, { u: 0, v: 0, w: 10, d: 6, floors: 3, a: 90 });
  for (const value of ['', 'Infinity', '-1', '0', '1001']) assert.ok(numericPushBlock(b, 'w+', value).error);
  for (const value of ['2.5', '201', '0']) assert.ok(numericPushBlock(b, 'top', value).error);
});

test('numeric scaling uses the drag transform for selected blocks and rejects impossible sizes', () => {
  const blocks = [{ u: -10, v: 0, w: 10, d: 6, floors: 3 }, { u: 10, v: 0, w: 8, d: 4, floors: 5 }];
  const center = { u: 0, v: 0 };
  const result = numericScaleBlocks(blocks, [0, 1], center, '1.25');
  assert.deepEqual(result.blocks, scaleBlocks(blocks, [0, 1], center, 1.25));
  assert.equal(result.blocks[1].floors, 5);
  assert.equal(numericScaleBlocks(blocks, [0], center, '.5').blocks[1], blocks[1]);
  for (const value of ['', '-1', '0', 'NaN', 'Infinity', '.01', '1000']) {
    assert.ok(numericScaleBlocks(blocks, [0, 1], center, value).error);
  }
});

test('a plan looks straight down and masses lie flat; leaning raises them', () => {
  const plan = cameraFor({ x: 10, y: 20, span: 100, tilt: TILT.plan, turn: 0 });
  close(plan.position[0], 10);
  close(plan.position[1], 20);
  assert.deepEqual(plan.target, [10, 20, 0]);
  assert.ok(riseFor(0) < 0.01 && riseFor(TILT.persp) === 1);
  const axo = cameraFor({ x: 0, y: 0, span: 100, tilt: TILT.persp, turn: 0 });
  assert.ok(axo.position[1] < 0, 'the viewer stands south of the target when facing north');
});

test('zooming keeps the point under the cursor and stays within limits', () => {
  const v = zoomAround({ x: 0, y: 0, span: 100, tilt: 0, turn: 0 }, 50, 0, 0.5);
  assert.equal(v.span, 50);
  close(v.x, 25);
  assert.equal(zoomAround(v, 0, 0, 1e-6).span, 12);
  assert.equal(drawingScale(100, 400), '1:945');
  assert.equal(lerpView({ x: 0, y: 0, span: 10, tilt: 0, turn: 350 }, { x: 0, y: 0, span: 10, tilt: 0, turn: 10 }, 0.5).turn, 360);
});

test('screen scale matches the projection instead of rounding to a standard ratio', () => {
  const height = 600, span = 100;
  assert.equal(drawingScale(span, height), '1:630');
  const exact = scaleSpan('1:500', height);
  close(exact.span, 79.375);
  assert.equal(drawingScale(exact.span, height), '1:500');
  close(scaleSpan('250', height).span, exact.span / 2);
  assert.equal(drawingScale(exact.span, height / 2), '1:1000');
  for (const value of ['', '0', '-1', '1:0', '2:500', 'Infinity', '1', '1000000']) assert.ok(scaleSpan(value, height).error);
  assert.ok(scaleSpan('500', 0).error);
  const bar = scaleBar(span, height);
  close(bar.pixels / height * span, bar.metres);
  assert.ok(bar.pixels >= 40 && bar.pixels <= 100);
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
  assert.ok(folded(TILT.persp) && folded(MAX_TILT));
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

test('the selection bar picks the schemes on the table and offers a comparison for two or more', () => {
  const board = {
    papers: [{ id: 'site', kind: 'site' }, { id: 'a', kind: 'mass' }, { id: 'n', kind: 'note' }, { id: 'b', kind: 'mass' }],
    tray: [{ id: 'ai', kind: 'mass' }],
  };
  assert.deepEqual(massIds(board), ['a', 'b'], 'schemes still in the AI section are not picked');
  assert.deepEqual(massIds(null), []);
  assert.equal(canCompare(['a', 'n'], board), false);
  assert.equal(canCompare(['a', 'ai'], board), true, 'a scheme in the AI section can be compared too');
  assert.equal(addQuestion('', COMPARE_QUESTION), COMPARE_QUESTION);
  assert.equal(addQuestion('북측 일조도', COMPARE_QUESTION), `북측 일조도\n${COMPARE_QUESTION}`, 'what was typed stays');
  assert.equal(addQuestion('그대로', ''), '그대로');
});

test('undo sends the inverse of the last step, redo sends it again, a new edit drops the redo', () => {
  const note = { id: 'n1', kind: 'note', text: '', x: 0, y: 0 };
  let h = recordStep(createHistory(), [{ op: 'add', paper: note }]);
  h = recordStep(h, [
    { op: 'update', id: 'n1', before: { x: 0, y: 0 }, after: { x: 5, y: 2 } },
    { op: 'update', id: 'm1', before: { x: 1, y: 1 }, after: { x: 6, y: 3 } },
  ]);
  assert.equal(h.past.length, 2);
  let out = undoStep(h);
  assert.deepEqual(out.step, [
    { op: 'update', id: 'm1', before: { x: 6, y: 3 }, after: { x: 1, y: 1 } },
    { op: 'update', id: 'n1', before: { x: 5, y: 2 }, after: { x: 0, y: 0 } },
  ], 'a drag of two papers comes back as one step, last edit first');
  out = undoStep(out.history);
  assert.deepEqual(out.step, [{ op: 'remove', paper: note }], 'undoing an added paper removes it');
  assert.equal(undoStep(out.history).step, null, 'nothing left to undo');
  out = redoStep(out.history);
  assert.deepEqual(out.step, [{ op: 'add', paper: note }]);
  assert.equal(out.history.future.length, 1);
  const fresh = recordStep(out.history, [{ op: 'update', id: 'n1', before: { text: '' }, after: { text: '메모' } }]);
  assert.deepEqual(fresh.future, [], 'a new edit after undo drops what could be redone');
  assert.deepEqual(invertStep(invertStep(h.past[1])), h.past[1]);
});

test('history keeps only edits that change something and papers that can come back', () => {
  let h = recordStep(createHistory(), [{ op: 'update', id: 'a', before: { x: 1 }, after: { x: 1 } }]);
  assert.deepEqual(h, createHistory(), 'a click without a move is not a step');
  h = recordStep(h, [{ op: 'remove', paper: { id: 'ai-expert-1', kind: 'expert' } }, { op: 'remove', paper: { id: 'site', kind: 'site' } }]);
  assert.deepEqual(h.past, [], 'an expert result or the site paper cannot be laid again by the screen');
  for (let i = 0; i < HISTORY_LIMIT + 5; i += 1) h = recordStep(h, [{ op: 'update', id: 'a', before: { x: i }, after: { x: i + 1 } }]);
  assert.equal(h.past.length, HISTORY_LIMIT);
  assert.equal(h.past[0][0].before.x, 5, 'the oldest steps go first');
  assert.deepEqual(changedFields({ x: 1, y: 2, strokes: [[0, 0]] }, { x: 1, y: 3, strokes: [[0, 0]] }), { before: { y: 2 }, after: { y: 3 } });
});

test('a card draws the lots and the scheme\'s blocks in the site frame, with a scale bar', () => {
  const site = { plan: { parcels: [{ rings: [[[-20, -10], [20, -10], [20, 10], [-20, 10]]] }], frame: { x: 0, y: 0, angle: Math.PI / 2 } } };
  const mass = { kind: 'mass', blocks: [{ u: 0, v: 0, w: 10, d: 4, floors: 5 }] };
  const plan = planDrawing(site, mass);
  assert.equal(plan.lots.length, 1);
  assert.equal(plan.lots[0], 'M-20.00 10.00 L20.00 10.00 L20.00 -10.00 L-20.00 -10.00 Z', 'north is up: y is flipped');
  assert.equal(plan.blocks.length, 1);
  assert.equal(plan.blocks[0].floors, 5);
  close(plan.blocks[0].x, 0);
  const [, , w, h] = plan.viewBox.split(' ').map(Number);
  assert.equal(w, 52, 'the lot plus 6 m each side');
  assert.equal(h, 40, 'the lot plus 6 m each side and 8 m for the scale bar');
  assert.equal(plan.scale.label, '10m');
  const turned = planDrawing({ plan: { parcels: [], frame: { x: 0, y: 0, angle: Math.PI / 2 } } }, mass);
  const xs = turned.blocks[0].d.match(/-?\d+\.\d+/g).map(Number).filter((_, i) => i % 2 === 0);
  assert.equal(Math.max(...xs) - Math.min(...xs), 4, 'u runs north here, so the 10 m side stands upright');
  assert.equal(planDrawing({ plan: null }, { kind: 'note' }), null, 'nothing to draw');
  assert.equal(planDrawing(null, null), null);
  assert.ok(planDrawing(null, mass), 'a scheme without site facts still draws, u east and v north');
});

test('a left drag on empty table picks papers with a box, window or crossing as in Rhino', () => {
  // a sits wholly inside the box below; b sticks out of its right side; c is far away.
  const items = [
    { id: 'a', left: 20, top: 20, right: 60, bottom: 60 },
    { id: 'b', left: 80, top: 20, right: 140, bottom: 60 },
    { id: 'c', left: 300, top: 300, right: 340, bottom: 340 },
  ];
  const tl = { x: 10, y: 10 };
  const br = { x: 100, y: 100 };
  // Left to right (window): only what lies wholly inside, replacing the selection.
  assert.equal(boxMode(tl, br), 'window');
  assert.deepEqual(boxPick(['c'], tl, br, items), ['a']);
  // Right to left (crossing): whatever the box touches; dragging up or down does not matter.
  assert.equal(boxMode(br, tl), 'crossing');
  assert.deepEqual(boxPick([], br, tl, items), ['a', 'b']);
  assert.deepEqual(boxPick([], { x: 100, y: 10 }, { x: 10, y: 100 }, items), ['a', 'b']);
  // Shift adds to the selection, Ctrl takes away.
  assert.deepEqual(boxPick(['c'], tl, br, items, { add: true }), ['c', 'a']);
  assert.deepEqual(boxPick(['a', 'b', 'c'], br, tl, items, { remove: true }), ['c']);
  // A scheme counts once though both its paper and its buildings fall in the box, and a window
  // takes it when one of its buildings lies wholly inside, wherever its paper is.
  const scheme = [...items, { id: 'm', left: 30, top: 70, right: 50, bottom: 90 }, { id: 'm', left: 70, top: 70, right: 90, bottom: 90 }, { id: 'm', left: 500, top: 500, right: 600, bottom: 560 }];
  assert.deepEqual(boxPick([], tl, br, scheme), ['a', 'm']);
  assert.deepEqual(boxPick([], br, tl, scheme), ['a', 'b', 'm']);
  // Never more than one message may carry.
  const many = Array.from({ length: 12 }, (_, i) => ({ id: `p${i}`, left: 20 + i, top: 20, right: 30 + i, bottom: 30 }));
  assert.equal(boxPick([], tl, br, many).length, MAX_CONTEXT);
});

test('each building of a scheme is picked on its own', () => {
  assert.equal(blockKey('mass-1', 2), 'mass-1#2');
  assert.deepEqual(parseBlockKey('ai-mass-7b#0'), { id: 'ai-mass-7b', index: 0 });
  const papers = [
    { id: 'a', kind: 'mass', blocks: [{}, {}, {}] },
    { id: 'b', kind: 'mass', blocks: [{}] },
    { id: 'n', kind: 'note' },
  ];
  // Grouped by scheme; blocks no longer there (an undo, a deleted paper) drop out.
  const groups = pickedBlocks(papers, ['a#2', 'b#0', 'a#0', 'a#5', 'gone#0', 'n#0']);
  assert.deepEqual(groups.map((g) => [g.paper.id, g.indices]), [['a', [2, 0]], ['b', [0]]]);
  // A box may pick any number of blocks, though papers stop at what one message carries.
  const many = Array.from({ length: 12 }, (_, i) => ({ id: `a#${i}`, left: 20 + i, top: 20, right: 30 + i, bottom: 30 }));
  assert.equal(boxPick([], { x: 10, y: 10 }, { x: 100, y: 100 }, many, { limit: Infinity }).length, 12);
});

test('the gumball edits the picked blocks only: move along u and v, size, floors', () => {
  // A move on the table turns into the site's frame: with the frame turned 90°, east is −v.
  const turned = { x: 0, y: 0, angle: Math.PI / 2 };
  const east = frameDelta(turned, 10, 0);
  close(east.du, 0);
  close(east.dv, -10);
  const north = frameDelta(turned, 0, 4);
  close(north.du, 4);
  close(north.dv, 0);
  // Picked blocks keep their places to one another, moved in steps of 10 cm; the rest stay.
  const blocks = [{ u: 0, v: 0, w: 10, d: 10, floors: 3 }, { u: 15, v: 2, w: 8, d: 8, floors: 5 }];
  assert.deepEqual(editBlocks(blocks, [0, 1], { du: 3.04, dv: -1.26 }).map((b) => [b.u, b.v]), [[3, -1.3], [18, 0.7]]);
  const one = editBlocks(blocks, [1], { du: 5 });
  assert.equal(one[0], blocks[0]);
  assert.equal(one[1].u, 20);
  // Sizes in 10 cm steps, never under 1 m; floors whole, 1 to 200.
  assert.deepEqual(editBlocks(blocks, [0], { dw: 2.46, dd: -30 })[0], { u: 0, v: 0, w: 12.5, d: 1, floors: 3 });
  assert.equal(editBlocks(blocks, [0], { df: 1.6 })[0].floors, 5);
  assert.equal(editBlocks(blocks, [0], { df: -9 })[0].floors, 1);
  assert.equal(editBlocks(blocks, [0], { df: 999 })[0].floors, 200);
  // An arrow follows the pointer along itself only, and an arrow seen end-on does not move.
  close(axisDrag([10, 0], 50, 30), 5);
  close(axisDrag([0, -4], 0, -20), 5);
  assert.equal(axisDrag([0.1, 0.2], 50, 50), 0);
  // The gumball stands in the middle of all the picked buildings, or nowhere without any.
  assert.deepEqual(blocksCenter(null, blocks), { x: 7, y: 0.5 }); // x −5…19, y −5…6
  assert.equal(blocksCenter(null, []), null);
});

test("SketchUp's tools on blocks: rectangle, push/pull, copy, rotate, scale", () => {
  const frame = { x: 100, y: 50, angle: Math.PI / 2 }; // u points north on the table
  // A rectangle dragged on the table lies square to the site, one floor high; too small is nothing.
  close(toFrame(frame, 100, 60).u, 10);
  close(toFrame(frame, 90, 50).v, 10);
  assert.deepEqual(rectBlock(frame, { x: 100, y: 50 }, { x: 90, y: 70 }), { u: 10, v: 5, w: 20, d: 10, floors: 1 });
  assert.equal(rectBlock(frame, { x: 100, y: 50 }, { x: 99.5, y: 70 }), null);
  // Push/pull: the top adds floors; a side moves out while the opposite side stays put.
  const b = { u: 0, v: 0, w: 10, d: 6, floors: 2 };
  assert.equal(pushBlock(b, 'top', 8.4, 4.2).floors, 4);
  assert.deepEqual(pushBlock(b, 'w+', 4), { u: 2, v: 0, w: 14, d: 6, floors: 2 }); // −u side stays at −5
  assert.deepEqual(pushBlock(b, 'd-', 2), { u: 0, v: -1, w: 10, d: 8, floors: 2 }); // +v side stays at 3
  assert.equal(pushBlock(b, 'w-', -50).w, 1);
  // A turned block pushes along its own side: turned 90°, its +u face looks along +v.
  const turned = pushBlock({ ...b, a: 90 }, 'w+', 4);
  close(turned.u, 0);
  close(turned.v, 2);
  // Copies go after the others and leave the originals where they were.
  const two = [b, { u: 20, v: 0, w: 8, d: 8, floors: 3 }];
  const copied = copyBlocks(two, [1], 5, 0);
  assert.deepEqual(copied.indices, [2]);
  assert.equal(copied.blocks[1], two[1]);
  assert.equal(copied.blocks[2].u, 25);
  // Rotate about a point: the middles go round it and each block turns with them.
  const r = turnBlocks(two, [0, 1], { u: 10, v: 0 }, 90);
  close(r[0].u, 10);
  close(r[0].v, -10);
  assert.equal(r[0].a, 90);
  close(r[1].v, 10);
  assert.equal(turnBlocks([{ ...b, a: 170 }], [0], { u: 0, v: 0 }, 20)[0].a, -170); // kept within ±180
  assert.equal('a' in turnBlocks([{ ...b, a: 90 }], [0], { u: 0, v: 0 }, -90)[0], false); // unturned again
  // Scale about a point: middles spread and sizes follow; floors stay; never under 1 m.
  const s = scaleBlocks(two, [0, 1], { u: 10, v: 0 }, 2);
  assert.deepEqual([s[0].u, s[0].w, s[0].d, s[0].floors], [-10, 20, 12, 2]);
  assert.equal(scaleBlocks(two, [0], { u: 0, v: 0 }, 0.01)[0].w, 1);
  // The protractor keeps to 5° steps, or 1°.
  assert.equal(snapAngle(43), 45);
  assert.equal(snapAngle(43, 1), 43);
  // A turned block's footprint turns about its middle.
  const corners = blockCorners(null, { u: 0, v: 0, w: 10, d: 2, a: 90 });
  close(corners[0][0], 1);
  close(corners[0][1], -5);
});

test('the mouse works like Rhino: right drag orbits, a plan straight into 3D', () => {
  assert.equal(dragMode({ button: 2 }), 'orbit');
  assert.equal(orbitBy({ x: 0, y: 0, span: 100, tilt: TILT.plan, turn: 0 }, 0, -100).tilt, 25); // up from a plan
  assert.equal(dragMode({ button: 2, shift: true }), 'pan');
  assert.equal(dragMode({ button: 2, ctrl: true }), 'zoom');
  assert.equal(dragMode({ button: 1, tilt: TILT.persp }), 'pan');
  assert.equal(dragMode({ button: 0, alt: true }), 'orbit');
  assert.equal(dragMode({ button: 0, tilt: TILT.persp }), null); // the left button selects, moves and draws
  // Rolling the wheel forward zooms in, back zooms out, by the same step either way.
  const inStep = wheelZoom(-100);
  assert.ok(inStep < 1 && inStep > 0.8);
  close(inStep * wheelZoom(100), 1);
  close(wheelZoom(-3, 1), inStep * wheelZoom(52)); // a line-mode wheel counts 16 px a line
  assert.ok(wheelZoom(10, 0, true) > wheelZoom(10)); // a trackpad pinch steps further per pixel
});

test('an orbit drag turns the model with the hand, as in Rhino', () => {
  const v = { x: 0, y: 0, span: 100, tilt: TILT.persp, turn: 0 };
  // Dragging right: the near side of the table moves right on screen.
  const right = orbitBy(v, 100, 0);
  assert.ok(right.turn > v.turn);
  // Which way a table point between the viewer and the target moves on screen, from the camera itself.
  const screenX = (view, p) => {
    const c = cameraFor(view);
    const f = c.target.map((t, i) => t - c.position[i]);
    const r = [f[1] * c.up[2] - f[2] * c.up[1], f[2] * c.up[0] - f[0] * c.up[2], f[0] * c.up[1] - f[1] * c.up[0]];
    return p.reduce((s, q, i) => s + (q - c.position[i]) * r[i], 0);
  };
  const nearPoint = [0, -20, 0]; // south of the target, the viewer's side at turn 0
  assert.ok(screenX({ ...v, ...right }, nearPoint) > screenX(v, nearPoint));
  // Dragging down shows more of the top; up lowers the eye. Both stop at the limits.
  assert.ok(orbitBy(v, 0, 40).tilt < v.tilt);
  assert.ok(orbitBy(v, 0, -40).tilt > v.tilt);
  assert.equal(orbitBy(v, 0, 1e6).tilt, 0);
  assert.equal(orbitBy(v, 0, -1e6).tilt, MAX_TILT);
});

test('two views as in Rhino: the plan and one 3D view whose angle the mouse sets', () => {
  assert.equal(viewName(0), 'plan');
  assert.equal(viewName(20), '3d');
  assert.equal(viewName(70), '3d');
  // From a plan the 3D button stands the table up, turned a little; in 3D it leaves the angle alone.
  assert.deepEqual(viewFor('3d', { tilt: 0, turn: 0 }), { tilt: TILT.persp, turn: -30 });
  assert.deepEqual(viewFor('3d', { tilt: 0, turn: 40 }), { tilt: TILT.persp, turn: 40 });
  assert.equal(viewFor('3d', { tilt: 60, turn: 15 }), null);
  assert.deepEqual(viewFor('plan', { tilt: 60, turn: 15, z: 8 }), { tilt: 0, turn: 0, z: 0 });
  assert.deepEqual(Object.keys(TILT), ['plan', 'persp']);
});

test('the table lies down to 90° for elevations, and an elevation pans with the mouse', () => {
  assert.equal(MAX_TILT, 90);
  assert.equal(orbitBy({ x: 0, y: 0, span: 100, tilt: 80, turn: 0 }, 0, -1e6).tilt, 90);
  // At 90° the eye looks level along the table at the target, the table seen edge-on.
  const side = cameraFor({ x: 0, y: 0, span: 100, tilt: 90, turn: 0 });
  close(side.position[2], 0);
  close(side.up[2], 1);
  assert.ok(side.position[1] < 0);
  close(cameraFor({ x: 0, y: 0, span: 100, tilt: 90, turn: 0, z: 12 }).position[2], 12);
  // The camera turns about one fixed point at every angle: the target never moves with the tilt
  // and the eye stays at the same distance from it.
  for (const tilt of [0, 30, 60, 70, 75, 80, 85, 90]) {
    const c = cameraFor({ x: 3, y: 4, span: 100, tilt, turn: 20, z: 5 });
    assert.deepEqual(c.target, [3, 4, 5]);
    close(Math.hypot(...c.position.map((p, i) => p - c.target[i])), c.dist, 1e-6);
  }
  // The ground (grid, shadows, site outline) shows in 3D and fades away for an elevation.
  assert.equal(groundFor(TILT.persp), 1);
  assert.equal(groundFor(80), 1);
  assert.equal(groundFor(MAX_TILT), 0);
  // Pan on the screen: drag right and the picture goes right (the eye goes left, west at turn 0);
  // drag up and the picture goes up (the eye goes down the building), never under the table.
  const v = { x: 0, y: 0, span: 100, tilt: 90, turn: 0, z: 20 };
  const right = panBy(v, 50, 0, 500);
  close(right.x, -10);
  close(right.z, 20);
  const up = panBy(v, 0, -50, 500);
  close(up.z, 10);
  close(up.x, 0);
  assert.equal(panBy(v, 0, -5000, 500).z, 0);
  // In plan the same pan slides the table under the mouse without lifting it.
  const plan = panBy({ x: 0, y: 0, span: 100, tilt: 0, turn: 0 }, 0, 50, 500);
  close(plan.y, 10);
  close(plan.z, 0);
  close(lerpView(v, { ...v, z: 0 }, 0.5).z, 10);
});

test('a photo the server takes is uploaded as it is; others are redrawn as a smaller JPEG', () => {
  const MB = 1024 * 1024;
  assert.equal(photoPlan('image/jpeg', 3 * MB, 4032, 3024), 'keep'); // a phone photo
  assert.equal(photoPlan('image/png', 1 * MB, 1920, 1080), 'keep');
  assert.equal(photoPlan('image/jpeg', 12 * MB, 4000, 3000), 'shrink'); // too heavy
  assert.equal(photoPlan('image/png', 2 * MB, 9000, 6000), 'shrink'); // too large
  assert.equal(photoPlan('image/heic', 2 * MB, 4032, 3024), 'shrink'); // the server does not take it
  assert.equal(photoPlan('', 2 * MB, 100, 100), 'shrink');
  assert.equal(photoPlan('image/gif', 12 * MB, 800, 600), 'keep'); // an animation stays
  assert.equal(photoPlan('image/gif', 30 * MB, 800, 600), 'shrink');
  assert.deepEqual(shrunkSize(5120, 2560), { width: PHOTO_MAX_SIDE, height: 1280 });
  assert.deepEqual(shrunkSize(800, 600), { width: 800, height: 600 }); // never enlarged
});

test('a photo paper keeps the picture shape with its longest side at the chosen size', () => {
  assert.deepEqual(photoPaperSize(4032, 3024), { w: 300, h: 225 });
  assert.deepEqual(photoPaperSize(3024, 4032), { w: 225, h: 300 });
  assert.deepEqual(photoPaperSize(1000, 1000, 500), { w: 500, h: 500 });
  assert.deepEqual(photoPaperSize(10000, 100), { w: 300, h: 40 }); // a panorama is still something to grab
  assert.deepEqual(photoPaperSize(0, 0), { w: 300, h: 225 });
});

test('a photo is named after its file, and a pasted screenshot has no name', () => {
  assert.equal(photoTitle('대지 북측 전경.JPG'), '대지 북측 전경');
  assert.equal(photoTitle('sketch.v2.png'), 'sketch.v2');
  assert.equal(photoTitle('image.png'), '');
  assert.equal(photoTitle(''), '');
  assert.equal(photoTitle(`${'가'.repeat(200)}.jpg`).length, 120);
  assert.equal(paperName({ kind: 'photo', title: '' }), '사진');
  assert.equal(paperName({ kind: 'photo', title: '북측' }), '북측');
  assert.equal(KIND_LABELS.photo, '사진');
});

test('only pictures and PDFs are taken from what was dropped, a few at a time', () => {
  const file = (name, type) => ({ name, type });
  const got = pickPhotoFiles([file('a.jpg', 'image/jpeg'), file('b.pdf', 'application/pdf'), file('c.HEIC', ''), file('d.txt', '')]);
  assert.deepEqual(got.files.map((f) => f.name), ['a.jpg', 'b.pdf', 'c.HEIC']);
  assert.equal(got.skipped, 1);
  const many = pickPhotoFiles(Array.from({ length: 13 }, (_, i) => file(`${i}.png`, 'image/png')));
  assert.equal(many.files.length, MAX_PHOTOS_AT_ONCE);
  assert.equal(many.skipped, 3);
  assert.deepEqual(pickPhotoFiles(null), { files: [], skipped: 0 });
});

test('a removed photo can be undone (the server keeps its file)', () => {
  const photo = { id: 'photo-1', kind: 'photo', file: 'photo-1.jpg' };
  const history = recordStep(createHistory(), [{ op: 'remove', paper: photo }]);
  assert.equal(history.past.length, 1);
});

test('contour lines cut the ground grid at every interval, every fifth is an index line', async () => {
  const { contourLines, aroundNote, isEstimate } = await import('../../webui/app/board-model.js');
  // a 3 × 3 grid rising 1 m per 10 m to the north: z = 0, 1, 2 by row
  const terrain = { min: -10, step: 10, n: 3, z: [0, 0, 0, 1, 1, 1, 2, 2, 2] };
  const lines = contourLines(terrain, 0.5);
  assert.deepEqual(lines.map((l) => l.z), [0.5, 1, 1.5]);
  for (const s of lines.find((l) => l.z === 0.5).segments) { close(s[1], -5); close(s[3], -5); }
  assert.equal(contourLines(terrain, 0.2).find((l) => l.z === 1).index, true);
  assert.equal(contourLines(terrain, 0.2).find((l) => l.z === 0.6).index, false);
  assert.deepEqual(contourLines(null, 1), []);
  assert.deepEqual(contourLines(terrain, 0), []);

  const note = aroundNote({
    terrain_sources: [{ name: '국토지리정보원 등고선', date: '2026-10-01' }],
    building_source: { name: 'GIS건물통합정보', date: '2026-03-06' },
    counts: { ledger: 2, vworld: 0, estimate: 3, map_estimate: 1, unknown: 4 }, disclaimer: '측량 결과가 아닙니다.',
  });
  assert.match(note[0], /기준 2026-10-01/);
  assert.equal(note[1], '건물: GIS건물통합정보 (기준 2026-03-06)');
  assert.match(note[2], /건축물대장 높이 2동/);
  assert.match(note[2], /추정\(수치지형도 층수\) 1동/);
  assert.doesNotMatch(note[2], /건축물정보 높이/); // a source no building used is not listed
  assert.match(note[2], /높이 미확인 4동/);
  assert.equal(isEstimate({ height_source: 'map_estimate' }), true);
  assert.equal(isEstimate({ height_source: 'ledger' }), false);
  assert.ok(note.some((l) => l.includes('추정')) && note.at(-1) === '측량 결과가 아닙니다.');
  assert.match(aroundNote({ terrain_sources: [], counts: {} })[0], /평지/);
});

test('the idea board: text from a message, reordering, links and notes', async () => {
  const {
    ideaText, moveIdea, dropIdea, sameOrder, ideaPapers, linkPapers, pickedNotes, ideasInPlay, MAX_IDEA_TEXT, MAX_IDEA_PAPERS,
  } = await import('../../webui/app/board-model.js');
  assert.equal(ideaText('  중정을 중심으로 \n\n  동을 돌린다 '), '중정을 중심으로\n동을 돌린다');
  const long = ideaText('가'.repeat(700));
  assert.equal(long.length, MAX_IDEA_TEXT);
  assert.ok(long.endsWith('…'));
  assert.equal(ideaText(null), '');

  const ids = ['a', 'b', 'c'];
  assert.deepEqual(moveIdea(ids, 'b', -1), ['b', 'a', 'c']);
  assert.deepEqual(moveIdea(ids, 'c', 1), ids);
  assert.deepEqual(moveIdea(ids, 'x', 1), ids);
  assert.deepEqual(dropIdea(ids, 'c', 'a'), ['c', 'a', 'b']);
  assert.deepEqual(dropIdea(ids, 'a', 'c', true), ['b', 'c', 'a']);
  assert.deepEqual(dropIdea(ids, 'a', 'a'), ids);
  assert.ok(sameOrder(ids, ['a', 'b', 'c']) && !sameOrder(ids, ['a', 'c', 'b']));

  const board = {
    papers: [{ id: 'site', kind: 'site' }, { id: 'n1', kind: 'note', text: '  북측은 낮게 ' }, { id: 'n2', kind: 'note', text: ' ' }],
    tray: [{ id: 'm1', kind: 'mass', title: '안 A' }],
    ideas: [{ id: 'i1', text: 'x', papers: ['m1', 'gone'], off: false }, { id: 'i2', text: 'y', papers: [], off: true }],
  };
  assert.deepEqual(ideaPapers(board.ideas[0], board), [{ id: 'm1', name: '안 A' }]);
  assert.deepEqual(linkPapers(['a'], ['b', 'a']), ['a', 'b']);
  assert.equal(linkPapers([], Array.from({ length: 12 }, (_, i) => `p${i}`)).length, MAX_IDEA_PAPERS);
  assert.deepEqual(pickedNotes(['m1', 'n1', 'n2'], board), [{ id: 'n1', text: '북측은 낮게' }]);
  assert.equal(ideasInPlay(board), 1);
  assert.equal(ideasInPlay(null), 0);
});

test('the floating idea window holds to its nearest corner and stays inside the table', async () => {
  const { floatState, floatPlace, floatAnchor, IDEA_FLOAT } = await import('../../webui/app/board-model.js');
  const fresh = floatState(null);
  assert.deepEqual(fresh, { pinned: false, corner: 'tr', dx: IDEA_FLOAT.dx, dy: IDEA_FLOAT.dy, width: IDEA_FLOAT.width, height: IDEA_FLOAT.height });
  const broken = floatState({ pinned: 'yes', corner: 'middle', dx: -5, dy: 'x', width: 50, height: NaN });
  assert.equal(broken.pinned, false);
  assert.equal(floatState({ pinned: true }).pinned, true);
  assert.equal(broken.corner, 'tr');
  assert.equal(broken.dx, IDEA_FLOAT.dx);
  assert.equal(broken.width, IDEA_FLOAT.minWidth); // never narrower than usable
  assert.equal(broken.height, IDEA_FLOAT.height);

  const box = { width: 1000, height: 700 };
  const size = { width: 300, height: 400 };
  // top right: measured from the right edge, so it stays there when the table grows
  assert.deepEqual(floatPlace({ corner: 'tr', dx: 20, dy: 10 }, size, box), { left: 680, top: 10, width: 300, height: 400 });
  assert.deepEqual(floatPlace({ corner: 'tr', dx: 20, dy: 10 }, size, { width: 1200, height: 700 }).left, 880);
  assert.deepEqual(floatPlace({ corner: 'bl', dx: 30, dy: 40 }, size, box), { left: 30, top: 260, width: 300, height: 400 });
  // a table smaller than the window: shrunk to fit, kept off the edges
  const small = floatPlace({ corner: 'br', dx: 500, dy: 500 }, size, { width: 200, height: 150 });
  assert.deepEqual(small, { left: IDEA_FLOAT.margin, top: IDEA_FLOAT.margin, width: 188, height: 138 });

  // dropped nearer the bottom left: held to that corner, gaps measured to its edges
  assert.deepEqual(floatAnchor({ left: 40, top: 380, width: 300, height: 300 }, box), { corner: 'bl', dx: 40, dy: 20 });
  assert.deepEqual(floatAnchor({ left: 650, top: 12, width: 300, height: 300 }, box), { corner: 'tr', dx: 50, dy: 12 });
  // placing again from the anchor puts it back where it was dropped
  const rect = { left: 612, top: 345, width: 300, height: 320 };
  const again = floatPlace(floatAnchor(rect, box), rect, box);
  assert.deepEqual([again.left, again.top], [612, 345]);
});

test('the surroundings legend lists only the ground kinds and building kinds that are drawn', async () => {
  const { aroundLegend } = await import('../../webui/app/board-model.js');
  // no 1:5,000 areas here (마포): the grid is all 대지, so no 도로·인도·수계 chips
  const plain = aroundLegend({ terrain: { classes: 'gggg' }, buildings: [{ height_source: 'ledger' }], counts: {} });
  assert.deepEqual(plain.map(([k]) => k), ['g']);
  const full = aroundLegend({
    terrain: { classes: 'grsw' }, buildings: [{ height_source: 'map_estimate' }], counts: { unknown: 2 },
  });
  assert.deepEqual(full.map(([k]) => k), ['g', 'r', 's', 'w', 'guess', 'unknown']);
  assert.deepEqual(aroundLegend({ terrain: null, buildings: [], counts: {} }), [['g', '대지']]); // flat
  assert.deepEqual(aroundLegend(null), []);
});

test('a block on the board stands on the ground under it only while the surroundings are shown', async () => {
  const { DraftingTable } = await import('../../webui/app/table.js');
  const { massBase, blockCorners } = await import('../../webui/app/board-model.js');
  // ground falling 1 m per 5 m eastward over ±10 m
  const terrain = { min: -10, n: 5, step: 5, z: Array.from({ length: 25 }, (_, k) => -(-10 + (k % 5) * 5) / 5) };
  const t = Object.create(DraftingTable.prototype);
  const frame = { x: 0, y: 0, angle: 0 };
  const block = { u: 4, v: 0, w: 4, d: 4, floors: 3 };
  Object.assign(t, { aroundOn: false, around: { terrain } });
  assert.equal(t.blockBase(frame, block), 0); // surroundings off: on the table
  t.aroundOn = true;
  assert.equal(t.blockBase(frame, block), massBase(blockCorners(frame, block), terrain));
  assert.equal(t.blockBase(frame, block), -1.2); // its east edge at x = 6
  t.around = null;
  assert.equal(t.blockBase(frame, block), 0);
});

test('a click on a building around the site says where its height and outline came from', async () => {
  const { buildingInfo } = await import('../../webui/app/board-model.js');
  const hall = buildingInfo({ name: '서울특별시 청사', height: 53.5, floors: 13, height_source: 'ledger',
    match: { source: 'map', dong: '신관', ratio: 0.99 } });
  assert.equal(hall, '서울특별시 청사 · 53.5m · 13층 · 건축물대장 높이 · 대장 신관 ↔ 1:5,000 수치지형도 외곽선, 면적비 0.99');
  const annex = buildingInfo({ name: '', height: 20, height_source: 'ledger', match: { source: 'vworld', dong: '별관', ratio: 1 }, display_only: true });
  assert.match(annex, /^이름 없는 건물 · 20\.0m · .*브이월드\(화면 전용\) 외곽선, 면적비 1\.00 · 파일로 내보내지 않음$/);
  assert.match(buildingInfo({ name: 'x', height: 9.9, height_source: 'estimate', match: null }), /대장과 짝지은 외곽선 아님/);
  assert.equal(buildingInfo(null), '');
});

test('the board masses go on the VWorld 3D map as lon/lat polygons standing on the ground', async () => {
  const { toLonLat, massPolygons, siteRings, hideBuildings, EARTH_RADIUS, MAX_HIDDEN } = await import('../../webui/app/board-model.js');
  const origin = { lon: 126.9787396, lat: 37.56782459 };
  const k = Math.PI / 180;
  const [lon, lat] = toLonLat(origin, 100, 50); // 100 m east, 50 m north
  close((lon - origin.lon) * EARTH_RADIUS * k * Math.cos(origin.lat * k), 100, 1e-6);
  close((lat - origin.lat) * EARTH_RADIUS * k, 50, 1e-6);
  assert.deepEqual(toLonLat(origin, 0, 0), [origin.lon, origin.lat]);

  const plan = { origin, frame: { x: 0, y: 0, angle: 0 }, parcels: [{ rings: [[[-10, -10], [10, -10], [10, 10], [-10, 10]]] }] };
  const paper = { floor_height: 3, blocks: [{ u: 0, v: 0, w: 20, d: 30, floors: 10 }, { u: 30, v: 0, w: 10, d: 10, floors: 2 }] };
  const [a, b] = massPolygons(paper, plan);
  assert.equal(a.height, 30) ; assert.equal(b.height, 6); assert.equal(a.floors, 10);
  assert.equal(a.ring.length, 4);
  close((a.ring[1][0] - a.ring[0][0]) * EARTH_RADIUS * k * Math.cos(origin.lat * k), 20, 1e-6); // 20 m wide
  close((a.ring[2][1] - a.ring[1][1]) * EARTH_RADIUS * k, 30, 1e-6); // 30 m deep
  assert.equal(massPolygons({ blocks: [{ u: 0, v: 0, w: 1, d: 1, floors: 1 }] }, plan)[0].height, 4.2); // default storey
  assert.deepEqual(massPolygons(paper, { parcels: [] }), []); // no site boundary: nowhere to stand
  assert.deepEqual(massPolygons(null, plan), []);
  assert.equal(siteRings(plan)[0].length, 4);
  close(siteRings(plan)[0][2][1], toLonLat(origin, 10, 10)[1], 1e-12);

  assert.deepEqual(hideBuildings(['a'], ['b', 'a', '', null]), ['a', 'b']);
  assert.equal(hideBuildings([], Array.from({ length: 400 }, (_, i) => `m${i}`)).length, MAX_HIDDEN);
});

test('the VWorld map look (white model, no ground photo) is read back safely', async () => {
  const { readLook } = await import('../../webui/app/board-model.js');
  assert.deepEqual(readLook(JSON.stringify({ white: true, plain: false })), { white: true, plain: false, noNames: false });
  assert.deepEqual(readLook(JSON.stringify({ white: true, plain: true, noNames: true })), { white: true, plain: true, noNames: true });
  assert.deepEqual(readLook(null), { white: false, plain: false, noNames: false }); // nothing stored: photos and names on
  assert.deepEqual(readLook('not json'), { white: false, plain: false, noNames: false });
  assert.deepEqual(readLook(JSON.stringify({ white: 'yes', plain: 1, noNames: 'y' })), { white: false, plain: false, noNames: false }); // only true counts
});

test('hiding VWorld buildings goes step by step, with undo and redo', async () => {
  const { startHistory, commitHistory, undoHistory, redoHistory, hideBuildings, MAX_HIDE_STEPS } = await import('../../webui/app/board-model.js');
  let h = startHistory(['old']);
  h = commitHistory(h, hideBuildings(h.present, ['a'])); // a click, confirmed
  h = commitHistory(h, hideBuildings(h.present, ['b', 'c'])); // 대지 위 건물 숨기기
  assert.deepEqual(h.present, ['old', 'a', 'b', 'c']);
  assert.equal(commitHistory(h, ['old', 'a', 'b', 'c']), h); // the same list is no step
  h = commitHistory(h, []); // 숨긴 건물 모두 보이기
  h = undoHistory(h);
  assert.deepEqual(h.present, ['old', 'a', 'b', 'c']); // Ctrl+Z brings them back as they were
  h = undoHistory(undoHistory(h));
  assert.deepEqual(h.present, ['old']); // back to what the project had
  assert.equal(undoHistory(h), h); // nothing more to undo
  h = redoHistory(h);
  assert.deepEqual(h.present, ['old', 'a']);
  h = commitHistory(h, hideBuildings(h.present, ['d'])); // a new step drops what was undone
  assert.equal(redoHistory(h), h);
  assert.deepEqual(h.present, ['old', 'a', 'd']);
  let long = startHistory([]);
  for (let i = 0; i < MAX_HIDE_STEPS + 10; i += 1) long = commitHistory(long, [...long.present, `m${i}`]);
  assert.equal(long.past.length, MAX_HIDE_STEPS);
});

test('keys on the VWorld map: Delete hides the picked building, Esc cancels, Ctrl+Z undoes', async () => {
  const { hideKey } = await import('../../webui/app/board-model.js');
  assert.equal(hideKey({ key: 'Delete' }, true), 'hide');
  assert.equal(hideKey({ key: 'Backspace' }, true), 'hide');
  assert.equal(hideKey({ key: 'Delete' }, false), ''); // nothing picked: the key is not ours
  assert.equal(hideKey({ key: 'Escape' }, true), 'cancel');
  assert.equal(hideKey({ key: 'Escape' }, false), '');
  assert.equal(hideKey({ key: 'z', ctrl: true }, false), 'undo');
  assert.equal(hideKey({ key: 'Z', meta: true }, false), 'undo');
  assert.equal(hideKey({ key: 'Z', ctrl: true, shift: true }, false), 'redo');
  assert.equal(hideKey({ key: 'y', ctrl: true }, false), 'redo');
  assert.equal(hideKey({ key: 'c', ctrl: true }, true), '');
  assert.equal(hideKey({ key: 'a' }, true), '');
});

test('a corner drag resizes a paper about its opposite corner, within the limits', () => {
  const from = { x: 0, y: 0, w: 300, h: 200 }; // 30 m × 20 m, corners at x ±15, y ±10
  // South-east corner to (30, -30): the north-west corner (-15, 10) stays.
  assert.deepEqual(resizedPaper(from, 'se', { x: 30, y: -30 }), { x: 7.5, y: -10, w: 450, h: 400 });
  // North-west corner pulled in: the south-east corner (15, -10) stays.
  const nw = resizedPaper(from, 'nw', { x: 5, y: 0 });
  assert.deepEqual([nw.w, nw.h], [100, 100]);
  close(nw.x + (nw.w * PX) / 2, 15); close(nw.y - (nw.h * PX) / 2, -10);
  // Dragged past the opposite corner or far away: held at the smallest and largest size.
  const tiny = resizedPaper(from, 'ne', { x: -100, y: -100 });
  assert.deepEqual([tiny.w, tiny.h], [PAPER_LIMITS.min, PAPER_LIMITS.min]);
  close(tiny.x - (tiny.w * PX) / 2, -15); close(tiny.y - (tiny.h * PX) / 2, -10); // the south-west corner stays
  const huge = resizedPaper(from, 'sw', { x: -1e6, y: -1e6 });
  assert.deepEqual([huge.w, huge.h], [PAPER_LIMITS.max, PAPER_LIMITS.max]);
});

test('a photo or PDF keeps its shape when a corner is dragged', () => {
  const from = { x: 0, y: 0, w: 300, h: 200 };
  const r = resizedPaper(from, 'se', { x: 45, y: -12 }, { ratio: true }); // pulled mostly sideways
  assert.deepEqual([r.w, r.h], [600, 400]);
  close(r.x - (r.w * PX) / 2, -15); close(r.y + (r.h * PX) / 2, 10);
  const small = resizedPaper(from, 'se', { x: -14, y: 9 }, { ratio: true });
  assert.equal(small.h, PAPER_LIMITS.min); assert.equal(small.w, 90); // the short side stops at the limit
  const big = resizedPaper(from, 'se', { x: 1e6, y: 0 }, { ratio: true });
  assert.equal(big.w, PAPER_LIMITS.max); assert.ok(Math.abs(big.h - PAPER_LIMITS.max * 2 / 3) <= 1);
});

test('every paper but a tracing sheet or a folded one can be resized', () => {
  for (const kind of ['site', 'mass', 'note', 'expert', 'photo']) assert.ok(resizable({ kind }), kind);
  assert.ok(!resizable({ kind: 'tracing' }));
  assert.ok(!resizable({ kind: 'photo', folded: true }));
  assert.ok(!resizable(null));
});

test('a PDF is taken as it is and its page is drawn as sharp as it is seen', () => {
  assert.ok(isPdfFile({ type: 'application/pdf', name: 'a' }));
  assert.ok(isPdfFile({ type: '', name: '평면도.PDF' }));
  assert.ok(!isPdfFile({ type: 'image/png', name: 'x.pdf' }));
  assert.ok(isPdfPaper({ kind: 'photo', file: 'photo-0a1b2c3d.pdf' }));
  assert.ok(!isPdfPaper({ kind: 'photo', file: 'photo-0a1b2c3d.png' }));
  const files = [{ type: 'application/pdf', name: 'plan.pdf' }, { type: 'text/plain', name: 'x.txt' }, { type: 'image/png', name: 'p.png' }];
  assert.deepEqual(pickPhotoFiles(files), { files: [files[0], files[2]], skipped: 1 });

  // 300 × 212 px of paper shown 4 screen px per paper px on a 2× screen: 2400 device px across.
  assert.deepEqual(pdfCanvasSize(300, 212, 4, 2), { width: 2400, height: 1696 });
  // Zoomed far in, held at the longest side and the area a canvas can take.
  const capped = pdfCanvasSize(300, 300, 100, 2);
  assert.equal(capped.width, capped.height);
  assert.ok(capped.width <= PDF_MAX_SIDE && capped.width * capped.height <= PDF_MAX_AREA + 2 * capped.width);
  assert.equal(pdfCanvasSize(3000, 100, 10, 1).width, PDF_MAX_SIDE);
  // Zoomed out it is drawn only as large as it is seen.
  assert.deepEqual(pdfCanvasSize(300, 200, 0.5, 1), { width: 150, height: 100 });

  assert.ok(pdfNeedsRedraw(null, { width: 10 }));
  assert.ok(!pdfNeedsRedraw({ width: 1000 }, { width: 1100 })); // a little sharper: not worth a redraw
  assert.ok(pdfNeedsRedraw({ width: 1000 }, { width: 1200 })); // it would blur
  assert.ok(pdfNeedsRedraw({ width: 1000 }, { width: 300 })); // much smaller: free the memory
});

test('a round range leaves the ground cells outside it out of the mesh and the contour lines', async () => {
  const { contourLines, terrainFaces, cellOpen, RANGE_SIZES, RANGE_SHAPES, OUTSIDE } = await import('../../webui/app/board-model.js');
  // 3 × 3 points rising northward; the north-east corner point is outside the circle
  const z = [0, 0, 0, 1, 1, 1, 2, 2, 2];
  const square = { min: -10, step: 10, n: 3, z, classes: 'ggggggggg' };
  const round = { ...square, classes: `gggggggg${OUTSIDE}` };
  assert.equal(terrainFaces(square).length, 4 * 6); // 4 cells, 2 triangles each
  assert.equal(terrainFaces(round).length, 3 * 6); // the north-east cell is left out
  assert.equal(cellOpen(round, 1, 1), false);
  assert.equal(cellOpen(round, 0, 1), true);
  assert.equal(cellOpen({ ...square, classes: undefined }, 1, 1), true);
  // PlaneGeometry's vertex order: row 0 is the north row (j = n - 1)
  const top = terrainFaces(square).slice(0, 6);
  assert.deepEqual(top, [0, 3, 1, 3, 4, 1]);
  const segs = (t) => contourLines(t, 0.5).flatMap((l) => l.segments);
  assert.ok(segs(round).length < segs(square).length);
  assert.ok(segs(round).every(([x1, y1, x2, y2]) => !(x1 > 0 && y1 > 0 && x2 > 0 && y2 > 0))); // none in the cut cell
  assert.deepEqual(RANGE_SIZES.map((s) => [s.key, s.radius]), [['small', 100], ['medium', 200], ['large', 300]]);
  assert.deepEqual(RANGE_SHAPES.map((s) => s.key), ['square', 'circle', 'rect']);
});

test('the range: query and what the server sends back', async () => {
  const { rangeQuery, parseRange, RANGE_ORIENTS } = await import('../../webui/app/board-model.js');
  assert.equal(rangeQuery({ size: 'small', shape: 'circle', orient: 'portrait' }), 'size=small&shape=circle'); // orient only for a rectangle
  assert.equal(rangeQuery({ size: 'large', shape: 'rect', orient: 'portrait' }), 'size=large&shape=rect&orient=portrait');
  assert.equal(rangeQuery(null), '');
  assert.deepEqual(parseRange({ size: 'large', shape: 'rect', orient: 'portrait', radius: 300 }), { size: 'large', shape: 'rect', orient: 'portrait' });
  assert.deepEqual(parseRange({}), { size: 'medium', shape: 'square', orient: 'landscape' });
  assert.deepEqual(RANGE_ORIENTS.map((o) => o.label), ['가로', '세로']);
});

test('the model base: step height, sheet size, the files request and the summary line', async () => {
  const { stepInterval, readSheet, modelBaseQuery, readModelSummary, modelSummaryText, MODEL_DEFAULTS } = await import('../../webui/app/board-model.js');
  assert.equal(stepInterval(500, 3), 1.5); // 3 mm at 1:500 is 1.5 m of ground
  assert.equal(stepInterval(1000, 2), 2);
  assert.deepEqual(readSheet('600x400'), [600, 400]);
  assert.deepEqual(readSheet(' 900 × 600 '), [900, 600]);
  assert.equal(readSheet('600'), null);
  assert.equal(readSheet('10x400'), null); // too small to be a sheet
  const q = new URLSearchParams(modelBaseQuery({ ...MODEL_DEFAULTS, sheet: '900×600', hollow: 4 }, { size: 'small', shape: 'circle' }));
  assert.deepEqual(Object.fromEntries(q), { scale: '500', thickness: '3', sheet: '900x600', hollow: '4', size: 'small', shape: 'circle' });
  assert.equal(new URLSearchParams(modelBaseQuery(null, null)).get('size'), null); // the project's saved range
  const s = readModelSummary('interval=1.5;layers=4;pieces=31;sheets=2;size_mm=400.0x400.0;radius=100.0;shape=circle;size=small;buildings_left_out=False');
  assert.equal(s.sheets, '2');
  assert.equal(modelSummaryText(s), '판 2장 · 조각 31개 · 층 4개 · 400×400 mm (작게, 원)');
  assert.match(modelSummaryText({ ...s, size: 'None', radius: '150.0', shape: 'square', buildings_left_out: 'True' }), /반경 150m, 정사각형\) · 실시간 건물은/);
  assert.match(modelSummaryText({ ...s, shape: 'rect', orient: 'portrait' }), /\(작게, 직사각형 세로\)/);
  assert.equal(modelSummaryText({}), '');
});

test('the VWorld 3D frame opens the app page with the script, or the data server page without it', async () => {
  const { vworldFrame } = await import('../../webui/app/board-model.js');
  const origin = { lon: 126.978, lat: 37.566 };
  const script = 'https://map.vworld.kr/js/webglMapInit.js.do?version=3.0&apiKey=k-1';
  const own = vworldFrame({ page: '/app/vworld3d.html', script, version: '3.0' }, origin, 'http://localhost:8765');
  const [page, hash] = own.src.split('#');
  assert.equal(page, '/app/vworld3d.html');
  const at = new URLSearchParams(hash);
  assert.equal(at.get('script'), script); // after #: never sent to a server
  assert.equal(at.get('lon'), '126.978');
  assert.equal(at.get('lat'), '37.566');
  assert.equal(at.get('parent'), 'http://localhost:8765'); // the only page the map talks to
  const relayPage = 'https://sida-kr.duckdns.org/relay/vworld3d?sida_token=sida_abc';
  const relayed = vworldFrame({ page: relayPage, version: '3.0' }, origin, 'http://localhost:8765');
  assert.ok(relayed.src.startsWith(`${relayPage}#`));
  assert.equal(new URLSearchParams(relayed.src.split('#')[1]).get('script'), null); // the server fills it in
  // a new page only when the page or the key changes, not when the site moves
  assert.equal(vworldFrame({ page: relayPage }, { lon: 127, lat: 37 }, 'x').key, relayed.key);
  assert.notEqual(relayed.key, own.key);
  assert.equal(vworldFrame(null, origin, 'x'), null);
  assert.equal(vworldFrame({ script }, origin, 'x'), null);
  assert.equal(vworldFrame({ page: '/app/vworld3d.html' }, null, 'x'), null);
});

test('the model board: its size, frame, overflow past the range, layers and the request', async () => {
  const {
    boardSize, frameSize, rangeHalf, frameOverflow, boardCenter, layersUnder, boardInfo, boardInfoText, boardBody, mapFit,
    MODEL_BOARDS, BOARD_SCALES,
  } = await import('../../webui/app/board-model.js');
  assert.deepEqual(boardSize({ board: 'W600x900' }), [900, 600]);
  assert.deepEqual(boardSize({ board: 'A1', orient: 'portrait' }), [594, 841]);
  assert.deepEqual(boardSize({ board: 'custom', width_mm: 400, height_mm: 700 }), [700, 400]);
  assert.equal(boardSize({ board: 'custom', width_mm: 40, height_mm: 700 }), null);
  assert.deepEqual(frameSize({ board: 'W600x900', scale: 600 }), [540, 360]);
  assert.deepEqual(rangeHalf({ size: 'large', shape: 'rect', orient: 'portrait' }), { hx: 200, hy: 300, round: false });
  const wide = { radius: 300, shape: 'rect', orient: 'landscape' };
  assert.equal(frameOverflow([0, 0], [540, 360], wide), 0);
  assert.equal(frameOverflow([50, 0], [540, 360], wide), 20); // the east edge at 320 m
  assert.ok(Math.abs(frameOverflow([0, 0], [540, 360], { radius: 300, shape: 'circle' }) - 24.5) < 0.1);
  assert.deepEqual(boardCenter({ center: [5, 6] }, null), [5, 6]);
  assert.deepEqual(boardCenter({}, { plan: { bounds: { min_x: -10, max_x: 30, min_y: 0, max_y: 20 } } }), [10, 10]);
  // ground rising 0 → 8 m northward on a 3 × 3 grid, 10 m apart; 1.5 m steps (3 mm at 1:500)
  const terrain = { min: -10, step: 10, n: 3, z: [0, 0, 0, 4, 4, 4, 8, 8, 8], classes: 'ggggggggx' };
  assert.equal(layersUnder(terrain, 30, [0, 0], [40, 40], 1.5), 6); // 30–38 m: from 30 up to 39
  assert.equal(layersUnder(terrain, 30, [0, -10], [5, 5], 1.5), 1); // only the south row
  const site = { plan: { bounds: { min_x: -10, max_x: 10, min_y: -5, max_y: 5 } } };
  const info = boardInfo({ board: 'W600x900', scale: 500, thickness_mm: 3 }, { range: wide, site, terrain, groundElev: 30 });
  assert.deepEqual([info.frame, info.interval, info.siteCm, info.overflow], [[450, 300], 1.5, [4, 2], 0]);
  assert.match(boardInfoText(info), /^판 범위 450×300 m · 층 약 6개 · 땅 높이 약 18 mm · 등고 간격 1.5 m · 대지 4×2 cm$/);
  assert.match(boardInfoText(info, { layers: 7, sheets: 9, total_height_mm: 21 }), /층 7개 · 판 9장 · 높이 21 mm/);
  const over = boardInfo({ board: 'A0', scale: 1000, thickness_mm: 3 }, { range: wide, site });
  assert.match(boardInfoText(over), /3D 범위를 \d+ m 벗어납니다$/);
  assert.deepEqual(boardBody({ board: 'custom', width_mm: 500, height_mm: 400, scale: 300, thickness_mm: 5 }, [1.234, 2]),
    { board: 'custom', orient: 'landscape', scale: 300, thickness_mm: 5, save_material: false, width_mm: 500, height_mm: 400, center: [1.23, 2] });
  const fit = mapFit(wide, 460, 316);
  assert.ok(Math.abs((0 - fit.west) * fit.k - 230) < 1e-9 && Math.abs(fit.north * fit.k - 158) < 1e-9); // the range's middle at the picture's middle
  assert.deepEqual(MODEL_BOARDS.map((b) => b.key), ['A0', 'A1', 'A2', 'W600x900', 'W900x1800', 'custom']);
  assert.equal(BOARD_SCALES.length, 12);
});

test('the laser formats ticked on and off stay in their order', async () => {
  const { pickFormats, LASER_FORMATS } = await import('../../webui/app/board-model.js');
  assert.deepEqual(LASER_FORMATS.map((f) => f.key), ['dxf', 'pdf', 'svg']);
  assert.deepEqual(pickFormats(['dxf', 'pdf', 'svg'], 'pdf', false), ['dxf', 'svg']);
  assert.deepEqual(pickFormats(['svg'], 'dxf', true), ['dxf', 'svg']);
  assert.deepEqual(pickFormats([], 'dwg', true), []); // not a format the server makes
});

test('papers and blocks sit on their own layer, else their kind or scheme', async () => {
  const { DEFAULT_LAYERS, paperLayer, blockLayer, layerFlags, boardLayers } = await import('../../webui/app/board-model.js');
  const layers = [...DEFAULT_LAYERS, { id: 'tower', name: '타워', parent: 'mass', visible: true, locked: false, color: '#ff0000' },
    { id: 'top', name: '옥탑', parent: 'tower', visible: true, locked: true, color: '' }];
  const mass = { id: 'm', kind: 'mass', layer: 'tower', blocks: [{ floors: 1 }, { floors: 2, layer: 'top' }, { floors: 3, layer: 'gone' }] };
  assert.equal(paperLayer(mass, layers), 'tower');
  assert.equal(paperLayer({ kind: 'note', layer: 'gone' }, layers), 'note');
  assert.equal(paperLayer({ kind: 'odd' }, layers), 'site');
  assert.deepEqual(mass.blocks.map((b) => blockLayer(mass, b, layers)), ['tower', 'top', 'tower']);
  // Hiding or locking a layer hides or locks its sublayers.
  const flags = layerFlags(layers.map((l) => (l.id === 'mass' ? { ...l, visible: false } : l)));
  assert.deepEqual([...flags.hidden].sort(), ['mass', 'top', 'tower']);
  assert.deepEqual([...flags.locked], ['top']);
  assert.equal(flags.color.get('tower'), '#ff0000');
  assert.equal(boardLayers({ layers: [] }), DEFAULT_LAYERS);
});

test('the layers panel lists a tree with counts, and layers are added, renamed, moved and taken away', async () => {
  const { DEFAULT_LAYERS, layerRows, addLayer, removeLayer, changeLayer, moveLayer, nextLayerName } = await import('../../webui/app/board-model.js');
  let layers = addLayer(DEFAULT_LAYERS, { id: 'tower', parent: 'mass' });
  assert.equal(layers.find((l) => l.id === 'tower').name, '레이어 1');
  layers = addLayer(layers, { id: 'top', name: '옥탑', parent: 'tower' });
  layers = addLayer(layers, { id: 'low', name: '저층부', parent: 'mass' });
  assert.deepEqual(layers.map((l) => l.id).slice(1, 5), ['mass', 'tower', 'top', 'low']);
  assert.equal(nextLayerName(layers), '레이어 2');
  const board = { layers, papers: [{ id: 's', kind: 'site' }, { id: 'm', kind: 'mass', blocks: [{}, { layer: 'top' }] }, { id: 'n', kind: 'note' }] };
  const rows = layerRows(board, { around: true, current: 'low' });
  assert.deepEqual(rows.map((r) => [r.id, r.depth, r.count]).slice(0, 5), [['site', 0, 1], ['mass', 0, 1], ['tower', 1, 0], ['top', 2, 1], ['low', 1, 0]]);
  assert.equal(rows.find((r) => r.id === 'low').current, true);
  assert.equal(rows.find((r) => r.id === 'mass').children, true);
  assert.deepEqual(rows.at(-1), { id: 'around', name: '주변 지형·건물', depth: 0, count: 0, visible: true, locked: false, color: '', system: true, children: false });
  assert.equal(layerRows({ layers: changeLayer(layers, 'mass', { visible: false }), papers: [] }).find((r) => r.id === 'top').parentHidden, true);
  // Moving keeps sublayers with their layer.
  assert.deepEqual(moveLayer(layers, 'low', 'up').map((l) => l.id).slice(1, 5), ['mass', 'low', 'tower', 'top']);
  assert.deepEqual(moveLayer(layers, 'tower', 'down').map((l) => l.id).slice(1, 5), ['mass', 'low', 'tower', 'top']);
  assert.equal(moveLayer(layers, 'site', 'up'), layers);
  // Taking a layer away lifts its sublayers to its parent; the last layer stays.
  const less = removeLayer(layers, 'tower');
  assert.equal(less.find((l) => l.id === 'top').parent, 'mass');
  assert.equal(less.some((l) => l.id === 'tower'), false);
  assert.equal(removeLayer([DEFAULT_LAYERS[0]], 'site').length, 1);
});

test('the properties tab sums a mass scheme against the site and its statutory caps', async () => {
  const { propertiesOf } = await import('../../webui/app/board-model.js');
  const mass = { id: 'm', kind: 'mass', title: 'A안', floor_height: 4, blocks: [{ w: 10, d: 20, floors: 3 }, { w: 5, d: 10, floors: 1 }] };
  const site = { areaM2: 500, area: '500㎡', address: '서울 중구 무교동 45', zones: ['일반상업지역'], bcr: 80, far: 1300 };
  const props = propertiesOf([mass], site);
  const row = (label) => props.rows.find((r) => r[0] === label)?.[1];
  assert.equal(props.title, 'A안');
  assert.equal(row('동'), '2개');
  assert.equal(row('최고 층수'), '3층 (12m)');
  assert.equal(row('건축면적'), '250㎡');
  assert.equal(row('연면적'), '650㎡');
  assert.equal(row('건폐율'), '50% (법정 80% 이하)');
  assert.equal(row('용적률'), '130% (법정 1300% 이하)');
  assert.ok(props.note.includes('겹친'));
  // No site area: no ratios.
  assert.equal(propertiesOf([mass], null).rows.some((r) => r[0] === '건폐율'), false);
  const siteRows = propertiesOf([{ id: 's', kind: 'site' }], site).rows;
  assert.deepEqual(siteRows[1].slice(0, 2), ['레이어', 'site']);
  assert.deepEqual(siteRows.slice(2), [['주소', '서울 중구 무교동 45'], ['용도지역', '일반상업지역'], ['대지면적', '500㎡']]);
  const several = propertiesOf([{ kind: 'note' }, { kind: 'note' }, { kind: 'photo' }]);
  assert.deepEqual(several.rows.slice(0, 2), [['메모', '2장'], ['사진', '1장']]);
  assert.deepEqual(several.rows[2].slice(0, 2), ['레이어', '']); // a note and a photo: two layers
  assert.equal(propertiesOf([]), null);
});

test('a picked building shows its floors and size to change; several share their floors', async () => {
  const { propertiesOf, pickedBlocks } = await import('../../webui/app/board-model.js');
  const mass = { id: 'm', kind: 'mass', title: 'A안', floor_height: 4, blocks: [{ u: 0, v: 0, w: 10, d: 20, floors: 3 }, { u: 0, v: 0, w: 5, d: 10, floors: 1, a: 30 }] };
  const one = propertiesOf([], null, pickedBlocks([mass], ['m#1']));
  const row = (props, label) => props.rows.find((r) => r[0] === label);
  assert.equal(one.title, 'A안 · 2동');
  assert.equal(row(one, '층수')[1], 1);
  assert.equal(row(one, '층수')[2].key, 'floors');
  assert.equal(row(one, '각도')[1], 30);
  assert.equal(row(one, '높이')[1], '4m');
  const both = propertiesOf([], null, pickedBlocks([mass], ['m#0', 'm#1']));
  assert.equal(both.title, '동 2개');
  assert.equal(row(both, '층수')[1], '');
  assert.ok(both.note.includes('다릅니다'));
  assert.equal(propertiesOf([], null, []), null);
  // A paper's name and a scheme's floor height are fields; the counts are not.
  const scheme = propertiesOf([mass]);
  assert.equal(row(scheme, '이름')[2].key, 'title');
  assert.equal(row(scheme, '층고')[2].key, 'floor_height');
  assert.equal(row(scheme, '동')[2], undefined);
  assert.equal(row(propertiesOf([{ id: 'n', kind: 'note', text: 'x' }]), '이름'), undefined);
});

test('a value typed into the properties is checked before it changes anything', async () => {
  const { propertyChange, pickedBlocks } = await import('../../webui/app/board-model.js');
  const mass = { id: 'm', kind: 'mass', title: 'A안', floor_height: 4, blocks: [{ u: 0, v: 0, w: 10, d: 20, floors: 3 }, { u: 0, v: 0, w: 5, d: 10, floors: 1, a: 30 }] };
  assert.deepEqual(propertyChange([mass], [], 'title', '  B안 '), [{ id: 'm', changes: { title: 'B안' } }]);
  assert.deepEqual(propertyChange([mass], [], 'title', 'A안'), []);
  assert.deepEqual(propertyChange([mass], [], 'floor_height', '3.5'), [{ id: 'm', changes: { floor_height: 3.5 } }]);
  assert.match(propertyChange([mass], [], 'floor_height', '30').error, /1에서 20/);
  assert.match(propertyChange([mass], [], 'floor_height', 'abc').error, /숫자/);
  assert.ok(propertyChange([{ id: 'n', kind: 'note' }], [], 'title', 'x').error);
  // Buildings: only the picked ones change; several take the same floors.
  const picked = pickedBlocks([mass], ['m#0', 'm#1']);
  const [change] = propertyChange([], picked, 'floors', '7');
  assert.deepEqual(change.changes.blocks.map((b) => b.floors), [7, 7]);
  assert.match(propertyChange([], picked, 'floors', '2.5').error, /정수/);
  const [turn] = propertyChange([], pickedBlocks([mass], ['m#1']), 'a', '0');
  assert.equal('a' in turn.changes.blocks[1], false);
  assert.equal(turn.changes.blocks[0], mass.blocks[0]);
  assert.deepEqual(propertyChange([], pickedBlocks([mass], ['m#0']), 'w', '10'), []);
  assert.ok(propertyChange([mass], picked, 'floors', '2').error);
});

test('the 레이어 value moves papers onto a layer and buildings onto their own or back', async () => {
  const { DEFAULT_LAYERS, propertiesOf, propertyChange, pickedBlocks } = await import('../../webui/app/board-model.js');
  const layers = [...DEFAULT_LAYERS, { id: 'tower', name: '타워', parent: 'mass', visible: true, locked: false, color: '' }];
  const mass = { id: 'm', kind: 'mass', title: 'A', blocks: [{ w: 1, d: 1, floors: 1 }, { w: 1, d: 1, floors: 1, layer: 'tower' }] };
  const row = (props) => props.rows.find((r) => r[0] === '레이어');
  assert.equal(row(propertiesOf([mass], null, [], layers))[1], 'mass');
  assert.equal(row(propertiesOf([], null, pickedBlocks([mass], ['m#1']), layers))[1], 'tower');
  assert.equal(row(propertiesOf([], null, pickedBlocks([mass], ['m#0', 'm#1']), layers))[1], '');
  assert.deepEqual(propertyChange([mass], [], 'layer', 'tower', layers), [{ id: 'm', changes: { layer: 'tower' } }]);
  assert.deepEqual(propertyChange([mass], [], 'layer', 'mass', layers), []);
  assert.match(propertyChange([mass], [], 'layer', 'nope', layers).error, /없는/);
  const [{ changes }] = propertyChange([], pickedBlocks([mass], ['m#0', 'm#1']), 'layer', 'mass', layers);
  assert.deepEqual(changes.blocks.map((b) => b.layer), [undefined, undefined]); // back onto the scheme's
  const [{ changes: onto }] = propertyChange([], pickedBlocks([mass], ['m#0']), 'layer', 'tower', layers);
  assert.equal(onto.blocks[0].layer, 'tower');
  assert.equal(onto.blocks[1], mass.blocks[1]);
});

test('a group is picked whole, made and taken apart as edits', async () => {
  const { expandGroups, groupChange, groupMembers, selectedGroup, groupProperties } = await import('../../webui/app/board-model.js');
  const papers = [
    { id: 'm', kind: 'mass', blocks: [{ floors: 1 }, { floors: 2 }, { floors: 3 }] },
    { id: 'n', kind: 'note' }, { id: 'p', kind: 'photo' },
  ];
  // Group a note with two buildings of a scheme.
  const made = groupChange(papers, ['n'], ['m#0', 'm#2'], 'g1');
  assert.deepEqual(made.map((e) => e.id), ['m', 'n']);
  assert.deepEqual(made[0].changes.blocks.map((b) => b.group), ['g1', undefined, 'g1']);
  assert.equal(made[0].changes.group, undefined); // the scheme itself is not in the group
  assert.deepEqual(made[1].changes, { group: 'g1' });
  const grouped = papers.map((p) => ({ ...p, ...(made.find((e) => e.id === p.id)?.changes || {}) }));
  assert.deepEqual(groupMembers(grouped, 'g1'), { ids: ['n'], keys: ['m#0', 'm#2'] });
  // Picking one member picks them all; something outside stays as it is.
  assert.deepEqual(expandGroups(grouped, [], ['m#2']), { ids: ['n'], keys: ['m#2', 'm#0'] });
  assert.deepEqual(expandGroups(grouped, ['p'], []), { ids: ['p'], keys: [] });
  assert.equal(selectedGroup(grouped, ['n'], ['m#0', 'm#2']), 'g1');
  assert.equal(selectedGroup(grouped, ['n', 'p'], ['m#0', 'm#2']), '');
  assert.equal(groupProperties(grouped, 'g1').title, '그룹 (3개)');
  // Taking it apart (from any member) clears the group everywhere.
  const apart = groupChange(grouped, [], ['m#0'], '');
  assert.deepEqual(apart.find((e) => e.id === 'n').changes, { group: '' });
  assert.equal(apart.find((e) => e.id === 'm').changes.blocks.some((b) => 'group' in b), false);
});

// The screen scripts were split into parts (#90); a function a part calls but forgot to import
// only fails when that code runs (2026-11-09: right-drag orbit and the idea board's drop threw).
test('every screen script imports the functions it calls from the other scripts', async () => {
  const { readFileSync, readdirSync } = await import('node:fs');
  const dir = new URL('../../webui/app/', import.meta.url);
  const read = (f) => readFileSync(new URL(f, dir), 'utf8');
  const files = readdirSync(dir).filter((f) => f.endsWith('.js'));
  const strip = (s) => s.replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|[^:'"`\\])\/\/.*$/gm, '$1');
  const exported = new Map();
  for (const f of files) for (const m of read(f).matchAll(/^export (?:async )?function (\w+)/gm)) exported.set(m[1], f);
  const out = [];
  for (const f of files) {
    const src = strip(read(f));
    const known = new Set();
    for (const m of src.matchAll(/import\s*\{([^}]*)\}/g)) for (const n of m[1].split(',')) known.add(n.trim().split(/\s+as\s+/).pop());
    for (const m of src.matchAll(/(?:function|const|let|var|class)\s+(\w+)/g)) known.add(m[1]);
    for (const [name, from] of exported) {
      if (from === f || known.has(name)) continue;
      // A call, also after a spread (...name(...)), but not a method on something (x.name(...)).
      const calls = [...src.matchAll(new RegExp(`(?<=^|[^.\\w$]|\\.\\.\\.)${name}\\(`, 'gm'))].filter((m) => {
        const line = src.slice(src.lastIndexOf('\n', m.index) + 1, src.indexOf('\n', m.index));
        return !new RegExp(`^\\s*(async\\s+)?${name}\\([^)]*\\)\\s*\\{`).test(line);
      });
      if (calls.length) out.push(`${f}: ${name} (from ${from})`);
    }
  }
  assert.deepEqual(out, []);
});

test('a resized paper scales its writing with the smaller of its width and height', async () => {
  const { paperTextScale, PAPER_SIZE } = await import('../../webui/app/board-model.js');
  const [w, h] = PAPER_SIZE.site;
  assert.equal(paperTextScale({ kind: 'site', w, h }), 1);
  assert.equal(paperTextScale({ kind: 'site', w: w * 2, h: h * 2 }), 2);
  assert.equal(paperTextScale({ kind: 'note', w: 400, h: 140 }), 1); // wider only: the height keeps it
  assert.equal(paperTextScale({ kind: 'expert', w: 160, h: 135 }), 0.5);
  assert.equal(paperTextScale({ kind: 'mass', w: 30000, h: 30000 }), 4);
  assert.equal(paperTextScale({ kind: 'photo', w: 900, h: 675 }), 1);
  assert.equal(paperTextScale({ kind: 'tracing', w: 900, h: 900 }), 1);
});

test('a paper shown as a circle carries the mark of its kind', async () => {
  const { paperGlyph } = await import('../../webui/app/board-model.js');
  assert.equal(paperGlyph({ kind: 'site' }), '◇');
  assert.equal(paperGlyph({ kind: 'mass', title: 'A' }), '▣');
  assert.equal(paperGlyph({ kind: 'photo', file: 'photo-12345678.pdf' }), 'PDF');
  assert.equal(paperGlyph({ kind: 'photo', file: 'photo-12345678.png' }), '•');
});

test('a corner drag with Alt keeps the middle, and with Ctrl keeps the shape', async () => {
  const { resizedPaper, PX } = await import('../../webui/app/board-model.js');
  const from = { x: 0, y: 0, w: 300, h: 200 }; // corners at x ±15, y ±10
  // Alt: the south-east corner to (20, -15) moves every side; the middle stays.
  assert.deepEqual(resizedPaper(from, 'se', { x: 20, y: -15 }, { center: true }), { x: 0, y: 0, w: 400, h: 300 });
  // Ctrl: pulled mostly sideways, the height follows the width.
  const kept = resizedPaper(from, 'se', { x: 45, y: -12 }, { ratio: true });
  assert.deepEqual([kept.w, kept.h], [600, 400]);
  // Both: from the middle and in shape.
  const both = resizedPaper(from, 'nw', { x: -30, y: 11 }, { ratio: true, center: true });
  assert.deepEqual(both, { x: 0, y: 0, w: 600, h: 400 });
  assert.ok(Math.abs(both.w * PX / 2 - 30) < 1e-9);
});

test('the properties show a paper size in metres on the table', async () => {
  const { propertiesOf, PX } = await import('../../webui/app/board-model.js');
  const row = propertiesOf([{ id: 'n', kind: 'note', text: 'x', w: 200, h: 140 }]).rows.find((r) => r[0] === '크기');
  assert.equal(row[1], `${200 * PX} × ${140 * PX}m`);
});

test('the surroundings get a sublayer for each part they have', async () => {
  const { layerRows } = await import('../../webui/app/board-model.js');
  const rows = layerRows({ papers: [] }, { around: true, aroundParts: [{ id: 'contours', count: 12 }, { id: 'ground', count: 1 }], aroundPartsHidden: new Set(['contours']) });
  const parts = rows.filter((r) => r.id.startsWith('around:'));
  assert.deepEqual(parts.map((r) => [r.id, r.depth, r.visible, r.count]), [['around:ground', 1, true, 1], ['around:contours', 1, false, 12]]);
  assert.equal(rows.find((r) => r.id === 'around').children, true);
  assert.equal(layerRows({ papers: [] }, { around: true, aroundHidden: true, aroundParts: [{ id: 'ground', count: 1 }] }).at(-1).parentHidden, true);
  assert.equal(layerRows({ papers: [] }, { around: false, aroundParts: [{ id: 'ground', count: 1 }] }).some((r) => r.id.startsWith('around')), false);
});

test('a folded layer hides its sublayers at any depth, and only those', async () => {
  const { foldedRows } = await import('../../webui/app/board-model.js');
  const rows = [
    { id: 'mass', depth: 0, children: true }, { id: 'tower', depth: 1, children: true }, { id: 'top', depth: 2 },
    { id: 'low', depth: 1 }, { id: 'note', depth: 0 }, { id: 'around', depth: 0, children: true }, { id: 'around:ground', depth: 1 },
  ];
  const ids = (folded) => foldedRows(rows, new Set(folded)).map((r) => r.id);
  assert.deepEqual(ids([]), rows.map((r) => r.id));
  assert.deepEqual(ids(['mass']), ['mass', 'note', 'around', 'around:ground']);
  assert.deepEqual(ids(['tower']), ['mass', 'tower', 'low', 'note', 'around', 'around:ground']);
  assert.deepEqual(ids(['around', 'note']), ['mass', 'tower', 'top', 'low', 'note', 'around']);
});

test('road paint becomes ribbons of its real width, filled marks and outlines', async () => {
  const { paintTriangles, AROUND_PARTS } = await import('../../webui/app/board-model.js');
  const tri = paintTriangles({
    lines: [{ color: 'yellow', width: 0.2, pieces: [[[0, 0, 1], [10, 0, 2]], [[0, 5, 0], [0, 5, 0]]] }],
    marks: [{ kind: '5371', shapes: [[[0, 0, 0], [1, 0, 0], [1, 1, 0], [0, 1, 0]]], outline: null },
      { kind: '5372', shapes: [], outline: [[0, 0, 0], [5, 0, 0], [5, 1, 0], [0, 0, 0]] }],
  });
  const ys = tri.lines.yellow.filter((_, i) => i % 3 === 1);
  assert.equal(tri.lines.yellow.length, 18); // one quad: the zero-length piece adds nothing
  assert.deepEqual([Math.min(...ys), Math.max(...ys)], [-0.1, 0.1]); // 0.2 m wide around the line
  assert.equal(tri.lines.yellow[2], 1); // each end keeps its own height
  assert.equal(tri.marks.length, 2 * 9); // a square as two triangles
  assert.equal(tri.outlines.length, 3 * 6); // three edges of the outline
  assert.deepEqual(tri.counts, { lanes: 2, marks: 2 });
  assert.deepEqual(paintTriangles(null).counts, { lanes: 0, marks: 0 });
  assert.ok(AROUND_PARTS.some(([id]) => id === 'lanes') && AROUND_PARTS.some(([id]) => id === 'marks'));
});

test('every three.js name the screen uses is in the bundled three.js', async () => {
  // A name missing from webui/app/vendor/three.js is undefined at run time: the 주변 3D drawing
  // stopped part way at THREE.Float32BufferAttribute (2026-11-11). Add it to scripts/three-vendor/entry.js.
  const { readFile, readdir } = await import('node:fs/promises');
  const dir = new URL('../../webui/app/', import.meta.url);
  const bundled = await import(new URL('vendor/three.js', dir).href);
  const used = new Set();
  for (const name of await readdir(dir)) {
    if (!name.endsWith('.js')) continue;
    for (const m of (await readFile(new URL(name, dir), 'utf8')).matchAll(/\bTHREE\.([A-Za-z0-9_]+)/g)) used.add(m[1]);
  }
  assert.ok(used.size > 20);
  assert.deepEqual([...used].filter((name) => bundled[name] === undefined), []);
});
