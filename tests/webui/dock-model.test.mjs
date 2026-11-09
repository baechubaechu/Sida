import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  DEFAULT_PANEL_RATIOS, activate, defaultDock, dockForSaving, dockOf, dropTarget, movePanel, normalizeDock, panelVisible,
  resizeGroups, reveal, setSideOpen, sideShown, swapActive,
} from '../../webui/app/dock-model.js';

const tabsOf = (layout) => ({ left: layout.left.groups.map((g) => g.tabs), right: layout.right.groups.map((g) => g.tabs) });
const sizesOf = (layout, side) => layout[side].groups.map((g) => Math.round(g.size * 1000) / 1000);

test('the default layout has Conductor on the left and the three tabs on the right, all placed once', () => {
  const layout = defaultDock();
  assert.deepEqual(tabsOf(layout), { left: [['conductor']], right: [['props', 'layers', 'experts']] });
  assert.equal(panelVisible(layout, 'conductor'), true);
  assert.equal(panelVisible(layout, 'layers'), true);
  assert.equal(panelVisible(layout, 'props'), false);
  assert.deepEqual(dockOf(layout, 'experts'), { side: 'right', index: 0 });
});

test('the sides start about 360px and 300px wide on a 2000px screen', async () => {
  const { panelWidths } = await import('../../webui/app/talk-panel-model.js');
  assert.deepEqual(panelWidths(2000, DEFAULT_PANEL_RATIOS), { left: 360, right: 300, board: 1340 });
  // A tablet keeps the narrowest widths.
  assert.deepEqual(panelWidths(1000, DEFAULT_PANEL_RATIOS), { left: 280, right: 240, board: 480 });
});

test('a broken or partial layout keeps every panel on screen exactly once', () => {
  assert.deepEqual(normalizeDock(null), defaultDock());
  assert.deepEqual(normalizeDock('x'), defaultDock());
  const fixed = normalizeDock({
    left: { open: false, groups: [{ tabs: ['experts', 'nope', 'experts'], active: 'gone', size: -2 }, { tabs: [] }] },
    right: { groups: [{ tabs: ['layers', 'experts'], active: 'layers', size: 3 }] },
  });
  assert.deepEqual(tabsOf(fixed), { left: [['experts']], right: [['layers', 'conductor', 'props']] });
  assert.equal(fixed.left.open, false);
  assert.equal(fixed.right.open, true);
  assert.equal(fixed.left.groups[0].active, 'experts');
  assert.deepEqual(sizesOf(fixed, 'left'), [1]);
  // Everything lost: the panels come back on the right.
  assert.deepEqual(tabsOf(normalizeDock({ left: {}, right: {} })), { left: [], right: [['conductor', 'props', 'layers', 'experts']] });
});

test('dragging a tab into another group, above or below one, or onto an empty side', () => {
  let layout = defaultDock();
  // Into the left group as a tab: it shows there.
  layout = movePanel(layout, 'experts', { side: 'left', index: 0, place: 'tab' });
  assert.deepEqual(tabsOf(layout), { left: [['conductor', 'experts']], right: [['props', 'layers']] });
  assert.equal(panelVisible(layout, 'experts'), true);
  // Below Conductor: the left side splits in two, half each.
  layout = movePanel(layout, 'experts', { side: 'left', index: 0, place: 'below' });
  assert.deepEqual(tabsOf(layout), { left: [['conductor'], ['experts']], right: [['props', 'layers']] });
  assert.deepEqual(sizesOf(layout, 'left'), [0.5, 0.5]);
  // Above: the new group comes first and takes half of the group it split.
  layout = movePanel(layout, 'props', { side: 'left', index: 1, place: 'above' });
  assert.deepEqual(tabsOf(layout).left, [['conductor'], ['props'], ['experts']]);
  assert.deepEqual(sizesOf(layout, 'left'), [0.5, 0.25, 0.25]);
  assert.equal(layout.right.groups[0].active, 'layers');
  // The last tab leaves the right side: the side is empty, and then takes a new group again.
  layout = movePanel(layout, 'layers', { side: 'left', index: 0, place: 'tab' });
  assert.deepEqual(tabsOf(layout).right, []);
  assert.equal(sideShown(layout, 'right'), false);
  layout = movePanel(layout, 'conductor', { side: 'right', index: 0, place: 'end' });
  assert.deepEqual(tabsOf(layout), { left: [['layers'], ['props'], ['experts']], right: [['conductor']] });
  assert.equal(layout.left.groups[0].active, 'layers');
  // A new group at the bottom of a side with groups gets an even share.
  layout = movePanel(layout, 'experts', { side: 'right', index: 0, place: 'end' });
  assert.deepEqual(sizesOf(layout, 'right'), [0.5, 0.5]);
  for (const side of ['left', 'right']) assert.ok(Math.abs(layout[side].groups.reduce((s, g) => s + g.size, 0) - 1) < 1e-9);
});

