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
  { name: 'persp', aliases: ['perspective'], label: '3D로 보기', group: 'view' },
  { name: 'iso', aliases: ['isometric'], label: '아이소로 보기 (평행투영, 다시 하면 90° 돌아감)', group: 'view' },
  { name: 'zoom', aliases: ['z'], label: '전체 맞춤', group: 'view' },
  { name: 'north', aliases: [], label: '북쪽을 위로', group: 'view' },
  { name: 'select', aliases: [], label: '선택 도구', group: 'draw' },
  { name: 'note', aliases: ['text'], label: '메모 붙이기 (제도판을 누른 자리에)', group: 'draw' },
  { name: 'pen', aliases: ['sketch'], label: '펜으로 그리기 (평면에서)', group: 'draw' },
  { name: 'trace', aliases: [], label: '트레이싱지 덮기', group: 'draw' },
  { name: 'mass', aliases: [], label: '숫자로 매스안 만들기', group: 'draw' },
  { name: 'people', aliases: ['person', 'figure'], label: '사람 배치: 바닥이나 매스 지붕을 눌러 사람 모형(1.7m) 세우기, 대지 주변에 뿌리기', group: 'draw' },
  { name: 'photo', aliases: ['picture', 'image', 'img'], label: '사진·PDF 올리기 (끌어다 놓거나 붙여넣어도 됨)', group: 'draw' },
  { name: 'section', aliases: ['sec'], label: '단면: 평면에서 끌어 단면선 긋기 (단면도 종이·3D 자르기·SVG/PDF/DXF)', group: 'draw' },
  // SketchUp's basic tools on blocks (2026-11-02 지훈), with the AutoCAD short names.
  { name: 'rect', aliases: ['rec', 'rectangle'], label: '사각형: 끌어서 새 동 그리기', group: 'draw' },
  { name: 'pushpull', aliases: ['pp', 'push'], label: '밀고끌기: 끌어서 조절 · 클릭하면 층수·길이 입력', group: 'draw' },
  { name: 'move', aliases: ['m'], label: '이동: 동 옮기기, Ctrl은 복사', group: 'edit' },
  { name: 'copy', aliases: ['co', 'cp'], label: '복사: 동을 끌어 복사', group: 'edit' },
  { name: 'rotate', aliases: ['ro'], label: '회전: 동 돌리기', group: 'edit' },
  { name: 'scale', aliases: ['sc'], label: '크기: 끌어서 조절 · 클릭하면 배율 입력', group: 'edit' },
  { name: 'eraser', aliases: [], label: '지우개: 누르거나 끌고 지나간 동 지우기', group: 'edit' },
  { name: 'dist', aliases: ['di', 'measure', 'tape'], label: '줄자: 두 점을 찍어 거리 재기', group: 'edit' },
  { name: 'radius', aliases: ['ra'], label: '반경: 중심과 끝점을 찍어 원 그리기 · 이어서 반경(m)을 치면 대지 가운데에 원', group: 'edit' },
  { name: 'delete', aliases: ['erase', 'e'], label: '고른 것 지우기', group: 'edit' },
  { name: 'group', aliases: [], label: '고른 것을 그룹으로 묶기: 하나를 누르면 함께 골라짐 (Ctrl+G)', group: 'edit' },
  { name: 'ungroup', aliases: [], label: '그룹 풀기 (Ctrl+Shift+G)', group: 'edit' },
  { name: 'undo', aliases: ['u'], label: '되돌리기', group: 'edit' },
  { name: 'redo', aliases: [], label: '다시 하기', group: 'edit' },
  { name: 'tray', aliases: ['ai'], label: 'AI 섹션 열고 닫기', group: 'panel' },
  { name: 'board', aliases: ['table'], label: '제도판만 보기 (오른쪽 칸 접기·펴기)', group: 'panel' },
  { name: 'layout', aliases: [], label: '패널 기본 배치로 (끌어 옮긴 탭·나눈 칸 되돌리기)', group: 'panel' },
  { name: 'site', aliases: [], label: '대지 페이지 열기', group: 'panel' },
  { name: 'run', aliases: [], label: '전문가 실행', group: 'panel' },
  { name: 'talks', aliases: ['history'], label: 'Conductor 대화 목록 열고 닫기', group: 'panel' },
  { name: 'idea', aliases: ['ideas'], label: '아이디어 보드 펴기 (제도판 위 창)', group: 'panel' },
  { name: 'export', aliases: ['exp'], label: '내보내기: CAD(DXF)·라이노(3dm) 파일로', group: 'panel' },
  { name: 'eye', aliases: ['walk'], label: '눈높이 보기: 땅 위 한 점을 눌러 그 자리 사람 눈높이(1.6m)에서 매스 보기', group: 'view' },
  { name: 'vworld', aliases: ['vw'], label: '브이월드 3D 지도에 매스안 세워 보기 (건물을 누르면 숨김)', group: 'view' },
  { name: 'around', aliases: ['context'], label: '주변 3D 켜고 끄기 (주변 건물·도로·지형, 설정은 레이어 패널의 주변)', group: 'view' },
  { name: 'envelope', aliases: ['legal', 'volume'], label: '법규 볼륨 켜고 끄기: 정북일조·건폐율·용적률로 지을 수 있는 볼륨과 참고 매스', group: 'view' },
  { name: 'landscape', aliases: ['green', 'garden'], label: '자동 조경: 매스 밖 땅에 조경 세 안을 조례·조경기준대로 그려 보기', group: 'view' },
  { name: 'clip', aliases: ['cut'], label: '3D 자르기: 단면선으로 3D를 잘라 보기 (다시 하면 끔)', group: 'view' },
  { name: 'diagram', aliases: ['diagrams', 'analysis'], label: '대지분석 다이어그램: 피겨-그라운드·높이·용도·그림자 등 9종 열기', group: 'panel' },
  { name: 'base', aliases: ['modelbase'], label: '모형 바닥: 레이저 커팅 대지 모형 판 열기', group: 'panel' },
  { name: 'deck', aliases: ['slides', 'ppt'], label: '발표 자료 열기 (발표 편집자의 발표자료 탭)', group: 'panel' },
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
// | { kind: 'landscape', ... } (readLandscape) | { kind: 'ask', text }. Everything that is not one
// command word, or a short 조경 line every word of which is read by rule, goes to the Conductor.
export function readLine(text) {
  const value = String(text ?? '').trim();
  if (!value) return { kind: 'empty' };
  const found = findCommand(value);
  if (found) return { kind: 'command', ...found };
  const landscape = readLandscape(value);
  return landscape ? { kind: 'landscape', ...landscape } : { kind: 'ask', text: value };
}

