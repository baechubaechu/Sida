// The right panel beside the drafting table, in tabs as in Rhino or CAD: 속성 (what is selected),
// 레이어 (what the table shows) and 전문가 (the experts). With nothing selected it opens on the
// layers; selecting a paper turns it to the properties (board.js select hook).

import { layerList, propertiesOf } from './board-model.js';
import { escapeHtml as escape, siteCard } from './model.js';
import { icon } from './icons.js';
import { ui } from './state.js';
import { expertsBody } from './view-experts.js';

export const SIDE_TABS = [['props', '속성'], ['layers', '레이어'], ['experts', '전문가']];

function propsTab() {
  const papers = (ui.board?.papers || []).filter((p) => ui.selected.includes(p.id));
  const props = propertiesOf(papers, siteCard(ui.site));
  if (!props) return '<p class="side-empty">제도판에서 종이나 매스안을 고르면 여기에 속성이 나옵니다.</p>';
  return `<h3 class="side-title">${escape(props.title)}</h3>
    <dl class="props">${props.rows.map(([label, value]) => `<dt>${escape(label)}</dt><dd>${escape(value)}</dd>`).join('')}</dl>
    ${props.note ? `<p class="side-note">${escape(props.note)}</p>` : ''}`;
}

function layersTab(around) {
  const rows = layerList(ui.board, ui.hiddenLayers, { around });
  return `<ul class="layers">${rows.map((r) => `<li class="layer ${r.visible ? '' : 'is-off'}">
      <button type="button" class="layer-eye" data-action="layer-toggle" data-layer="${escape(r.key)}" aria-pressed="${r.visible}" aria-label="${escape(r.label)} ${r.visible ? '숨기기' : '보이기'}" title="${r.visible ? '숨기기' : '보이기'}">${icon(r.visible ? 'eye' : 'eyeOff')}</button>
      <span class="layer-name">${escape(r.label)}</span>${r.count ? `<span class="layer-count">${r.count}${escape(r.unit)}</span>` : ''}</li>`).join('')}</ul>
    <p class="side-note">숨긴 레이어는 제도판에서만 가려집니다. 내보내기와 전문가 검토에는 그대로 들어갑니다.</p>`;
}

// `around`: the surroundings have been shown on the table (they then get a layer).
export function sidePanel({ around = false } = {}) {
  const tab = ui.sideTab;
  return `<aside id="experts-panel" class="experts panel side-panel" aria-label="속성 · 레이어 · 전문가">
    <header class="side-head"><div class="side-tabs" role="tablist" aria-label="오른쪽 패널">${SIDE_TABS.map(([id, label]) => `<button type="button" role="tab" data-action="side-tab" data-tab="${id}" aria-selected="${tab === id}">${label}</button>`).join('')}</div>
      <button type="button" class="ghost" data-action="collapse-experts" aria-label="오른쪽 패널 접기" aria-controls="experts-panel" aria-expanded="true">›</button></header>
    ${tab === 'experts' ? expertsBody() : `<div class="experts-scroll side-body" role="tabpanel">${tab === 'props' ? propsTab() : layersTab(around)}</div>`}</aside>`;
}
