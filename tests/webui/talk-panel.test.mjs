import { test } from 'node:test';
import assert from 'node:assert/strict';
import { talkPanel, talkMenu, initialTalk, panelShown, panelWidths, resizePanel } from '../../webui/app/talk-panel-model.js';

test('closing and reopening retains the active conversation and history view', () => {
  const before = { open: true, active: '02', list: true };
  const closed = talkPanel(before, 'close');
  assert.deepEqual(closed, { open: false, active: '02', list: true });
  assert.deepEqual(talkPanel(closed, 'toggle'), before);
  assert.equal(before.open, true);
});

test('removing a conversation drops its active selection without reopening it', () => {
  const state = { open: true, active: '02', list: false };
  assert.deepEqual(talkPanel(state, 'remove', '02'), { open: true, active: '', list: true });
  assert.deepEqual(talkPanel(state, 'remove', '03'), { open: true, active: '02', list: true });
  assert.equal(initialTalk([], null), '');
  assert.equal(state.active, '02');
});

test('conversation actions stay hidden until requested and only one conversation menu opens', () => {
  let menu = talkMenu('', 'toggle', '01');
  assert.equal(menu, '01');
  menu = talkMenu(menu, 'toggle', '02');
  assert.equal(menu, '02');
  assert.equal(talkMenu(menu, 'toggle', '02'), '');
  assert.equal(talkMenu(menu, 'dismiss'), '');
  assert.equal(talkMenu('', 'dismiss'), '');
});

test('selecting a saved conversation opens it and leaves the list', () => {
  assert.deepEqual(talkPanel({ open: false, active: '01', list: true }, 'select', '03'),
    { open: true, active: '03', list: false });
});

test('a new conversation does not silently return to the last saved conversation', () => {
  const talks = [{ id: '01' }, { id: '02' }];
  assert.equal(initialTalk(talks, null), '02');
  const fresh = talkPanel({ open: false, active: '02', list: true }, 'new');
  assert.equal(initialTalk(talks, fresh.active), '');
  assert.equal(initialTalk([], null), '');
  assert.equal(initialTalk(talks, '01'), '01');
});

test('history can be opened while the panel is closed without losing the active talk', () => {
  assert.deepEqual(talkPanel({ open: false, active: '01', list: false }, 'list'),
    { open: true, active: '01', list: true });
});

test('on narrow screens the conversation is open only while its tab is visible', () => {
  const state = { open: true, active: '01', list: false };
  assert.equal(panelShown(state, 'board', false), true);
  assert.equal(panelShown(state, 'board', true), false);
  assert.equal(panelShown(state, 'conductor', true), true);
  assert.equal(panelShown(talkPanel(state, 'close'), 'conductor', false), false);
  assert.equal(talkPanel(talkPanel(state, 'close'), 'show').active, '01');
});

test('both panel widths fit while retaining at least 320px for the board', () => {
  const ratios = { left: .4, right: .4 };
  for (const total of [877, 1000, 1256, 1800]) {
    const widths = panelWidths(total, ratios);
    assert.ok(widths.left >= 280);
    assert.ok(widths.right >= 240);
    assert.ok(widths.board >= 320);
    assert.equal(widths.left + widths.board + widths.right, total);
  }
  assert.deepEqual(ratios, { left: .4, right: .4 });
});

test('folding either panel releases its space and reopening restores the preference', () => {
  const ratios = { left: .3, right: .2 };
  const before = panelWidths(1200, ratios);
  const hidden = panelWidths(1200, ratios, { left: false, right: false });
  assert.deepEqual(hidden, { left: 0, right: 0, board: 1200 });
  assert.equal(panelWidths(1200, ratios, { left: false }).right, before.right);
  assert.equal(panelWidths(1200, ratios, { right: false }).left, before.left);
  assert.deepEqual(panelWidths(1200, ratios), before);
});

test('dragging a boundary changes only that side, stops at limits and can be reversed', () => {
  const widths = { left: 340, right: 260, board: 656 };
  const wider = resizePanel(widths, 'left', 100);
  assert.deepEqual(wider, { left: 440, right: 260, board: 556 });
  assert.deepEqual(resizePanel(wider, 'left', -100), widths);
  assert.equal(resizePanel(widths, 'right', 10000).board, 320);
  assert.equal(resizePanel(widths, 'left', -10000).left, 280);
  assert.equal(resizePanel(widths, 'right', -10000, 320).right, 320);
  assert.deepEqual(widths, { left: 340, right: 260, board: 656 });
});