test('moves that would change nothing leave the layout as it is', () => {
  const layout = defaultDock();
  assert.deepEqual(tabsOf(movePanel(layout, 'conductor', { side: 'left', index: 0, place: 'below' })), tabsOf(layout));
  assert.deepEqual(tabsOf(movePanel(layout, 'props', { side: 'right', index: 0, place: 'tab' })), tabsOf(layout));
  assert.equal(movePanel(layout, 'props', { side: 'right', index: 0, place: 'tab' }).right.groups[0].active, 'props');
  assert.equal(movePanel(layout, 'props', { side: 'right', index: 5, place: 'tab' }), layout);
  assert.equal(movePanel(layout, 'nothing', { side: 'right', index: 0, place: 'tab' }), layout);
  // Splitting a tab off its own group works.
  assert.deepEqual(tabsOf(movePanel(layout, 'experts', { side: 'right', index: 0, place: 'below' })).right, [['props', 'layers'], ['experts']]);
});

test('folding, revealing and turning tabs', () => {
  let layout = setSideOpen(defaultDock(), 'left', false);
  assert.equal(panelVisible(layout, 'conductor'), false);
  assert.equal(sideShown(layout, 'left'), false);
  layout = reveal(layout, 'conductor');
  assert.equal(panelVisible(layout, 'conductor'), true);
  layout = activate(layout, 'experts');
  assert.equal(layout.right.groups[0].active, 'experts');
  // Selecting turns 레이어 to 속성 only when 레이어 is showing in the same group.
  assert.equal(swapActive(layout, 'layers', 'props'), layout);
  layout = swapActive(activate(layout, 'layers'), 'layers', 'props');
  assert.equal(layout.right.groups[0].active, 'props');
  const apart = movePanel(defaultDock(), 'props', { side: 'right', index: 0, place: 'below' });
  assert.equal(swapActive(apart, 'layers', 'props'), apart);
});

test('dragging the line between two groups keeps both at least 120px tall', () => {
  const layout = movePanel(defaultDock(), 'experts', { side: 'right', index: 0, place: 'below' });
  assert.deepEqual(sizesOf(resizeGroups(layout, 'right', 0, 100, [300, 300]), 'right'), [0.667, 0.333]);
  assert.deepEqual(sizesOf(resizeGroups(layout, 'right', 0, 1000, [300, 300]), 'right'), [0.8, 0.2]);
  assert.deepEqual(sizesOf(resizeGroups(layout, 'right', 0, -1000, [300, 300]), 'right'), [0.2, 0.8]);
  // Too little room for two minimums: they share it.
  assert.deepEqual(sizesOf(resizeGroups(layout, 'right', 0, 50, [100, 100]), 'right'), [0.5, 0.5]);
  assert.equal(resizeGroups(layout, 'right', 1, 10, [300, 300]), layout);
  assert.equal(resizeGroups(layout, 'right', 0, 10, [300]), layout);
});

test('a dragged tab lands by where the pointer is over the groups', () => {
  const groups = [
    { side: 'left', index: 0, left: 0, right: 300, top: 0, bottom: 400, tabsBottom: 40 },
    { side: 'right', index: 0, left: 900, right: 1200, top: 0, bottom: 400, tabsBottom: 40 },
  ];
  const zones = [{ side: 'left', left: 0, right: 60, top: 0, bottom: 900 }];
  assert.deepEqual(dropTarget({ x: 100, y: 20 }, groups), { side: 'left', index: 0, place: 'tab' });
  assert.deepEqual(dropTarget({ x: 100, y: 100 }, groups), { side: 'left', index: 0, place: 'above' });
  assert.deepEqual(dropTarget({ x: 100, y: 220 }, groups), { side: 'left', index: 0, place: 'tab' });
  assert.deepEqual(dropTarget({ x: 1000, y: 390 }, groups), { side: 'right', index: 0, place: 'below' });
  assert.equal(dropTarget({ x: 600, y: 200 }, groups), null);
  // A group wins over an edge strip under it; the strip takes the rest of the edge.
  assert.deepEqual(dropTarget({ x: 30, y: 20 }, groups, zones).place, 'tab');
  assert.deepEqual(dropTarget({ x: 30, y: 600 }, groups, zones), { side: 'left', index: 0, place: 'end' });
});

test('the saved layout is the plain shape with sizes rounded', () => {
  const layout = movePanel(defaultDock(), 'experts', { side: 'left', index: 0, place: 'below' });
  const saved = dockForSaving(resizeGroups(layout, 'left', 0, 33, [300, 300]));
  assert.deepEqual(saved.left.groups.map((g) => g.size), [0.555, 0.445]);
  assert.deepEqual(normalizeDock(JSON.parse(JSON.stringify(saved))).left.groups.map((g) => g.tabs), [['conductor'], ['experts']]);
});
