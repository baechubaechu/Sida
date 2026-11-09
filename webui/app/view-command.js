// The command line at the bottom: what Enter will do, suggestions, help (HTML strings).

import { escapeHtml as escape } from './model.js';
import { pickedNames } from './board-model.js';
import { COMMANDS, GROUP_LABELS, readLine, suggest, HISTORY_LINES } from './command-model.js';
import { panelVisible } from './dock-model.js';
import { app, draftFor, ui } from './state.js';

// What Enter does with the line: while one word is typed, the highlighted suggestion runs.
export function resolveLine(text) {
  const line = readLine(text);
  if (line.kind !== 'ask') return line;
  const offered = suggest(text);
  return offered.length ? readLine(offered[Math.min(ui.cmd.pick, offered.length - 1)].name) : line;
}

// What Enter will do with the line, shown before the input.
function commandMode(text) {
  if (ui.cmd.prompt) return { label: '답', tone: 'prompt' };
  const line = resolveLine(text);
  if (line.kind === 'command') return { label: line.command.name, tone: 'command' };
  if (line.kind === 'ask') return { label: 'AI에게', tone: 'ask' };
  return { label: '명령', tone: 'idle' };
}

function suggestionItems(text) {
  if (ui.cmd.prompt) return '';
  return suggest(text).map((c, i) => `<li role="option" id="cmd-opt-${i}" aria-selected="${i === ui.cmd.pick}" data-action="cmd-pick" data-command="${escape(c.name)}">
      <b>${escape(c.name)}</b>${c.aliases.length ? `<span class="cmd-alias">${escape(c.aliases.join(', '))}</span>` : ''}<span>${escape(c.label)}</span></li>`).join('');
}

function helpCard() {
  const groups = Object.keys(GROUP_LABELS).map((g) => `<div><h3>${escape(GROUP_LABELS[g])}</h3><dl>${COMMANDS.filter((c) => c.group === g)
    .map((c) => `<dt>${escape([c.name, ...c.aliases].join(' · '))}</dt><dd>${escape(c.label)}</dd>`).join('')}</dl></div>`).join('');
  return `<section class="command-help" aria-label="명령 목록"><header><strong>명령</strong>
      <button type="button" class="ghost" data-action="cmd-help" aria-label="명령 목록 닫기">×</button></header>
      <p class="muted">띄어쓰기 없는 영어 한 단어가 명령입니다. 그 밖의 글은 모두 Conductor에게 갑니다. Enter 실행 · Shift+Enter 줄 바꿈 · 빈 칸에서 Enter는 직전 명령 반복 · Esc 취소</p>
      <p class="muted">조작: 왼쪽 끌기 선택 상자(→ 안에 든 것, ← 걸친 것, Shift 더하기, Ctrl 빼기) · 건물 클릭 그 동만 고르기(끌면 옮김, 검볼, Delete 지우기) · Ctrl+C/V 복사·붙여넣기, Ctrl+A 모든 동 · 고른 이름표 끌기 종이 옮기기 · 휠 커서 기준 확대 · 우클릭 끌기 돌리기 · Shift+우클릭·가운데 버튼 끌기 이동 · Ctrl+Z 되돌리기 · 사진·PDF는 끌어다 놓거나 붙여넣기 · 종이 모서리 끌기 크기 조절(글자도 같이) · 종이 위 가운데 핀: 동그라미로 접기 · 제도판에서 글자를 치면 명령창으로</p>
      <p class="muted">제도판: 종이 클릭은 상세 보기, Shift+클릭은 여러 장 골라 대화에 보내기 · 기울이면 배치도가 3D가 됩니다 · 트레이싱지는 대지 위에 덮고, 옆으로 끌어내면 떼어집니다 · 도구 이름과 단축키는 아이콘에 마우스를 올리면 보입니다</p>
      <div class="command-help-groups">${groups}</div></section>`;
}

export function commandBar() {
  const c = ui.cmd;
  const text = draftFor('command');
  const mode = commandMode(text);
  const items = suggestionItems(text);
  const picked = pickedNames(ui.selected, ui.board);
  const shown = matchMedia('(max-width: 900px)').matches ? ui.pane === 'conductor' : panelVisible(ui.dock, 'conductor');
  return `<section class="command-bar" aria-label="명령창">
      ${c.help ? helpCard() : ''}
      <div class="command-top"><ol class="command-history" aria-label="명령 기록">${c.lines.slice(-HISTORY_LINES).map((l) => `<li class="${escape(l.tone)}">${escape(l.text)}</li>`).join('')}
        ${ui.sessionError ? `<li class="error">${escape(ui.sessionError)} <a href="#/">← 프로젝트로 돌아가기</a></li>` : ''}
        ${c.prompt ? `<li class="command-question">${escape(c.prompt.text)} ${c.prompt.options.map((o, i) => `<button type="button" data-action="cmd-option" data-index="${i}">${i + 1} ${escape(o.label)}</button>`).join('')}</li>` : ''}</ol>
      </div>
      <form class="command-form" id="command-form">
        <button type="button" class="command-talks ${shown ? 'open' : ''}" data-action="conductor-toggle" aria-controls="conductor-panel" aria-expanded="${shown}" aria-label="Conductor 대화 ${shown ? '접기' : '열기'}">대화</button>
        <span class="command-mode ${mode.tone}" id="command-mode">${escape(mode.label)}</span>
        ${picked.length ? `<span class="command-picked" title="${escape(picked.map((p) => p.name).join(', '))}">자료 ${picked.length}개</span>` : ''}
        <textarea id="command-input" data-focus="command" rows="1" maxlength="6000" spellcheck="false" autocomplete="off"
          role="combobox" aria-expanded="${Boolean(items)}" aria-controls="command-suggest" aria-autocomplete="list" ${items ? `aria-activedescendant="cmd-opt-${c.pick}"` : ''}
          aria-label="명령 또는 질문" placeholder="${c.prompt ? '번호나 이름을 입력하세요 (Esc 취소)' : '명령(plan, zoom, help…) 또는 Conductor에게 질문'}">${escape(text)}</textarea>
        <button type="submit" class="command-run" aria-label="실행">↵</button>
      </form>
      <ul class="command-suggest" id="command-suggest" role="listbox" aria-label="명령 제안" ${items ? '' : 'hidden'}>${items}</ul>
    </section>`;
}

// The line's mode and suggestions change as it is typed, without redrawing the page.
export function updateCommandLine() {
  const input = app.querySelector('#command-input');
  if (!input) return;
  const mode = commandMode(input.value);
  const label = app.querySelector('#command-mode');
  label.textContent = mode.label;
  label.className = `command-mode ${mode.tone}`;
  const items = suggestionItems(input.value);
  const list = app.querySelector('#command-suggest');
  list.innerHTML = items;
  list.hidden = !items;
  input.setAttribute('aria-expanded', String(Boolean(items)));
  if (items) input.setAttribute('aria-activedescendant', `cmd-opt-${ui.cmd.pick}`);
  else input.removeAttribute('aria-activedescendant');
}
