// Section helpers (webui/app/section-model.js): the same cases as tests/test_board_section.py,
// so the drawing on the table and the exported file agree.
import test from 'node:test';
import assert from 'node:assert/strict';
import {
  nextSectionName, sectionFrame, spans, groundHeight, sectionCut, sectionSolids, sectionFigures, sectionSvg,
  nearEnd, draggedLine, sectionExport,
} from '../../webui/app/section-model.js';
import { OUTSIDE } from '../../webui/app/board-model.js';

const square = (x0, y0, x1, y1) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
// A grid of the surroundings' shape {min, step, n, z}: flat at `z`, `half` metres each way.
const flat = (z = 0, half = 50, step = 10) => {
  const n = (2 * half) / step + 1;
  return { min: -half, step, n, z: Array(n * n).fill(z) };
};
const near = (a, b) => Math.abs(a - b) < 1e-6;

test('names go A, B, … and skip the ones taken', () => {
  assert.equal(nextSectionName([]), 'A');
  assert.equal(nextSectionName([{ kind: 'section', title: 'A' }, { kind: 'mass', title: 'B' }]), 'B');
  const all = [...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'].map((title) => ({ kind: 'section', title }));
  assert.equal(nextSectionName(all), 'A2');
});

test('the line looks to its right and reads as the viewer sees it', () => {
  const north = sectionFrame([[0, 0], [0, 10]]);
  assert.ok(near(north.n[0], 1) && near(north.n[1], 0) && north.mirror === true); // looking east
  const flipped = sectionFrame([[0, 0], [0, 10]], true);
  assert.ok(near(flipped.n[0], -1) && flipped.mirror === false);
  assert.equal(sectionFrame([[1, 1], [1, 1]]), null);
});

test('spans find every stretch inside a concave footprint', () => {
  const u = [[0, 0], [30, 0], [30, 20], [20, 20], [20, 5], [10, 5], [10, 20], [0, 20]];
  assert.deepEqual(spans([-5, 10], [1, 0], 50, u), [[5, 15], [25, 35]]);
  assert.deepEqual(spans([-5, 2], [1, 0], 50, u), [[5, 35]]);
  assert.deepEqual(spans([-5, 30], [1, 0], 50, u), []);
  assert.deepEqual(spans([-5, 10], [1, 0], 8, u), [[5, 8]]); // the line ends inside
});

test('the ground is not known off the grid or outside the range', () => {
  const t = flat(2, 20, 5);
  assert.equal(groundHeight(t, 3, -4), 2);
  assert.equal(groundHeight(t, 25, 0), null);
  const round = { ...t, classes: Array(t.n * t.n).fill('g') };
  round.classes[0] = OUTSIDE;
  assert.equal(groundHeight(round, -20, -20), null);
  const cut = sectionCut([[-30, 0], [30, 0]], [], t);
  assert.equal(cut.profile.length, 1);
  assert.deepEqual([cut.profile[0][0], cut.profile[0].at(-1)], [[10, 2], [50, 2]]);
  assert.deepEqual(sectionCut([[-30, 0], [30, 0]], [], null).profile, []);
});

test('cut and beyond follow the side and the depth, far ones first', () => {
  const solids = [
    { kind: 'mass', outline: square(-5, -5, 5, 5), base: 0, top: 12 },
    { kind: 'building', outline: square(10, 20, 20, 30), base: 0, top: 9 }, // 20 m beyond, looking north
    { kind: 'building', outline: square(-20, 80, -10, 90), base: 0, top: 30 }, // 80 m beyond
    { kind: 'building', outline: square(0, -30, 10, -20), base: 0, top: 30 }, // behind the viewer
  ];
  const line = [[30, 0], [-30, 0]]; // walking west, it looks to its right: north
  const got = sectionCut(line, solids, null, { depth: 60 });
  assert.deepEqual(got.cut.map((c) => [c.kind, c.a, c.b]), [['mass', 25, 35]]);
  assert.deepEqual(got.beyond.map((c) => [c.a, c.b, c.dist]), [[10, 20, 20]]);
  assert.deepEqual(sectionCut(line, solids, null, { depth: 100 }).beyond.map((c) => c.dist), [80, 20]);
  assert.deepEqual(sectionCut(line, solids, null, { flip: true, depth: 100 }).beyond.map((c) => [c.a, c.b]), [[20, 30]]);
  // the 3D cut runs past the line's ends
  const wide = sectionCut([[0, 0], [1, 0]], [{ kind: 'mass', outline: square(20, -5, 30, 5), base: 0, top: 3 }], null, { from: -50, to: 50 });
  assert.deepEqual(wide.cut.map((c) => [c.a, c.b]), [[20, 30]]);
});

test('the solids are the scheme on its ground and the buildings around, less the one on the site', () => {
  const scheme = { id: 'm1', floor_height: 3, blocks: [{ u: 0, v: 0, w: 20, d: 10, floors: 5 }] };
  const buildings = [
    { outline: square(-6, -3, 6, 3), base: -1.5, top: 18.5, on_site: true },
    { outline: square(-5, 20, 5, 30), base: -2, top: 13, height_source: 'estimate' },
    { outline: square(-5, 40, 5, 50), base: -2, top: 13, height_source: 'height' },
  ];
  const solids = sectionSolids({ scheme, terrain: flat(-1.5), buildings });
  assert.deepEqual(solids.map((s) => [s.kind, s.base, s.top]), [['mass', -1.5, 13.5], ['building', -2, 13], ['building', -2, 13]]);
  assert.deepEqual(solids.map((s) => s.estimate), [undefined, true, false]);
  // a part turned off in 레이어 leaves the section too
  assert.deepEqual(sectionSolids({ scheme, buildings, hiddenParts: new Set(['buildings']) }).map((s) => s.estimate), [undefined, true]);
  assert.deepEqual(sectionSolids({ scheme, buildings, hiddenParts: new Set(['estimated']) }).map((s) => s.estimate), [undefined, false]);
});

test('the drawing shows the cut, its floors, its height and the A / A′ marks the right way round', () => {
  const solids = [{ kind: 'mass', outline: square(-5, -5, 5, 5), base: 0, top: 12, floors: 3, storey: 4 }];
  const result = sectionCut([[-30, 0], [30, 0]], solids, flat(), { flip: true });
  const svg = sectionSvg(result, { name: 'A' });
  assert.match(svg, /^<svg class="section-drawing"/);
  assert.equal((svg.match(/class="sec-floor"/g) || []).length, 2);
  assert.match(svg, /12\.0m/);
  assert.match(svg, /class="sec-ground"/);
  // looking south from a line walking east: A is on the left
  const marks = [...svg.matchAll(/<text class="sec-end" x="([\d.]+)"[^>]*>([^<]+)</g)].map((m) => [Number(m[1]), m[2]]);
  marks.sort((a, b) => a[0] - b[0]);
  assert.deepEqual(marks.map((m) => m[1]), result.mirror ? ['A′', 'A'] : ['A', 'A′']);
  assert.deepEqual(sectionFigures(result), ['길이 60.0m', '지형 높이차 0.0m', '자른 매스 12.0m']);
  assert.equal(sectionSvg(null), '');
});

test('dragging a line: the nearer end, 15° steps, and the file it exports', () => {
  assert.equal(nearEnd([[0, 0], [100, 0]], { x: 96, y: 3 }, 12), 1);
  assert.equal(nearEnd([[0, 0], [100, 0]], { x: 50, y: 0 }, 12), -1);
  const [, [x, y]] = draggedLine({ x: 0, y: 0 }, { x: 10, y: 2.4 }, true);
  assert.ok(Math.abs(Math.atan2(y, x) * (180 / Math.PI) - 15) < 0.1); // kept to the centimetre
  assert.deepEqual(draggedLine({ x: 0.123, y: 0 }, { x: 5.556, y: 1 }), [[0.12, 0], [5.56, 1]]);
  assert.deepEqual(sectionExport('p 1', 's1', 'pdf', 'm1', '무교동 45', 'B'), {
    url: '/api/projects/p%201/board/sections/s1/export?format=pdf&active=m1',
    filename: '무교동 45_단면_B-B.pdf',
  });
});

test('a section paper shows its length and takes its depth and scale in the properties', async () => {
  const { propertiesOf, propertyChange, paperName } = await import('../../webui/app/board-model.js');
  const p = { id: 's', kind: 'section', title: 'B', line: [[0, 0], [30, 40]], depth: 60, scale: 500 };
  assert.equal(paperName(p), '단면 B–B′');
  const rows = Object.fromEntries(propertiesOf([p]).rows.map((r) => [r[0], r[1]]));
  assert.deepEqual([rows['이름'], rows['길이'], rows['뒤쪽 깊이'], rows['축척 (1:n)']], ['B', '50m', 60, 500]);
  assert.deepEqual(propertyChange([p], [], 'depth', '0'), [{ id: 's', changes: { depth: 0 } }]);
  assert.deepEqual(propertyChange([p], [], 'scale', '200'), [{ id: 's', changes: { scale: 200 } }]);
  assert.deepEqual(propertyChange([p], [], 'scale', '500'), []);
  assert.match(propertyChange([p], [], 'scale', '250').error, /중 하나/);
  assert.match(propertyChange([p], [], 'depth', '2000').error, /0에서 1000/);
  assert.match(propertyChange([{ id: 'm', kind: 'mass', blocks: [] }], [], 'depth', '10').error, /없는 값/);
});
