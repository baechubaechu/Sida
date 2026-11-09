// The panels docked beside the drafting table (dock-model.js): on each side, groups stacked top
// to bottom, each with a row of tabs and the body of the one it shows. Tabs are dragged to another
// group, above or below one, or to an empty side (dock.js); the line between two groups sets
// their heights. The panels: 대화 (Conductor), 속성 (what is selected), 레이어 (what the table
// shows) and 전문가 (the experts), as in Rhino or CAD. On a narrow screen (≤900px) the tabs at the
// bottom show one side at a time and the layout is fixed: 대화 alone, the rest in one group.

import { boardLayers, groupProperties, layerRows, pickedBlocks, propertiesOf, selectedGroup } from './board-model.js';
import { DOCK_PANELS, sideShown } from './dock-model.js';
import { escapeHtml as escape, siteCard } from './model.js';
import { icon } from './icons.js';
import { drafts, ui } from './state.js';
import { table } from './board.js';
import { conductorBody } from './view-conductor.js';
import { expertsBody } from './view-experts.js';

function propsBody() {
  const all = ui.board?.papers || [];
  const papers = all.filter((p) => ui.selected.includes(p.id));
  // A whole group shows as one (its parts and a button to take it apart).
  const group = selectedGroup(all, ui.selected, ui.picked);
  const props = group ? groupProperties(all, group) : propertiesOf(papers, siteCard(ui.site), papers.length ? [] : pickedBlocks(all, ui.picked), boardLayers(ui.board));
  const inner = props
    ? `<h3 class="side-title">${escape(props.title)}</h3>
      <dl class="props">${props.rows.map(([label, value, field]) => `<dt>${field ? `<label for="prop-${field.key}">${escape(label)}</label>` : escape(label)}</dt><dd>${field ? propField(field, value) : escape(value)}</dd>`).join('')}</dl>
      ${props.note ? `<p class="side-note">${escape(props.note)}</p>` : ''}
      ${group ? '<button type="button" class="secondary small prop-ungroup" data-action="ungroup">그룹 풀기</button>' : ''}
      ${!group && papers.length === 1 ? table?.detailHtml?.(papers[0].id) || '' : ''}`
    : '<p class="side-empty">제도판에서 종이나 매스안을 고르면 여기에 속성이 나옵니다.</p>';
  return `<div class="dock-body" role="tabpanel" aria-label="속성"><div class="experts-scroll side-body">${inner}</div></div>`;
}

// A value to change: Enter or leaving the field saves it, Esc puts it back (app.js). What is being
// typed is kept in `drafts` (prop:key) so a redraw meanwhile does not wipe it.
function propField(field, value) {
  const error = ui.propError?.key === field.key ? ui.propError.text : '';
  if (field.type === 'layer') {
    // The layers as a tree; '' when the selection is on several.
    const rows = layerRows(ui.board);
    return `<span class="prop-field"><select id="prop-layer" class="prop-input" data-prop="layer" data-focus="prop-layer">
        ${value === '' ? '<option value="" selected disabled>여러 레이어</option>' : ''}
        ${rows.map((r) => `<option value="${escape(r.id)}" ${r.id === value ? 'selected' : ''}>${'\u2003'.repeat(r.depth)}${escape(r.name)}</option>`).join('')}</select></span>
      ${error ? `<span class="prop-error" role="alert">${escape(error)}</span>` : ''}`;
  }
  const number = field.type === 'number';
  const shown = drafts.get(`prop:${field.key}`) ?? value;
  return `<span class="prop-field ${error ? 'has-error' : ''}"><input id="prop-${field.key}" class="prop-input" data-prop="${field.key}" data-focus="prop-${field.key}"
      type="${number ? 'number' : 'text'}" value="${escape(shown)}" data-saved="${escape(value)}" ${number ? `min="${field.min}" max="${field.max}" step="${field.step}" inputmode="decimal"` : `maxlength="${field.max}"`}
      ${value === '' && number ? 'placeholder="여러 값"' : ''} ${error ? 'aria-invalid="true" aria-describedby="prop-error"' : ''}>${field.unit ? `<span class="prop-unit">${escape(field.unit)}</span>` : ''}</span>
    ${error ? `<span class="prop-error" id="prop-error" role="alert">${escape(error)}</span>` : ''}`;
}

