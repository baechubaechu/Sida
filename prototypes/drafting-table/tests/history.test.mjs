import test from 'node:test';
import assert from 'node:assert/strict';
import { createHistory, historyReducer as reduce, canUndo } from '../src/table/history.js';

const initial = { papers: [{ id: 'site', kind: 'site', x: 0 }, { id: 'note', kind: 'note', text: '원본', x: 10 }], pins: [] };
const change = (history, update) => reduce(history, { type: 'change', update });

test('card deletion and its pin undo/redo together', () => {
  const value = { ...initial, pins: [{ id: 'pin', paper: 'note' }] };
  let h = change(createHistory(value), (doc) => ({ papers: doc.papers.filter((p) => p.id !== 'note'), pins: [] }));
  h = reduce(h, { type: 'undo' });
  assert.deepEqual(h.present, value);
  h = reduce(h, { type: 'redo' });
  assert.equal(h.present.papers.length, 1);
  assert.deepEqual(h.present.pins, []);
});

test('many drag updates are a single undo step and do not mutate the initial value', () => {
  let h = reduce(createHistory(initial), { type: 'begin' });
  for (const x of [20, 30, 40]) h = change(h, (doc) => ({ ...doc, papers: doc.papers.map((p) => ({ ...p, x })) }));
  assert.ok(canUndo(h));
  h = reduce(h, { type: 'finish' });
  assert.equal(h.past.length, 1);
  assert.equal(initial.papers[1].x, 10);
  assert.deepEqual(reduce(h, { type: 'undo' }).present, initial);
});

test('note creation and typing can undo as one action, including before blur', () => {
  let h = reduce(createHistory(initial), { type: 'begin' });
  h = change(h, (doc) => ({ ...doc, papers: [...doc.papers, { id: 'new', text: '' }] }));
  h = change(h, (doc) => ({ ...doc, papers: doc.papers.map((p) => p.id === 'new' ? { ...p, text: '수정' } : p) }));
  const undone = reduce(h, { type: 'undo' });
  assert.deepEqual(undone.present, initial);
  assert.equal(reduce(undone, { type: 'redo' }).present.papers.at(-1).text, '수정');
});

test('new edits invalidate redo while empty or cancelled edits preserve it', () => {
  let h = change(createHistory(initial), (doc) => ({ ...doc, pins: [{ id: 'new' }] }));
  h = reduce(h, { type: 'undo' });
  h = reduce(reduce(h, { type: 'begin' }), { type: 'finish' });
  assert.equal(h.future.length, 1);
  h = reduce(h, { type: 'begin' });
  h = change(h, (doc) => ({ ...doc, pins: [{ id: 'preview' }] }));
  h = reduce(h, { type: 'cancel' });
  assert.deepEqual(h.present, initial);
  assert.equal(h.future.length, 1);
  h = change(h, (doc) => ({ ...doc, pins: [{ id: 'different' }] }));
  assert.equal(h.future.length, 0);
});

test('a cancelled stroke, no-op deletion or round-trip drag creates no undo entry', () => {
  let h = createHistory(initial);
  h = change(h, (doc) => ({ ...doc, papers: [...doc.papers] }));
  h = reduce(h, { type: 'begin' });
  h = change(h, (doc) => ({ ...doc, pins: [{ id: 'temporary' }] }));
  h = change(h, () => initial);
  h = reduce(h, { type: 'finish' });
  assert.equal(h.past.length, 0);
  assert.ok(!canUndo(h));
});

test('history retains at most 100 changes and safely handles empty undo/redo', () => {
  let h = createHistory(initial);
  assert.deepEqual(reduce(h, { type: 'undo' }), h);
  assert.deepEqual(reduce(h, { type: 'redo' }), h);
  for (let i = 0; i < 120; i++) h = change(h, (doc) => ({ ...doc, pins: [{ id: i }] }));
  assert.equal(h.past.length, 100);
});
