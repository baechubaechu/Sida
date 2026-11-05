// Drafting table helpers (webui/app/board-model.js): run with `node --test tests/webui/`.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  PX, TILT, MAX_TILT, cameraFor, riseFor, groundFor, zoomAround, drawingScale, scaleSpan, scaleBar, lerpView, siteBounds, traceHome,
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
} from '../../webui/app/board-model.js';

const close = (a, b, eps = 1e-6) => assert.ok(Math.abs(a - b) < eps, `${a} ≈ ${b}`);
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

test('only pictures are taken from what was dropped, a few at a time', () => {
  const file = (name, type) => ({ name, type });
  const got = pickPhotoFiles([file('a.jpg', 'image/jpeg'), file('b.pdf', 'application/pdf'), file('c.HEIC', ''), file('d.txt', '')]);
  assert.deepEqual(got.files.map((f) => f.name), ['a.jpg', 'c.HEIC']);
  assert.equal(got.skipped, 2);
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
  const { contourLines, groundPoint, aroundNote, isEstimate } = await import('../../webui/app/board-model.js');
  // a 3 × 3 grid rising 1 m per 10 m to the north: z = 0, 1, 2 by row
  const terrain = { min: -10, step: 10, n: 3, z: [0, 0, 0, 1, 1, 1, 2, 2, 2] };
  assert.deepEqual(groundPoint(terrain, 2, 1), [10, 0, 1]);
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
