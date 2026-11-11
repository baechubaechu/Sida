// The command line's behaviour: Enter, Esc, Tab, up/down, and what each command does.

import { visibleExperts, projectPath as projectUrl, sitePath, EXPORT_FORMATS } from './model.js';
import { COMMANDS, suggest, pickOption, addHistory, remember, readRadii } from './command-model.js';
import { talkPanel } from './talk-panel-model.js';
import { reveal, setSideOpen, sideShown } from './dock-model.js';
import { resetDock, saveDock } from './dock.js';
import { downloadBoard, table, toggleVWorld } from './board.js';
import { runExpert } from './experts.js';
import { openIdeas } from './ideas.js';
import { render } from './render.js';
import { openSettings } from './settings.js';
import { app, currentRoute, draftFor, drafts, ui } from './state.js';
import { askFromLine } from './talks.js';
import { resolveLine, updateCommandLine } from './view-command.js';

// ------------------------------------------------------------------ the command line

export function say(text, tone = 'info') {
  ui.cmd.lines = addHistory(ui.cmd.lines, text, tone);
}

export function focusCommandLine() {
  const input = app.querySelector('#command-input');
  if (!input) return false;
  input.focus({ preventScroll: true });
  input.setSelectionRange(input.value.length, input.value.length);
  return true;
}

// Enter on the command line: answer the open question, run a command, or ask the Conductor.
export async function runCommandLine() {
  const name = currentRoute.name;
  const input = app.querySelector('#command-input');
  const text = input ? input.value : draftFor('command');
  const c = ui.cmd;
  c.back = -1;
  if (c.prompt?.read) {
    // A question answered by typing a value (the radius command's radii); its buttons type their key.
    if (!text.trim()) { cancelCommand(); return; }
    const value = c.prompt.read(text);
    if (value == null) { say(`'${text.trim()}'은(는) 읽을 수 없습니다. ${c.prompt.example}`, 'warn'); drafts.delete('command'); render(false); focusCommandLine(); return; }
    const { prompt } = c;
    c.prompt = null;
    drafts.delete('command');
    prompt.answer(value);
    render(false);
    focusCommandLine();
    return;
  }
  if (c.prompt) {
    const option = pickOption(text, c.prompt.options);
    if (!text.trim()) { cancelCommand(); return; }
    if (!option) { say(`'${text.trim()}'은(는) 보기에 없습니다. 번호나 이름을 입력하세요.`, 'warn'); drafts.delete('command'); render(false); focusCommandLine(); return; }
    const { prompt } = c;
    c.prompt = null;
    drafts.delete('command');
    prompt.answer(option);
    render(false);
    focusCommandLine();
    return;
  }
  const line = resolveLine(text);
  if (line.kind === 'empty') {
    if (c.last) runCommand(name, COMMANDS.find((x) => x.name === c.last));
    render(false);
    focusCommandLine();
    return;
  }
  c.typed = remember(c.typed, text);
  drafts.delete('command');
  c.pick = 0;
  if (line.kind === 'command') {
    if (line.viaKorean) say(`한글 자판으로 친 '${text.trim()}'을(를) ${line.command.name}(으)로 읽었습니다.`);
    runCommand(name, line.command);
    render(false);
    focusCommandLine();
    return;
  }
  render(false);
  if (!(await askFromLine(name, line.text))) drafts.set('command', text);
  render(false);
}

function cancelCommand() {
  const c = ui.cmd;
  if (c.prompt) say('취소했습니다.');
  c.prompt = null;
  c.help = false;
  ui.conductor = { ...ui.conductor, list: false };
  c.pick = 0;
  c.back = -1;
  drafts.delete('command');
  render(false);
  focusCommandLine();
}

const TABLE_COMMANDS = new Set(['plan', 'persp', 'iso', 'zoom', 'north', 'select', 'note', 'pen', 'trace', 'mass', 'photo', 'delete', 'undo', 'redo', 'tray',
  'rect', 'pushpull', 'move', 'copy', 'rotate', 'scale', 'eraser', 'dist', 'radius', 'eye', 'people', 'group', 'ungroup', 'section']);

