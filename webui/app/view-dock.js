// The panels docked beside the drafting table (dock-model.js): on each side, groups stacked top
// to bottom, each with a row of tabs and the body of the one it shows. Tabs are dragged to another
// group, above or below one, or to an empty side (dock.js); the line between two groups sets
// their heights. The panels: 대화 (Conductor), 속성 (what is selected), 레이어 (what the table
// shows) and 전문가 (the experts), as in Rhino or CAD. On a narrow screen (≤900px) the tabs at the
// bottom show one side at a time and the layout is fixed: 대화 alone, the rest in one group.

import { layerList, pickedBlocks, propertiesOf } from './board-model.js';
import { DOCK_PANELS, sideShown } from './dock-model.js';
import { escapeHtml as escape, siteCard } from './model.js';
import { icon } from './icons.js';
import { drafts, ui } from './state.js';
import { conductorBody } from './view-conductor.js';
import { expertsBody } from './view-experts.js';

function propsBody() {
  const all = ui.board?.papers || [];
  const papers = all.filter((p) => ui.selected.includes(p.id));
  const props = propertiesOf(papers, siteCard(ui.site), papers.length ? [] : pickedBlocks(all, ui.picked));
  const inner = props
    ? `<h3 class="side-title">${escape(props.title)}</h3>
      <dl class="props">${props.rows.map(([label, value, field]) => `<dt>${field ? `<label for="prop-${field.key}">${escape(label)}</label>` : escape(label)}</dt><dd>${field ? propField(field, value) : escape(value)}</dd>`).join('')}</dl>
      ${props.note ? `<p class="side-note">${escape(props.note)}</p>` : ''}`
    : '<p class="side-empty">제도판에서 종이나 매스안을 고르면 여기에 속성이 나옵니다.</p>';
  return `<div class="dock-body" role="tabpanel" aria-label="속성"><div class="experts-scroll side-body">${inner}</div></div>`;
}

// A value to change: Enter or leaving the field saves it, Esc puts it back (app.js). What is being
// typed is kept in `drafts` (prop:key) so a redraw meanwhile does not wipe it.
function propField(field, value) {
  const error = ui.propError?.key === field.key ? ui.propError.text : '';
  const number = field.type === 'number';
  const shown = drafts.get(`prop:${field.key}`) ?? value;
  return `<span class="prop-field ${error ? 'has-error' : ''}"><input id="prop-${field.key}" class="prop-input" data-prop="${field.key}" data-focus="prop-${field.key}"
      type="${number ? 'number' : 'text'}" value="${escape(shown)}" data-saved="${escape(value)}" ${number ? `min="${field.min}" max="${field.max}" step="${field.step}" inputmode="decimal"` : `maxlength="${field.max}"`}
      ${value === '' && number ? 'placeholder="여러 값"' : ''} ${error ? 'aria-invalid="true" aria-describedby="prop-error"' : ''}>${field.unit ? `<span class="prop-unit">${escape(field.unit)}</span>` : ''}</span>
    ${error ? `<span class="prop-error" id="prop-error" role="alert">${escape(error)}</span>` : ''}`;
}

function layersBody(around) {
  const rows = layerList(ui.board, ui.hiddenLayers, { around });
  return `<div class="dock-body" role="tabpanel" aria-label="레이어"><div class="experts-scroll side-body"><ul class="layers">${rows.map((r) => `<li class="layer ${r.visible ? '' : 'is-off'}">
      <button type="button" class="layer-eye" data-action="layer-toggle" data-layer="${escape(r.key)}" aria-pressed="${r.visible}" aria-label="${escape(r.label)} ${r.visible ? '숨기기' : '보이기'}" title="${r.visible ? '숨기기' : '보이기'}">${icon(r.visible ? 'eye' : 'eyeOff')}</button>
      <span class="layer-name">${escape(r.label)}</span>${r.count ? `<span class="layer-count">${r.count}${escape(r.unit)}</span>` : ''}</li>`).join('')}</ul>
    <p class="side-note">숨긴 레이어는 제도판에서만 가려집니다. 내보내기와 전문가 검토에는 그대로 들어갑니다.</p></div></div>`;
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
