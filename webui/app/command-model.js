// The command line at the bottom of the workspace, as pure functions (tested in
// tests/webui/command-model.test.mjs). What the line does with a command lives in app.js and
// table.js; this file only decides what was typed.
//
// The rule (2026-11-01, 지훈): one word with no space that is a command name runs that command,
// as in CAD and Rhino; anything else is a question for the Conductor. Command names are English,
// as in CAD and Rhino, with the AutoCAD short names. A command typed with the Korean keyboard on
// (ㅣㅑㅜㄷ for line) is read back as the English keys.

// group: shown in help. Only commands that work are listed; drawing commands come next.
export const COMMANDS = [
  { name: 'plan', aliases: ['top'], label: '평면으로 보기', group: 'view' },
  { name: 'axo', aliases: [], label: '액소로 보기', group: 'view' },
  { name: 'persp', aliases: ['perspective'], label: '투시로 보기', group: 'view' },
  { name: 'zoom', aliases: ['z'], label: '전체 맞춤', group: 'view' },
  { name: 'north', aliases: [], label: '북쪽을 위로', group: 'view' },
  { name: 'select', aliases: [], label: '선택 도구', group: 'draw' },
  { name: 'note', aliases: ['text'], label: '메모 붙이기 (제도판을 누른 자리에)', group: 'draw' },
  { name: 'pen', aliases: ['sketch'], label: '펜으로 그리기 (평면에서)', group: 'draw' },
  { name: 'trace', aliases: [], label: '트레이싱지 덮기', group: 'draw' },
  { name: 'mass', aliases: [], label: '숫자로 매스안 만들기', group: 'draw' },
  { name: 'delete', aliases: ['erase', 'e'], label: '고른 것 지우기', group: 'edit' },
  { name: 'undo', aliases: ['u'], label: '되돌리기', group: 'edit' },
  { name: 'redo', aliases: [], label: '다시 하기', group: 'edit' },
  { name: 'tray', aliases: ['ai'], label: 'AI 섹션 열고 닫기', group: 'panel' },
  { name: 'board', aliases: ['table'], label: '제도판만 보기 (오른쪽 칸 접기·펴기)', group: 'panel' },
  { name: 'site', aliases: [], label: '대지 페이지 열기', group: 'panel' },
  { name: 'run', aliases: [], label: '전문가 실행', group: 'panel' },
  { name: 'talks', aliases: ['history'], label: 'Conductor 대화 목록 열고 닫기', group: 'panel' },
  { name: 'settings', aliases: ['options'], label: '설정 열기', group: 'panel' },
  { name: 'help', aliases: ['?'], label: '명령 목록 보기', group: 'panel' },
];

export const GROUP_LABELS = { view: '보기', draw: '그리기', edit: '편집', panel: '패널' };

// ------------------------------------------------------------------ Korean keyboard

// The 2-set (두벌식) Korean keyboard: which English key makes each jamo.
const KEYS = {
  ㄱ: 'r', ㄲ: 'R', ㄴ: 's', ㄷ: 'e', ㄸ: 'E', ㄹ: 'f', ㅁ: 'a', ㅂ: 'q', ㅃ: 'Q', ㅅ: 't', ㅆ: 'T',
  ㅇ: 'd', ㅈ: 'w', ㅉ: 'W', ㅊ: 'c', ㅋ: 'z', ㅌ: 'x', ㅍ: 'v', ㅎ: 'g',
  ㅏ: 'k', ㅐ: 'o', ㅑ: 'i', ㅒ: 'O', ㅓ: 'j', ㅔ: 'p', ㅕ: 'u', ㅖ: 'P', ㅗ: 'h', ㅘ: 'hk', ㅙ: 'ho',
  ㅚ: 'hl', ㅛ: 'y', ㅜ: 'n', ㅝ: 'nj', ㅞ: 'np', ㅟ: 'nl', ㅠ: 'b', ㅡ: 'm', ㅢ: 'ml', ㅣ: 'l',
  ㄳ: 'rt', ㄵ: 'sw', ㄶ: 'sg', ㄺ: 'fr', ㄻ: 'fa', ㄼ: 'fq', ㄽ: 'ft', ㄾ: 'fx', ㄿ: 'fv', ㅀ: 'fg', ㅄ: 'qt',
};
const INITIALS = 'ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ';
const MEDIALS = 'ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ';
const FINALS = ['', ...'ㄱㄲㄳㄴㄵㄶㄷㄹㄺㄻㄼㄽㄾㄿㅀㅁㅂㅄㅅㅆㅇㅈㅊㅋㅌㅍㅎ'];