// The 레이어 panel, as Rhino's: a row of tools (new layer, sublayer, delete, up, down) over a tree
// of layers with the current mark, visibility, lock and colour (layers.js does the buttons).
// Double-clicking a name renames it.
function layersBody(around) {
  const rows = layerRows(ui.board, { around, aroundHidden: ui.aroundHidden, current: ui.currentLayer,
    aroundParts: table?.aroundParts?.() || [], aroundPartsHidden: table?.aroundPartsHidden || new Set() });
  const pick = rows.find((r) => r.id === ui.layerPick && !r.system);
  const tool = (action, name, label, off = false) => `<button type="button" class="layer-tool" data-action="${action}" aria-label="${label}" title="${label}" ${off ? 'disabled' : ''}>${icon(name)}</button>`;
  const mark = (r, action, on, onIcon, offIcon, label) => `<button type="button" class="layer-mark ${on ? '' : 'is-off'}" data-action="${action}" data-layer="${escape(r.id)}" aria-pressed="${on}" aria-label="${escape(r.name)} ${label}" title="${label}">${icon(on ? onIcon : offIcon)}</button>`;
  return `<div class="dock-body" role="tabpanel" aria-label="레이어">
    <div class="layer-tools" role="toolbar" aria-label="레이어 도구">
      ${tool('layer-add', 'layerNew', '새 레이어')}${tool('layer-add-sub', 'layerSub', pick ? `${pick.name} 아래에 하위 레이어` : '하위 레이어 (먼저 레이어를 고르세요)', !pick)}
      ${tool('layer-remove', 'trash', pick ? `${pick.name} 지우기 (안의 것은 위 레이어로)` : '레이어 지우기 (먼저 레이어를 고르세요)', !pick || rows.filter((r) => !r.system).length < 2)}
      <span class="layer-tools-gap"></span>${tool('layer-up', 'up', '위로', !pick)}${tool('layer-down', 'down', '아래로', !pick)}</div>
    <div class="layer-table" role="grid" aria-label="레이어">
      <div class="layer-row layer-header" role="row"><span role="columnheader">레이어</span><span role="columnheader" title="새로 만드는 것이 들어갈 레이어">현재</span><span role="columnheader">보기</span><span role="columnheader">잠금</span><span role="columnheader">색</span></div>
      ${rows.map((r) => `<div class="layer-row ${r.id === ui.layerPick ? 'is-picked' : ''} ${!r.visible || r.parentHidden ? 'is-off' : ''}" role="row" data-layer-row="${escape(r.id)}" aria-selected="${r.id === ui.layerPick}">
        <span class="layer-name" role="gridcell" style="--depth: ${r.depth}">${ui.layerRename === r.id
          ? `<input class="layer-rename" data-layer-rename="${escape(r.id)}" data-focus="layer-rename" value="${escape(ui.layerRenameText || r.name)}" maxlength="60" aria-label="레이어 이름">`
          : `<button type="button" class="layer-label" data-action="layer-pick" data-layer="${escape(r.id)}" title="${r.system ? '' : '두 번 누르면 이름 바꾸기'}">${escape(r.name)}</button>`}${r.count ? `<span class="layer-count">${r.count}</span>` : ''}</span>
        <span role="gridcell">${r.system ? '' : `<button type="button" class="layer-mark layer-current ${r.current ? '' : 'is-off'}" data-action="layer-current" data-layer="${escape(r.id)}" aria-pressed="${r.current}" aria-label="${escape(r.name)} 현재 레이어로" title="${r.current ? '현재 레이어 (다시 누르면 종류별 레이어로)' : '현재 레이어로: 새로 만드는 것이 여기에 들어갑니다'}">${icon('check')}</button>`}</span>
        <span role="gridcell">${mark(r, 'layer-eye', r.visible, 'eye', 'eyeOff', r.visible ? '숨기기' : '보이기')}</span>
        <span role="gridcell">${r.system ? '' : mark(r, 'layer-lock', !r.locked, 'unlock', 'lock', r.locked ? '잠금 풀기' : '잠그기')}</span>
        <span role="gridcell">${r.system ? '' : `<label class="layer-swatch ${r.color ? '' : 'is-empty'}" style="--swatch: ${escape(r.color || 'transparent')}" title="색 (매스가 이 색으로)"><input type="color" data-layer-color="${escape(r.id)}" value="${escape(r.color || '#9aa7b2')}" aria-label="${escape(r.name)} 색"></label>`}</span>
      </div>`).join('')}
      <p class="side-note layer-note">숨기거나 잠근 레이어는 제도판에서만 가려지거나 고를 수 없습니다. 내보내기와 전문가 검토에는 그대로 들어갑니다. 고른 것을 다른 레이어로 옮기려면 속성의 "레이어" 값을 바꾸세요.</p>
    </div></div>`;
}

