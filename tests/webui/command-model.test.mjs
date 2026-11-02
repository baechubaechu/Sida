import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
  COMMANDS, englishKeys, findCommand, readLine, suggest, pickOption, addHistory, remember,
} from '../../webui/app/command-model.js';

test('command names and short names are unique English words', () => {
  const words = COMMANDS.flatMap((c) => [c.name, ...c.aliases]);
  assert.equal(new Set(words).size, words.length);
  for (const w of words) assert.match(w, /^[a-z?]+$/);
});

test('one command word runs the command; anything else goes to the Conductor', () => {
  assert.equal(readLine('plan').command.name, 'plan');
  assert.equal(readLine('  PLAN ').command.name, 'plan');
  assert.equal(readLine('Z').command.name, 'zoom');
  assert.equal(readLine('e').command.name, 'delete');
  assert.deepEqual(readLine('plan 좀 보여줘'), { kind: 'ask', text: 'plan 좀 보여줘' });
  assert.deepEqual(readLine('평면'), { kind: 'ask', text: '평면' });
  assert.deepEqual(readLine('zoomy'), { kind: 'ask', text: 'zoomy' });
  assert.deepEqual(readLine('남향이 나을까?\n두 안을 비교해 줘'), { kind: 'ask', text: '남향이 나을까?\n두 안을 비교해 줘' });
  assert.deepEqual(readLine('   '), { kind: 'empty' });
});

test("SketchUp's basic tools are commands too, with the AutoCAD short names", () => {
  const named = (word) => readLine(word).command?.name;
  assert.equal(named('rect'), 'rect');
  assert.equal(named('rec'), 'rect');
  assert.equal(named('pp'), 'pushpull');
  assert.equal(named('m'), 'move');
  assert.equal(named('co'), 'copy');
  assert.equal(named('ro'), 'rotate');
  assert.equal(named('sc'), 'scale');
  assert.equal(named('scale'), 'scale');
  assert.equal(named('eraser'), 'eraser');
  assert.equal(named('di'), 'dist');
  assert.equal(named('갯ㅁㅅㄷ'), 'rotate'); // typed with the Korean keyboard on
  assert.equal(named('ㄴㅊ믿'), 'scale');
});

test('the Korean keyboard is read back as the English keys', () => {
  assert.equal(englishKeys('ㅣㅑㅜㄷ'), 'line');
  assert.equal(englishKeys('채ㅔㅛ'), 'copy');
  assert.equal(englishKeys('ㅔㅣ무'), 'plan');
  assert.equal(englishKeys('갯ㅁㅅㄷ'), 'rotate');
  assert.equal(englishKeys('ㅉ'), 'w');
  assert.equal(englishKeys('plan'), '');
  assert.deepEqual(findCommand('ㅔㅣ무'), { command: COMMANDS.find((c) => c.name === 'plan'), viaKorean: true });
  assert.equal(readLine('ㅕㅜ애').command.name, 'undo');
});

test('a single Korean letter or a Korean word is never a command', () => {
  assert.equal(findCommand('ㅋ'), null); // would be z (zoom)
  assert.equal(findCommand('ㄷ'), null); // would be e (delete)
  assert.equal(readLine('안녕').kind, 'ask');
  assert.equal(readLine('대지').kind, 'ask');
});

test('suggestions follow the word being typed and stop at a space', () => {
  assert.deepEqual(suggest('p').map((c) => c.name), ['plan', 'persp', 'pen', 'pushpull']);
  assert.deepEqual(suggest('z').map((c) => c.name), ['zoom']);
  assert.equal(findCommand('perspective').command.name, 'persp'); // one 3D view (2026-11-01)
  assert.equal(findCommand('axo'), null);
  assert.deepEqual(suggest('ㅔㅣ').map((c) => c.name), ['plan']);
  assert.equal(suggest('zoom ').length, 0);
  assert.equal(suggest('').length, 0);
  assert.equal(suggest('qqq').length, 0);
  assert.ok(suggest('e')[0].name === 'delete'); // the exact short name comes first
});

test('a command question takes a number, a key or the start of a label', () => {
  const options = [{ key: 'site_reader', label: '대지 분석가' }, { key: 'program_analyst', label: '프로그램 분석가' }];
  assert.equal(pickOption('2', options).key, 'program_analyst');
  assert.equal(pickOption('SITE_READER', options).key, 'site_reader');
  assert.equal(pickOption('프로그램', options).key, 'program_analyst');
  assert.equal(pickOption('3', options), null);
  assert.equal(pickOption('', options), null);
  assert.equal(pickOption('법규', options), null);
});

test('history keeps the newest lines and skips repeats', () => {
  let lines = [];
  for (let i = 0; i < 25; i += 1) lines = addHistory(lines, `l${i}`);
  assert.equal(lines.length, 20);
  assert.equal(lines.at(-1).text, 'l24');
  assert.deepEqual(remember(remember(remember([], 'plan'), 'plan'), '  '), ['plan']);
});