// ------------------------------------------------------------------ 조경 in a few words

// "조경 광장 넓게 나무 더", "조경 자연형 관목 없이 길 2m" (2026-11-20 4단계 견본): the 자동 조경's
// knobs turned by rule, no AI. The line starts with 조경; each following word must be read, or
// the whole line goes to the Conductor (which may propose a layout of its own). Returns
// { style, tune: {plaza?, trees?, path?, hedge?}, reset, shuffle, place, compare, words } or null.
const LANDSCAPE_STYLES = { 정형: 'formal', 자연형: 'natural', 광장형: 'plaza' };
const PLAZA_WORDS = { 작게: 'small', 좁게: 'small', 보통: 'normal', 기본: 'normal', 넓게: 'wide', 크게: 'wide', 최대: 'widest' };
const TREE_WORDS = { 더: 'more', '25%': 'more', '+25%': 'more', 많이: 'most', '50%': 'most', '+50%': 'most', 최대: 'room', 가득: 'room', 자리만큼: 'room',
  법정: 'law', 기본: 'law', 보통: 'law' };
const LANDSCAPE_SAY = {
  plaza: { small: '광장 작게', normal: '광장 보통', wide: '광장 넓게', widest: '광장 아주 넓게' },
  trees: { law: '나무 법정 수량', more: '나무 25% 더', most: '나무 50% 더', room: '나무 자리만큼' },
  style: { formal: '정형', natural: '자연형', plaza: '광장형' },
};
const metres = (w) => {
  const m = /^(\d+(?:\.\d+)?)m?$/.exec(w);
  return m ? Number(m[1]) : null;
};
export function readLandscape(text) {
  const words = String(text ?? '').trim().split(/[\s,]+/).filter(Boolean);
  if (words[0] !== '조경') return null;
  const out = { style: null, tune: {}, reset: false, shuffle: false, place: false, compare: false, words: [] };
  for (let i = 1; i < words.length; i += 1) {
    const w = words[i];
    const next = words[i + 1];
    if (LANDSCAPE_STYLES[w]) { out.style = LANDSCAPE_STYLES[w]; out.words.push(w); continue; }
    if (w === '광장') {
      if (next === '아주' || (next === '더' && words[i + 2] === '넓게')) {
        if (words[i + 2] !== '넓게' && words[i + 2] !== '크게') return null;
        out.tune.plaza = 'widest'; i += 2;
      } else if (PLAZA_WORDS[next]) { out.tune.plaza = PLAZA_WORDS[next]; i += 1; } else return null;
      out.words.push(LANDSCAPE_SAY.plaza[out.tune.plaza]);
      continue;
    }
    if (w === '나무' || w === '교목') {
      if (next === '더' && words[i + 2] === '많이') { out.tune.trees = 'most'; i += 2; } else if (TREE_WORDS[next]) { out.tune.trees = TREE_WORDS[next]; i += 1; } else return null;
      out.words.push(LANDSCAPE_SAY.trees[out.tune.trees]);
      continue;
    }
    if (w === '길') {
      const v = next === '기본' ? null : next === '넓게' ? 3 : next === '좁게' ? 1.5 : metres(next ?? '');
      if (v === null && next !== '기본') return null;
      if (v !== null && !(v >= 1.5 && v <= 4)) return null;
      out.tune.path = v; i += 1;
      out.words.push(v === null ? '길 폭 기본' : `길 ${v.toFixed(1)}m`);
      continue;
    }
    if (w === '관목' || w === '관목띠') {
      let at = i + 1;
      if (words[at] === '띠') at += 1;
      const said = words[at];
      const v = ['없이', '없음', '빼기', '빼고'].includes(said) ? 0 : said === '기본' ? null : said === '넓게' ? 3 : said === '좁게' ? 1 : metres(said ?? '');
      if (v === null && said !== '기본') return null;
      if (v !== null && !(v === 0 || (v >= 1 && v <= 3))) return null;
      out.tune.hedge = v; i = at;
      out.words.push(v === null ? '관목 띠 기본' : v === 0 ? '관목 띠 없음' : `관목 띠 ${v.toFixed(1)}m`);
      continue;
    }
    if (w === '처음대로' || w === '초기화') { out.reset = true; out.words.push('조절 처음대로'); continue; }
    if (w === '다시' && next === '섞기') { out.shuffle = true; out.words.push('다시 섞기'); i += 1; continue; }
    if (w === '섞기') { out.shuffle = true; out.words.push('다시 섞기'); continue; }
    if (w === '놓기') { out.place = true; out.words.push('제도판에 놓기'); continue; }
    if (w === '비교') { out.compare = true; out.words.push('비교'); continue; }
    return null;
  }
  return out;
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

// The radius command's answer (2026-11-10 지훈): one or more radii in metres, as "500",
// "250 500 1000", "250, 500m" or "1.5km". null when anything else is typed or a radius is not
// between 1 m and 20 km.
export const MAX_RADIUS = 20000;
export function readRadii(text) {
  const words = String(text ?? '').trim().toLowerCase().split(/[\s,]+/).filter(Boolean);
  if (!words.length) return null;
  const radii = [];
  for (const w of words) {
    const m = /^(\d+(?:\.\d+)?)(m|km)?$/.exec(w);
    if (!m) return null;
    const r = Number(m[1]) * (m[2] === 'km' ? 1000 : 1);
    if (!(r >= 1 && r <= MAX_RADIUS)) return null;
    radii.push(r);
  }
  return radii;
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
