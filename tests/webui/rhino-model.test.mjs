// rhino-model.js: what the Rhino paper and the panel inside Rhino show, from what Sida sent.
import test from 'node:test';
import assert from 'node:assert/strict';

import { rhinoPaperParts, rhinoViewUrl, rhinoDiagramUrl, diagramFileName, diagramPngSize, limitLines, panelStatus, panelFigures, panelBusy, diagramChoices, layerRows, readFloorHeight, meaningChoices } from '../../webui/app/rhino-model.js';

const MEANINGS = [
  { code: 'housing', word: '주거', built: true }, { code: 'commercial', word: '상업', built: true },
  { code: 'surroundings', word: '주변 건물', built: false }, { code: 'ignore', word: '제외', built: false },
];
const ZONE = { zone: '제2종일반주거지역', bcr_max: 60, far_min: 100, far_max: 250, ordinance_bcr: 60, ordinance_far: 200 };
const FIGURES = {
  floor_area_m2: 2100, footprint_m2: 570, volume_m3: 6780, height_m: 13, coverage_pct: 57, far_pct: 210, site_area_m2: 1000,
  objects: 3, unmeasured: [], no_floor_height: [], unassigned: 0,
  by_meaning: [{ meaning: 'housing', word: '주거', floor_area_m2: 1920, footprint_m2: 480, objects: 2 },
    { meaning: 'commercial', word: '상업', floor_area_m2: 180, footprint_m2: 180, objects: 1 }],
  lines: ['연면적 2,100.0㎡ (주거 1,920.0, 상업 180.0)', '건축면적 570.0㎡', '건폐율 57.0% · 용적률 210.0%'], limits: [ZONE],
};

test('the Rhino paper shows the figure lines as sent, the perspective capture first, and where it came from', () => {
  const paper = { kind: 'rhino', title: 'studio', snapshot: '20261116-104000-0001', file: 'studio.3dm', taken_at: '2026-11-16T10:40:00', objects: 12,
    views: [{ kind: 'plan', file: 'plan.png' }, { kind: 'persp', file: 'persp.png' }, { kind: 'odd' }], figures: FIGURES };
  const parts = rhinoPaperParts(paper);
  assert.deepEqual(parts.lines, FIGURES.lines);
  assert.deepEqual(parts.views.map((v) => [v.kind, v.word]), [['persp', '투시'], ['plan', '평면']]);
  assert.equal(parts.source, 'studio.3dm, 2026-11-16 10:40, 개체 12개');
  assert.deepEqual(parts.limits, ['제2종일반주거지역: 법정 건폐율 60% 이하, 용적률 250% 이하 (조례 건폐율 60%, 용적률 200%)']);
  assert.equal(rhinoViewUrl('무교동 45', parts.snapshot, 'persp.png'), '/api/projects/%EB%AC%B4%EA%B5%90%EB%8F%99%2045/rhino/snapshots/20261116-104000-0001/views/persp.png');
  const bare = rhinoPaperParts({ kind: 'rhino' });
  assert.deepEqual([bare.lines, bare.views, bare.limits], [[], [], []]);
  assert.equal(bare.source, '저장하지 않은 라이노 문서, 개체 0개');
  assert.deepEqual(limitLines([{ zone: '자연녹지지역', bcr_max: 20, far_max: 100, ordinance_bcr: null, ordinance_far: null }]), ['자연녹지지역: 법정 건폐율 20% 이하, 용적률 100% 이하']);
});

test('the panel says which state it is in and what to do about it', () => {
  assert.equal(panelStatus({ connected: false, rev: 0, state: null }).code, 'waiting');
  assert.equal(panelStatus({ connected: false, state: { project: 'a', project_known: true } }).code, 'lost');
  assert.equal(panelStatus({ connected: true, state: { project: '' } }).code, 'no-project');
  const bad = panelStatus({ connected: true, state: { project: '옛 프로젝트', project_known: false } });
  assert.equal(bad.code, 'bad-project');
  assert.match(bad.text, /옛 프로젝트/);
  assert.deepEqual(panelStatus({ connected: true, state: { project: 'a', project_known: true } }), { code: 'ready', text: '' });
});