function panelBody(id, around) {
  if (id === 'conductor') return conductorBody();
  if (id === 'props') return propsBody();
  if (id === 'layers') return layersBody(around);
  return expertsBody();
}

const SIDE_NAMES = { left: '왼쪽', right: '오른쪽' };

// The tab names of a side, for its label and the button that unfolds it.
export function sideTitle(layout, side) {
  return layout[side].groups.flatMap((g) => g.tabs).map((id) => DOCK_PANELS[id]).join(' · ');
}

function tabRow(g, narrow) {
  return `<div class="dock-tabs" role="tablist" aria-label="${escape(g.tabs.map((id) => DOCK_PANELS[id]).join(', '))}">${g.tabs.map((id) => `<button type="button" role="tab" class="dock-tab" data-action="dock-tab" data-panel="${id}" data-focus="dock-tab-${id}" aria-selected="${g.active === id}" ${narrow ? '' : 'title="끌어서 다른 묶음·반대쪽·위아래에 붙이거나 제도판 위에 띄우기"'}>${DOCK_PANELS[id]}</button>`).join('')}</div>`;
}

// One side of the layout. `around`: the surroundings have been shown on the table (they then get a
// layer). `narrow`: tabs are not dragged and the side does not fold (the bottom tabs switch).
export function dockView(layout, side, { around = false, narrow = false } = {}) {
  if (!narrow && !sideShown(layout, side)) return '';
  const groups = layout[side].groups;
  const fold = side === 'left' ? '‹' : '›';
  return `<div class="dock dock-${side}" data-dock="${side}" aria-label="${SIDE_NAMES[side]} 패널: ${escape(sideTitle(layout, side))}">
    ${groups.map((g, i) => `<section class="panel dock-group" data-group="${side}:${i}" style="flex-grow: ${g.size}">
      <header class="dock-head">${tabRow(g, narrow)}
        ${i === 0 && !narrow ? `<button type="button" class="ghost dock-fold" data-action="dock-fold" data-side="${side}" aria-label="${SIDE_NAMES[side]} 패널 접기" title="${SIDE_NAMES[side]} 패널 접기">${fold}</button>` : ''}</header>
      ${panelBody(g.active, around)}</section>
    ${i < groups.length - 1 && !narrow ? `<div class="dock-split" role="separator" aria-orientation="horizontal" tabindex="0" data-dock-split="${side}:${i}" data-focus="dock-split-${side}-${i}" aria-label="두 묶음 높이 조절" title="드래그 또는 ↑↓로 높이 조절 · 두 번 누르면 반반"></div>` : ''}`).join('')}
  </div>`;
}

// The floating windows over the drafting table: moved by the empty part of the head, sized by the
// corner, put back on the right with ⇥ (or by dragging a tab onto a side). They stay inside the
// workspace when the window gets smaller.
export function floatView(layout, { around = false } = {}) {
  return (layout.float || []).map((g, i) => `<section class="panel dock-group dock-float" data-group="float:${i}" data-float="${i}" role="dialog" aria-label="떠 있는 패널: ${escape(g.tabs.map((id) => DOCK_PANELS[id]).join(', '))}"
      style="left: max(0px, min(${g.x}px, calc(100% - ${g.w}px))); top: max(0px, min(${g.y}px, calc(100% - ${g.h}px))); width: min(${g.w}px, 100%); height: min(${g.h}px, 100%)">
      <header class="dock-head" title="끌어서 옮기기">${tabRow(g, false)}
        <button type="button" class="ghost dock-float-back" data-action="dock-float-back" data-index="${i}" aria-label="오른쪽에 다시 붙이기" title="오른쪽에 다시 붙이기">⇥</button></header>
      ${panelBody(g.active, around)}
      <div class="dock-float-resize" data-float-resize="${i}" aria-hidden="true" title="끌어서 크기 조절"></div></section>`).join('');
}

// A narrow screen's fixed layout: 대화 on its own, the other panels in one group showing `active`.
export function narrowDock(active) {
  const others = Object.keys(DOCK_PANELS).filter((id) => id !== 'conductor');
  return {
    left: { open: true, groups: [{ tabs: ['conductor'], active: 'conductor', size: 1 }] },
    right: { open: true, groups: [{ tabs: others, active: others.includes(active) ? active : 'layers', size: 1 }] },
    float: [],
  };
}
