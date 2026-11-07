// Values the drafting table's files share: the tools, snapping, detail labels.

export const SNAP = 7; // metres: a tracing sheet this close to its place on the site clicks into register
export const typing = (el) => el && (el.tagName === 'TEXTAREA' || el.tagName === 'INPUT' || el.tagName === 'SELECT' || el.isContentEditable);
// The tools, with SketchUp's basic modeling tools on blocks (2026-11-02 지훈). No single-key
// shortcuts: a tool starts from its button or its command word on the command line (`cmd`).
export const TOOLS = [
  { id: 'select', label: '선택', cmd: 'select', icon: '↖' },
  { id: 'rect', label: '사각형', cmd: 'rect', icon: '▭', group: 'model', hint: '땅 위에서 끌어 새 동을 그립니다. 그다음 밀고끌기(pushpull)로 올리세요.' },
  { id: 'push', label: '밀고끌기', cmd: 'pushpull', icon: '⇕', group: 'model', hint: '면을 끌어서 조절하거나, 클릭해 목표 층수·길이를 숫자로 입력합니다.' },
  { id: 'move', label: '이동', cmd: 'move', icon: '✥', group: 'model', hint: '고른 동(또는 누른 동)을 끌어 옮깁니다. Ctrl을 누르고 시작하면 복사합니다.' },
  { id: 'rotate', label: '회전', cmd: 'rotate', icon: '⟲', group: 'model', hint: '고른 동(또는 누른 동)의 가운데를 기준으로 끌어 돌립니다. 5° 단위, Shift는 1° 단위.' },
  { id: 'scale', label: '크기', cmd: 'scale', icon: '⤡', group: 'model', hint: '동을 끌어서 크기를 조절하거나, 클릭해 배율을 입력합니다. 층수는 유지됩니다.' },
  { id: 'erase', label: '지우개', cmd: 'eraser', icon: '⌫', group: 'model', hint: '누르거나 끌고 지나간 동을 지웁니다.' },
  { id: 'tape', label: '줄자', cmd: 'dist', icon: '↔', group: 'model', hint: '매스 꼭짓점·모서리와 대지·트레이싱 선에 스냅합니다. Alt를 누르면 스냅을 끕니다.' },
  { id: 'note', label: '메모', cmd: 'note', icon: '▤' },
  { id: 'pen', label: '펜', cmd: 'pen', icon: '✎' },
];
export const MODEL_TOOLS = new Set(TOOLS.filter((t) => t.group === 'model').map((t) => t.id));
export const DETAIL_KINDS = { site: '대지 자료', mass: '매스안', expert: '전문가 검토', tracing: '트레이싱', note: '설계 메모', photo: '사진' };
export const PHOTO_GAP = 3; // metres between photos dropped together
export const cm = (metres) => Math.round(metres * 100) / 100; // pen points are kept to the centimetre
export const strokePath = (pts) => pts.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(2)} ${(-y).toFixed(2)}`).join(' ');
