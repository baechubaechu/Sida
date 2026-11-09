// Drawing the page: the workspace (Conductor, table, experts or a page, command line) from `ui`,
// keeping focus and reading positions, then laying the kept elements (table, map, model board,
// idea window) over their slots.

import { escapeHtml as escape, EXPORT_FORMATS } from './model.js';
import { pickedNames, massIds, canCompare } from './board-model.js';
import { DOCK_PANELS, sideShown } from './dock-model.js';
import { placeModelMaker, placeTable, table } from './board.js';
import { ideaDragging, placeIdeaFloat } from './ideas.js';
import { panelResizing, syncPanelWidths } from './panels.js';
import { dockDragging, dockSplitting, floatMoving } from './dock.js';
import { placeSiteMap } from './site.js';
import { app, conductorScrolls, currentProjectLabel, currentRoute, deferred, expertById, newProjectDialog, settingsWarned, ui } from './state.js';
import { commandBar } from './view-command.js';
import { expertPage } from './view-experts.js';
import { dockView, floatView, narrowDock, sideTitle } from './view-dock.js';
import { homeView, newView } from './view-home.js';
import { ideaFloatView } from './view-ideas.js';
import { sitePage } from './view-site.js';

// The table lives outside the redrawn page (so WebGL, a drag or a note being typed survive
// redraws) and is laid over the page's #table-slot.
const slotWatch = new ResizeObserver(() => { placeTable(); placeIdeaFloat(); });

// The board panel's head: where we are, the panel toggles, and what is picked on the table.
function boardHead(name, site, agent) {
  const picked = pickedNames(ui.selected, ui.board);
  const compare = canCompare(ui.selected, ui.board);
  const masses = massIds(ui.board);
  const selection = picked.length
    ? `<span class="selection-count" role="status">선택 ${picked.length}개</span>
      <div class="selection-items">${picked.map((p) => `<button type="button" data-action="inspect-paper" data-id="${escape(p.id)}" title="상세 보기">${escape(p.name)} ↗</button>`).join('')}</div>
      <button type="button" class="selection-ask" data-action="ask-selection" data-compare="${compare}">${compare ? '두 안 비교 질문 →' : '이 자료로 질문 →'}</button>
      <button type="button" class="selection-clear" data-action="clear-selection" aria-label="선택 모두 해제">×</button>`
    : masses.length ? '<button type="button" class="selection-ask" data-action="select-masses">매스안 선택</button>' : '';
  // A side folds with its own ‹ or ›: the head offers it back once folded, on that side.
  const unfold = (side) => (ui.dock[side].open || !ui.dock[side].groups.length || (side === 'right' && (site || agent)) ? ''
    : `<button type="button" class="panel-toggle dock-unfold" data-action="dock-open" data-side="${side}" aria-expanded="false" title="${side === 'left' ? '왼쪽' : '오른쪽'} 패널 펴기">${side === 'left' ? '' : '<span aria-hidden="true">‹</span> '}<span class="dock-unfold-label">${escape(sideTitle(ui.dock, side))}</span>${side === 'left' ? ' <span aria-hidden="true">›</span>' : ''}</button>`);
  return `<header class="board-head">
      ${unfold('left')}<div class="board-heading"><h1 class="sr-only">제도판</h1><nav class="crumbs" aria-label="현재 위치"><a href="#/">프로젝트</a><span aria-hidden="true">/</span><button type="button" class="project-name-edit" data-action="project-info" data-project="${escape(name)}" title="프로젝트 정보 수정">${escape(currentProjectLabel(name))} ✎</button>${site ? '<span aria-hidden="true">/</span><span>대지</span>' : ''}</nav></div>
      ${selection ? `<div class="selection-bar ${picked.length ? 'has-selection' : ''}" aria-label="고른 종이">${selection}</div>` : '<span class="selection-bar" aria-hidden="true"></span>'}
      <div class="panel-toggles">
        ${unfold('right')}
        ${site ? '' : `<button type="button" class="panel-toggle" data-action="vworld-3d" aria-pressed="${Boolean(ui.vworld)}" title="브이월드 3D 지도에 매스안 세워 보기 (vworld)">브이월드 3D</button>`}
        <details class="export-menu"><summary class="panel-toggle" title="CAD·라이노 파일로 내보내기 (export)">내보내기</summary>
          <div class="export-options">${EXPORT_FORMATS.map((f) => `<button type="button" data-action="export-board" data-format="${f.key}">${f.label}</button>`).join('')}
          <p class="muted">대지 경계·매스안·트레이싱 선이 레이어별로 들어갑니다. 이 PC에 지도 묶음이 있으면 대지 주변 지형·등고선·건물도 '대지 주변' 레이어로 들어갑니다. 단위 m, 원점은 대지 가운데.</p></div></details>
        <button type="button" class="ghost settings-button" data-action="settings" aria-label="설정" title="설정">⚙${settingsWarned() ? '<span class="warn-dot" aria-label="확인할 설정 있음">●</span>' : ''}</button>
      </div>
    </header>`;
}

function panelSplitter(side) {
  const label = side === 'left' ? '왼쪽 패널 너비 조절' : '오른쪽 패널 너비 조절';
  return `<div class="studio-splitter splitter-${side}" role="separator" aria-label="${label}" aria-orientation="vertical"
    aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0" data-resize-side="${side}" data-focus="panel-${side}"
    title="드래그 또는 방향키로 너비 조절 · 두 번 누르면 기본 너비"></div>`;
}