test('a gauge measures a ratio against the ordinance value, else the legal ceiling, and only in one zone', () => {
  const view = panelFigures(FIGURES);
  const [coverage, far] = view.gauges;
  assert.deepEqual([coverage.text, coverage.limitText, coverage.over], ['57.0%', '조례 60%', false]);
  assert.equal(coverage.fill, 0.95);
  assert.deepEqual([far.text, far.limitText, far.over], ['210.0%', '조례 200%', true]);
  assert.equal(far.fill, 1.05);
  assert.deepEqual(view.rows.map((r) => `${r.label} ${r.text}`), ['연면적 2,100.0㎡', '건축면적 570.0㎡', '대지면적 1,000.0㎡', '최고 높이 13.0m']);
  assert.deepEqual(view.shares.map((s) => [s.word, s.text, Math.round(s.share * 1000)]), [['주거', '1,920.0㎡', 914], ['상업', '180.0㎡', 86]]);
  assert.deepEqual(view.notes, []);

  const legal = panelFigures({ ...FIGURES, far_pct: 900, limits: [{ ...ZONE, ordinance_far: null }] }).gauges[1];
  assert.deepEqual([legal.limitText, legal.over, legal.fill], ['법정 상한 250%', true, 1.25]);  // the bar stops a quarter past the mark
  const two = panelFigures({ ...FIGURES, limits: [ZONE, { ...ZONE, zone: '일반상업지역' }] });
  assert.equal(two.gauges[0].limit, null);
  assert.match(two.gauges[0].limitText, /용도지역이 여러 개/);
  assert.equal(two.limits.length, 2);
  assert.equal(panelFigures({ ...FIGURES, limits: [] }).gauges[0].limitText, '');
  assert.equal(panelFigures(null), null);
});

test('what was left out of the figures is said, and nothing is shown as a number that Sida did not send', () => {
  const view = panelFigures({ ...FIGURES, coverage_pct: null, far_pct: null, site_area_m2: null, height_m: null, objects: 0,
    unassigned: 4, no_floor_height: ['a'], unmeasured: ['b', 'c'] });
  assert.deepEqual(view.gauges.map((g) => [g.text, g.fill, g.over]), [['미확인', 0, false], ['미확인', 0, false]]);
  assert.equal(view.rows[2].text, '미확인');
  assert.equal(view.rows.length, 3);
  assert.equal(view.notes.length, 4);
  assert.match(view.notes[1], /개체 4개/);
  assert.equal(view.empty, true);
});

test('layers that need a meaning or a floor height come first, and empty ones are only counted', () => {
  const layers = [
    { path: 'Default', meaning: '', color: '#000000', floor_height: null, objects: 0 },
    { path: 'Program::Housing', meaning: 'housing', color: '#c86432', floor_height: 3, objects: 2 },
    { path: 'Sida::주변 건물', meaning: 'surroundings', color: '', floor_height: null, objects: 40 },
    { path: 'Program::Shop', meaning: 'commercial', color: '', floor_height: null, objects: 1 },
    { path: 'Sketch', meaning: '', color: '', floor_height: null, objects: 3 },
  ];
  const { rows, quiet } = layerRows(layers, MEANINGS);
  assert.deepEqual(rows.map((r) => [r.path, r.needs]), [
    ['Program::Shop', 'height'], ['Sketch', 'meaning'], ['Program::Housing', ''], ['Sida::주변 건물', '']]);
  assert.equal(quiet, 1);
  assert.deepEqual([rows[2].name, rows[2].under, rows[2].floorHeight, rows[2].takesHeight], ['Housing', 'Program', '3', true]);
  assert.equal(rows[3].takesHeight, false);
  assert.equal(layerRows(layers, MEANINGS, { all: true }).rows.length, 5);
  assert.deepEqual(layerRows(null, null), { rows: [], quiet: 0 });
});