const HANGUL = /[ㄱ-ㆎ가-힣]/;

// The English keys behind Korean text typed with the Korean keyboard on, lower-cased:
// 'ㅣㅑㅜㄷ' → 'line', '채ㅔㅛ' → 'copy'. Other characters are kept. '' when there is no Hangul.
export function englishKeys(text) {
  const value = String(text ?? '');
  if (!HANGUL.test(value)) return '';
  let out = '';
  for (const ch of value) {
    const code = ch.charCodeAt(0) - 0xac00;
    if (code >= 0 && code < 11172) {
      out += KEYS[INITIALS[Math.floor(code / 588)]] + KEYS[MEDIALS[Math.floor((code % 588) / 28)]] + (KEYS[FINALS[code % 28]] || '');
    } else {
      out += KEYS[ch] ?? ch;
    }
  }
  return out.toLowerCase();
}

// ------------------------------------------------------------------ reading a line

const byName = new Map(COMMANDS.flatMap((c) => [[c.name, c], ...c.aliases.map((a) => [a, c])]));

// The command a typed word names, or null. `viaKorean` is true when it was typed with the
// Korean keyboard on. A single Korean letter is never read as a command (ㅋ is not zoom).
export function findCommand(word) {
  const typed = String(word ?? '').trim();
  if (!typed || /\s/.test(typed)) return null;
  const direct = byName.get(typed.toLowerCase());
  if (direct) return { command: direct, viaKorean: false };
  const keys = englishKeys(typed);
  if (keys.length < 2) return null;
  const korean = byName.get(keys);
  return korean ? { command: korean, viaKorean: true } : null;
}

// What Enter does with the line: { kind: 'empty' } | { kind: 'command', command, viaKorean }
// | { kind: 'ask', text }. Everything that is not one command word goes to the Conductor.
export function readLine(text) {
  const value = String(text ?? '').trim();
  if (!value) return { kind: 'empty' };
  const found = findCommand(value);
  return found ? { kind: 'command', ...found } : { kind: 'ask', text: value };
}

// Commands to offer while one word is being typed: exact names first, then names and short
// names that start with it. [] once there is a space (a sentence for the Conductor).
export function suggest(text, limit = 6) {
  const value = String(text ?? '').trimStart();
  if (!value || /\s/.test(value)) return [];
  const words = [value.toLowerCase()];
  const keys = englishKeys(value);
  if (keys.length >= 2) words.push(keys);
  const score = (c) => {
    let best = Infinity;
    for (const w of words) {
      if (c.name === w || c.aliases.includes(w)) best = Math.min(best, 0);
      else if (c.name.startsWith(w)) best = Math.min(best, 1);
      else if (c.aliases.some((a) => a.startsWith(w))) best = Math.min(best, 2);
    }
    return best;
  };
  return COMMANDS.map((c, i) => ({ c, s: score(c), i }))
    .filter((x) => x.s < Infinity)
    .sort((a, b) => a.s - b.s || a.i - b.i)
    .slice(0, limit)
    .map((x) => x.c);
}

// ------------------------------------------------------------------ a command's question

// A command that needs a choice asks for it on the line, as in CAD ("어느 전문가? [1] 대지 분석가 …").
// The answer is the option's number, its key or its label (case-insensitive, a label may be
// started). Returns the option, or null.
export function pickOption(text, options) {
  const value = String(text ?? '').trim().toLowerCase();
  if (!value) return null;
  const number = Number(value);
  if (Number.isInteger(number) && number >= 1 && number <= options.length) return options[number - 1];
  return options.find((o) => o.key.toLowerCase() === value || o.label.toLowerCase() === value)
    || options.find((o) => o.label.toLowerCase().startsWith(value) || o.key.toLowerCase().startsWith(value))
    || null;
}

// The newest lines of the command history, oldest first.
export const HISTORY_LINES = 3;
export function addHistory(lines, text, tone = 'info', keep = 20) {
  return [...lines, { text, tone }].slice(-keep);
}

// Previous typed lines for ↑ and ↓: the newest last, no empty lines or repeats in a row.
export function remember(typed, text, keep = 30) {
  const value = String(text ?? '').trim();
  if (!value || typed[typed.length - 1] === value) return typed;
  return [...typed, value].slice(-keep);
}