function workspaceView() {
  const { name, agent, site } = currentRoute;
  const expert = agent ? expertById(agent) : null;
  // The drafting table fills the screen; the docked panels sit on either side (each side folds),
  // and the site page or an expert's page takes the right side's place.
  const narrow = matchMedia('(max-width: 900px)').matches;
  const layout = narrow ? narrowDock(ui.narrowSide) : ui.dock;
  const page = site ? sitePage(name) : agent ? expertPage(name, agent) : '';
  const left = narrow || sideShown(layout, 'left');
  const right = Boolean(page) || narrow || sideShown(layout, 'right');
  const options = { around: Boolean(table?.aroundOn), narrow };
  const sideLabel = site ? '대지' : expert ? expert.name : DOCK_PANELS[narrowDock(ui.narrowSide).right.groups[0].active];
  const tabs = [['conductor', '대화'], ['board', '제도판'], ['side', sideLabel]];
  return `<main class="studio with-table ${site ? 'site-open' : agent ? 'expert-open' : ''} pane-${ui.pane} ${left ? 'left-open' : ''} ${right ? 'right-open' : ''}" id="main" tabindex="-1">
      ${dockView(layout, 'left', options)}
      ${left && !narrow ? panelSplitter('left') : ''}
      <section class="board panel" aria-label="제도판">${boardHead(name, site, agent)}<div class="board-canvas"><div id="table-slot"></div>${ideaFloatView()}</div></section>
      ${page || dockView(layout, 'right', options)}
      ${right && !narrow ? panelSplitter('right') : ''}
      ${narrow ? '' : floatView(layout, options)}
      ${commandBar()}
      <nav class="pane-tabs" aria-label="화면 바꾸기">${tabs.map(([id, label]) => `<button type="button" data-action="pane" data-pane="${id}" aria-pressed="${ui.pane === id}">${escape(label)}</button>`).join('')}</nav>
    </main>`;
}

// The new-project form floats over the list while the route is #/new. It is filled once when it
// opens (so redraws of the list underneath do not disturb typing) and closed when the route leaves.
function syncNewProject(open) {
  if (!open) { if (newProjectDialog.open) newProjectDialog.close(); return; }
  if (newProjectDialog.open) {
    newProjectDialog.querySelector('[type="submit"]').disabled = ui.creating;
    return;
  }
  newProjectDialog.innerHTML = newView();
  newProjectDialog.showModal();
  newProjectDialog.querySelector('#project-name').focus({ preventScroll: true });
}

export function render(fresh = true) {
  if (panelResizing() || ideaDragging() || dockDragging() || dockSplitting() || floatMoving() || deferred.growing) { deferred.render = true; return; } // Keep the captured handle until release.
  // Keep typing and reading positions across redraws.
  const focused = document.activeElement?.dataset?.focus;
  const selection = focused ? [document.activeElement.selectionStart, document.activeElement.selectionEnd] : null;
  const scrolls = new Map();
  for (const el of app.querySelectorAll('[data-scroll]')) {
    if (!el.getClientRects().length) continue;
    const position = { top: el.scrollTop, bottom: el.scrollHeight - el.scrollTop - el.clientHeight < 40 };
    scrolls.set(el.dataset.scroll, position);
    if (el.closest('.conductor-panel')) conductorScrolls.set(el.dataset.scroll, position);
  }
  const page = currentRoute.page;
  app.innerHTML = page === 'home' || page === 'new' ? homeView() : workspaceView();
  syncNewProject(page === 'new');
  syncPanelWidths();
  document.title = `Sida · ${page === 'project' ? currentProjectLabel(currentRoute.name) : page === 'new' ? '새 프로젝트' : '프로젝트'}`;
  for (const el of app.querySelectorAll('[data-scroll]')) {
    if (!el.getClientRects().length) continue;
    // Chats follow their newest message; pages (data-scroll-from="top") open at the top.
    const fromTop = el.dataset.scrollFrom === 'top';
    const saved = fresh && !el.closest('.conductor-panel') ? null : scrolls.get(el.dataset.scroll) || conductorScrolls.get(el.dataset.scroll);
    if (!saved) el.scrollTop = fromTop ? 0 : el.scrollHeight;
    else el.scrollTop = saved.bottom && !fromTop ? el.scrollHeight : saved.top;
  }
  slotWatch.disconnect();
  const slot = app.querySelector('#table-slot');
  if (slot) slotWatch.observe(slot);
  placeTable();
  placeIdeaFloat();
  placeSiteMap();
  placeModelMaker();
  const ask = ui.focusComposer && app.querySelector('[data-focus="command"]');
  ui.focusComposer = false;
  const again = focused && app.querySelector(`[data-focus="${CSS.escape(focused)}"]`);
  if (ask) {
    ask.focus({ preventScroll: true });
    ask.setSelectionRange(ask.value.length, ask.value.length);
  } else if (again) {
    again.focus({ preventScroll: true });
    // Only text fields keep a cursor (a select or a checkbox has none to restore).
    if (selection && again.selectionStart != null && typeof again.setSelectionRange === 'function') again.setSelectionRange(...selection);
  } else if (fresh) {
    document.querySelector('#main')?.focus({ preventScroll: true });
  }
}