test('a floor height is read as metres, empty is none, and nonsense is refused with an example', () => {
  assert.deepEqual(readFloorHeight(' 3,3 '), { value: 3.3 });
  assert.deepEqual(readFloorHeight(''), { value: null });
  assert.deepEqual(readFloorHeight('4.2004'), { value: 4.2 });
  for (const bad of ['0', '-3', '3m', '101']) assert.match(readFloorHeight(bad).error, /예: 3\.3/);
  assert.deepEqual(meaningChoices(MEANINGS), {
    built: [{ code: 'housing', word: '주거' }, { code: 'commercial', word: '상업' }],
    other: [{ code: 'surroundings', word: '주변 건물' }, { code: 'ignore', word: '제외' }],
  });
});

test('the Rhino paper lists the diagrams Sida can draw, with the address and file name of each', () => {
  const parts = rhinoPaperParts({ kind: 'rhino', snapshot: 's1', diagrams: [{ kind: 'program', title: '프로그램 매스' }, { kind: 'stack' }, null, { title: '이름만' }] });
  assert.deepEqual(parts.diagrams, [{ kind: 'program', title: '프로그램 매스' }, { kind: 'stack', title: 'stack' }]);
  assert.deepEqual(rhinoPaperParts({ kind: 'rhino' }).diagrams, []);
  assert.equal(rhinoDiagramUrl('무교동 45', 's1', 'program'), '/api/projects/%EB%AC%B4%EA%B5%90%EB%8F%99%2045/rhino/snapshots/s1/diagrams/program?format=svg');
  assert.equal(rhinoDiagramUrl('a', 's1', 'site', 'json'), '/api/projects/a/rhino/snapshots/s1/diagrams/site?format=json');
  assert.equal(diagramFileName('studio: 1/2안', '프로그램 매스', 'png'), 'studio 1 2안 프로그램 매스.png');
  assert.equal(diagramFileName('', '', 'svg'), 'diagram.svg');
});

test('a diagram PNG is twice the picture, but never larger than a canvas holds', () => {
  assert.deepEqual(diagramPngSize(960, 700), { width: 1920, height: 1400 });
  assert.deepEqual(diagramPngSize(960, 4000), { width: 983, height: 4096 });
  assert.deepEqual(diagramPngSize(0, undefined), { width: 1920, height: 1440 });
});

test('the panel is busy while the plugin says so, and from a pressed button until the plugin answers', () => {
  const live = (busy, n) => ({ connected: true, state: { busy, notice: n ? { n } : null } });
  const asked = { what: 'push', notice: 2, until: 5000 };
  assert.equal(panelBusy(live('pull', 2), null, 0), 'pull');      // the plugin's word comes first
  assert.equal(panelBusy(live('draw', 2), asked, 1000), 'draw');
  assert.equal(panelBusy(live('', 2), asked, 1000), 'push');      // pressed, the plugin has not reported yet
  assert.equal(panelBusy(live('', 3), asked, 1000), '');          // answered with a new notice
  assert.equal(panelBusy(live('', 2), asked, 6000), '');          // too long ago
  assert.equal(panelBusy(live('', 0), null, 0), '');
  assert.equal(panelBusy({ connected: false, state: null }, asked, 1000), '');
});

test('every diagram is picked to be drawn until the designer leaves one out', () => {
  const kinds = [{ kind: 'program', title: '프로그램 매스' }, { kind: 'floors', title: '층별 분해' }, { kind: 'site', title: '대지 배치도' }];
  assert.deepEqual(diagramChoices(kinds, []).picked, ['program', 'floors', 'site']);
  const some = diagramChoices(kinds, ['floors', 'gone']);
  assert.deepEqual(some.picked, ['program', 'site']);
  assert.deepEqual(some.rows.map((r) => [r.title, r.on]), [['프로그램 매스', true], ['층별 분해', false], ['대지 배치도', true]]);
  assert.deepEqual(diagramChoices(undefined, undefined), { rows: [], picked: [] });
});