function runCommand(name, command) {
  if (!command) return;
  const c = ui.cmd;
  c.last = command.name;
  c.help = false;
  if (TABLE_COMMANDS.has(command.name)) {
    if (!table) {
      say(`${command.name}: 제도판을 아직 불러오지 못했습니다.`, 'warn');
      return;
    }
    ui.pane = 'board';
    const problem = table.command(command.name);
    say(problem ? `${command.name}: ${problem}` : `${command.name} — ${command.label}`, problem ? 'warn' : 'info');
    // As in CAD, radius then asks for the radii: circles about the middle of the site. Clicking
    // two points on the table works as well, with the question still open.
    if (!problem && command.name === 'radius') {
      c.prompt = {
        text: '대지 가운데에 그릴 반경(m)? 제도판에서 두 점을 찍어도 됩니다.',
        example: '500이나 250 500 1000처럼 m로 적으세요.',
        placeholder: '반경(m), 예: 500 또는 250 500 1000 (Esc 취소)',
        options: [['250', '250 m'], ['500', '500 m'], ['1000', '1 km'], ['250 500 1000', '250·500·1000 m']].map(([key, label]) => ({ key, label })),
        read: readRadii,
        answer: (radii) => table.circlesAtSite(radii),
      };
    }
    return;
  }
  switch (command.name) {
    case 'board':
      if (currentRoute.agent || currentRoute.site) {
        location.hash = projectUrl(name);
        say('board — 오른쪽 페이지를 닫았습니다.');
      } else {
        const fold = sideShown(ui.dock, 'right');
        ui.dock = setSideOpen(ui.dock, 'right', !fold);
        saveDock();
        say(fold ? 'board — 오른쪽 패널을 접었습니다.' : 'board — 오른쪽 패널을 폈습니다.');
      }
      ui.pane = 'board';
      break;
    case 'layout':
      resetDock();
      say('layout — 패널을 기본 배치로 되돌렸습니다 (왼쪽 대화, 오른쪽 속성·레이어·전문가).');
      break;
    case 'site':
      location.hash = sitePath(name);
      say('site — 대지 페이지를 엽니다.');
      break;
    case 'talks':
      ui.conductor = talkPanel(ui.conductor, 'list');
      ui.dock = reveal(ui.dock, 'conductor');
      saveDock();
      ui.pane = 'conductor';
      say(ui.conductor.list ? 'talks — 대화 목록을 열었습니다.' : 'talks — 대화로 돌아갑니다.');
      break;
    case 'idea':
      openIdeas(name);
      say('idea — 아이디어 보드를 폈습니다. 제도판 위 창에 적거나 대화에서 ＋ 아이디어로를 누르세요.');
      break;
    case 'export':
      c.prompt = {
        text: '어떤 파일로 내보낼까요?',
        options: EXPORT_FORMATS.map((f) => ({ key: f.key, label: f.label })),
        answer: (option) => { downloadBoard(name, option.key); },
      };
      break;
    case 'vworld':
      toggleVWorld(name);
      say(ui.vworld ? 'vworld — 제도판으로 돌아갑니다.' : 'vworld — 브이월드 3D 지도에 매스안을 세웁니다. 건물을 누르면 숨겨집니다.');
      break;
    case 'settings':
      openSettings();
      break;
    case 'help':
      c.help = true;
      break;
    case 'run': {
      const experts = visibleExperts(ui.session?.experts);
      if (!experts.length) { say('run: 전문가 목록을 아직 불러오지 못했습니다.', 'warn'); break; }
      c.prompt = {
        text: '어느 전문가를 실행할까요?',
        options: experts.map((e) => ({ key: e.id, label: e.name })),
        answer: (option) => { say(`run — ${option.label}을(를) 실행합니다.`); runExpert(name, option.key); },
      };
      break;
    }
    default:
      say(`${command.name}: 아직 쓸 수 없는 명령입니다.`, 'warn');
  }
}

// Keys on the command line: Enter runs, Shift+Enter breaks the line, ↑↓ pick a suggestion or
// go through earlier lines, Tab completes, Esc cancels. Enter while a Korean letter is still
// being composed belongs to the input method, not to the line.
export function commandKey(event) {
  const input = event.target;
  const c = ui.cmd;
  const offered = c.prompt ? [] : suggest(input.value);
  if (event.key === 'Enter' && !event.shiftKey && !event.isComposing && event.keyCode !== 229) {
    event.preventDefault();
    runCommandLine();
  } else if (event.key === 'Escape') {
    event.preventDefault();
    cancelCommand();
  } else if (event.key === 'Tab' && offered.length && !event.shiftKey) {
    event.preventDefault();
    input.value = offered[Math.min(c.pick, offered.length - 1)].name;
    drafts.set('command', input.value);
    c.pick = 0;
    updateCommandLine();
  } else if ((event.key === 'ArrowUp' || event.key === 'ArrowDown') && !event.isComposing) {
    const down = event.key === 'ArrowDown';
    if (offered.length > 1) {
      event.preventDefault();
      c.pick = (c.pick + (down ? 1 : -1) + offered.length) % offered.length;
      updateCommandLine();
    } else if (!input.value.includes('\n') && c.typed.length) {
      event.preventDefault();
      const at = c.back < 0 ? c.typed.length : c.back;
      const next = down ? at + 1 : Math.max(0, at - 1);
      c.back = next >= c.typed.length ? -1 : next;
      input.value = c.back < 0 ? '' : c.typed[c.back];
      drafts.set('command', input.value);
      updateCommandLine();
    }
  }
}
