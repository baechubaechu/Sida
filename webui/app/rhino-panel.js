// The Sida panel inside Rhino (rhino.html). The plugin shows this page in a web view; the page
// never talks to Rhino. It reads the running document from Sida once a second (/api/rhino/live)
// and asks the plugin for things through Sida (/api/rhino/commands); what it shows and how is
// decided in rhino-model.js. Opened in a browser without ?doc= it follows the document whose
// plugin asked last.

import { api } from './api.js';
import { panelStatus, panelFigures, panelBusy, diagramChoices, layerRows, readFloorHeight, meaningChoices, askContext, askReady, readPanelHash, panelHash } from './rhino-model.js';
import { chat, chatFor, chatHtml, newTalk, send } from './rhino-chat.js';

const POLL_MS = 1000;
const BUSY_MS = 20000;  // a button pressed counts as "in progress" this long, unless the plugin says more (rhino-model.js panelBusy)
const BUSY_WORDS = { pull: '가져오는 중…', push: '보내는 중…', draw: '그리는 중…' };
const named = new URLSearchParams(location.search).get('doc') || '';
const el = (id) => document.getElementById(id);
const escape = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

const kept = readPanelHash(location.hash);  // the tab and talk open before a reload
const ui = {
  tab: kept.tab,
  live: { connected: false, rev: 0, state: null },
  meanings: [], diagrams: [], projects: [],
  serverDown: false,
  allLayers: false,
  asked: null,  // the button just pressed: {what, notice (the notice count then), until}
  skipped: [],  // the diagrams the designer left out of "라이노에 그리기"
  error: '',
  drawn: {},
};

// ------------------------------------------------------------------ drawing

// A part is written again only when what it shows changed, and never under the designer's
// fingers: a part that holds the focused field waits.
function draw(id, html) {
  const node = el(id);
  if (ui.drawn[id] === html) return;
  const active = document.activeElement;
  if (active && node.contains(active) && (active.tagName === 'INPUT' || active.tagName === 'SELECT')) return;
  ui.drawn[id] = html;
  node.innerHTML = html;
}

function drawHead(state, status) {
  const file = state ? (state.file || '저장하지 않은 문서') : 'Sida';
  const dot = ui.serverDown ? ['off', 'Sida 꺼짐'] : !state ? ['wait', '라이노 기다리는 중'] : ui.live.connected ? ['on', '라이노 연결됨'] : ['off', '라이노 연결 끊김'];
  const options = [`<option value="">프로젝트 고르기</option>`,
    ...ui.projects.map((p) => `<option value="${escape(p.name)}" ${state?.project === p.name ? 'selected' : ''}>${escape(p.display_name && p.display_name !== p.name ? `${p.display_name} (${p.name})` : p.name)}</option>`)].join('');
  draw('rp-head', `
    <div class="rp-title"><h1>${escape(file)}</h1><span class="rp-dot is-${dot[0]}">${escape(dot[1])}</span></div>
    ${state ? `<label class="rp-project ${status.code === 'no-project' || status.code === 'bad-project' ? 'needs' : ''}">Sida 프로젝트
      <select id="rp-project" ${ui.live.connected ? '' : 'disabled'}>${options}</select></label>` : ''}`);
  draw('rp-tabs', state ? [['model', '모델'], ['chat', 'Sida에게 묻기']].map(([tab, word]) =>
    `<button type="button" role="tab" id="rp-tab-${tab}" data-tab="${tab}" aria-selected="${ui.tab === tab}" tabindex="${ui.tab === tab ? 0 : -1}">${word}</button>`).join('') : '');
}

// The talk with Sida about this model (rhino-chat.js). The question field is not drawn again
// (it is in rhino.html): only its hint, and whether it can be sent, change.
function drawChat(state, status) {
  const tabbed = Boolean(state) && ui.tab === 'chat';
  el('rp-ask').hidden = !tabbed;
  if (!tabbed) { draw('rp-chat', ''); return; }
  const project = status.code === 'ready' || status.code === 'lost' ? state.project : '';  // a lost Rhino's talk stays readable
  chatFor(project, kept.project === project ? kept.talk : '');
  if (project) kept.talk = '';  // taken once
  const ready = askReady(ui.live, status, chat.busy);
  const rows = el('rp-chat').childElementCount;
  draw('rp-chat', chatHtml(ready.ok));
  if (el('rp-chat').childElementCount !== rows) window.scrollTo(0, document.body.scrollHeight);  // the newest line in view
  el('rp-with').textContent = ready.ok || chat.busy ? askContext(state) : ready.why;
  if (chat.unsent) {  // the answer failed and the question was not kept: back into the field, unless a new one is being written
    if (!el('rp-question').value) el('rp-question').value = chat.unsent;
    chat.unsent = '';
  }
  el('rp-question').disabled = !project;
  el('rp-send').disabled = !ready.ok;
  el('rp-new-talk').hidden = !chat.talk;
  el('rp-new-talk').disabled = chat.busy;
  const address = panelHash({ tab: ui.tab, project: chat.project, talk: chat.talk });
  if (address !== location.hash) history.replaceState(null, '', address || location.pathname + location.search);
}

function gaugeHtml(g) {
  const scale = 1.25;  // the track runs to 125% of the limit, so the mark sits at 80%
  const within = Math.min(g.fill, 1) / scale * 100;
  const beyond = Math.max(g.fill - 1, 0) / scale * 100;
  const said = `${g.label} ${g.text}${g.limitText ? `, ${g.limitText}` : ''}${g.over ? ', 한도를 넘음' : ''}`;
  return `<div class="gauge ${g.over ? 'is-over' : ''} ${g.value == null ? 'is-unknown' : ''}">
    <div class="gauge-head"><span>${escape(g.label)}</span><b>${escape(g.text)}</b></div>
    ${g.limit == null ? '' : `<div class="gauge-track" role="img" aria-label="${escape(said)}">
      <i class="gauge-fill" style="width:${within.toFixed(2)}%"></i>
      ${beyond > 0 ? `<i class="gauge-beyond" style="left:80%;width:${beyond.toFixed(2)}%"></i>` : ''}
      <i class="gauge-mark"></i></div>`}
    ${g.limitText ? `<p class="gauge-limit ${g.limit == null ? '' : 'at-mark'}">${escape(g.limitText)}${g.over ? ' 초과' : ''}</p>` : ''}
  </div>`;
}

function drawFigures(state, status) {
  if (!state || status.code === 'no-project' || status.code === 'bad-project') { draw('rp-figures', ''); return; }
  const view = panelFigures(state.figures);
  if (!view) { draw('rp-figures', '<p class="rp-empty">아직 수치가 없습니다.</p>'); return; }
  const shares = view.shares.length > 1 ? `<div class="shares" role="img" aria-label="용도별 연면적: ${escape(view.shares.map((s) => `${s.word} ${s.text}`).join(', '))}">
      ${view.shares.map((s, i) => `<i class="share-${i % 5}" style="flex-grow:${Math.max(s.share * 100, 2).toFixed(2)}"></i>`).join('')}</div>
    <ul class="share-list">${view.shares.map((s, i) => `<li><i class="share-${i % 5}"></i>${escape(s.word)}<b>${escape(s.text)}</b></li>`).join('')}</ul>` : '';
  draw('rp-figures', `
    ${view.empty ? '<p class="rp-empty">건물 의미를 준 레이어에 입체가 없습니다. 아래에서 레이어의 의미를 정하세요.</p>' : ''}
    <div class="gauges">${view.gauges.map(gaugeHtml).join('')}</div>
    <dl class="rp-rows">${view.rows.map((r) => `<div><dt>${escape(r.label)}</dt><dd>${escape(r.text)}</dd></div>`).join('')}</dl>
    ${shares}
    ${view.limits.length > 1 ? `<ul class="rp-limits">${view.limits.map((l) => `<li>${escape(l)}</li>`).join('')}</ul>` : ''}
    ${view.notes.length ? `<ul class="rp-notes">${view.notes.map((n) => `<li>${escape(n)}</li>`).join('')}</ul>` : ''}`);
}

function drawLayers(state) {
  if (!state) { draw('rp-layers', ''); return; }
  const { rows, quiet } = layerRows(state.layers, ui.meanings, { all: ui.allLayers });
  const choices = meaningChoices(ui.meanings);
  const select = (row) => `<select data-layer="${escape(row.path)}" aria-label="${escape(row.name)} 레이어의 의미" ${ui.live.connected ? '' : 'disabled'}>
      <option value="" ${row.meaning ? '' : 'selected'}>의미 없음</option>
      <optgroup label="건물 (수치에 들어감)">${choices.built.map((m) => `<option value="${escape(m.code)}" ${row.meaning === m.code ? 'selected' : ''}>${escape(m.word)}</option>`).join('')}</optgroup>
      <optgroup label="건물 아님 (수치에서 빠짐)">${choices.other.map((m) => `<option value="${escape(m.code)}" ${row.meaning === m.code ? 'selected' : ''}>${escape(m.word)}</option>`).join('')}</optgroup>
    </select>`;
  const needWords = { meaning: '의미를 정하면 수치에 들어갑니다', height: '층고를 적으면 연면적에 들어갑니다' };
  const body = rows.map((row) => `<li class="layer ${row.needs ? 'needs' : ''}">
      <i class="swatch" style="${row.color ? `background:${escape(row.color)}` : ''}"></i>
      <div class="layer-name"><b title="${escape(row.path)}">${escape(row.name)}</b>
        <small>${escape([row.under, `입체 ${row.objects}개`].filter(Boolean).join(', '))}</small>
        ${row.needs ? `<small class="layer-need">${escape(needWords[row.needs])}</small>` : ''}</div>
      ${select(row)}
      ${row.takesHeight ? `<input type="text" inputmode="decimal" data-height="${escape(row.path)}" value="${escape(row.floorHeight)}" placeholder="예: 3.3"
        aria-label="${escape(row.name)} 레이어의 층고 (m)" ${ui.live.connected ? '' : 'disabled'}>` : '<span class="no-height" aria-hidden="true"></span>'}
    </li>`).join('');
  draw('rp-layers', `
    <div class="rp-layers-head"><h2>레이어</h2><span>의미</span><span>층고 m</span></div>
    ${rows.length ? `<ul class="layers">${body}</ul>` : '<p class="rp-empty">입체가 있는 레이어가 없습니다. 라이노에서 매스를 만들면 여기에 레이어가 나옵니다.</p>'}
    ${quiet || ui.allLayers ? `<button type="button" class="rp-more" id="rp-more">${ui.allLayers ? '입체가 있는 레이어만 보기' : `빈 레이어 ${quiet}개도 보기`}</button>` : ''}`);
}

// The diagrams Sida draws of the model, to be put into the document as real geometry: all of
// them unless the designer leaves some out.
function drawDiagrams(state, status, busy) {
  if (!state || status.code !== 'ready' || !ui.diagrams.length) { draw('rp-diagrams', ''); return; }
  const { rows, picked } = diagramChoices(ui.diagrams, ui.skipped);
  const can = ui.live.connected && !busy;
  draw('rp-diagrams', `
    <h2>다이어그램</h2>
    <p class="rp-hint">지금 모델을 Sida로 보낸 뒤, 고른 그림을 "Sida 다이어그램" 레이어에 선과 면으로 그립니다.</p>
    <div class="rp-kinds" role="group" aria-label="그릴 다이어그램">${rows.map((r) => `<button type="button" data-kind="${escape(r.kind)}" aria-pressed="${r.on}">${escape(r.title)}</button>`).join('')}</div>
    <button type="button" class="secondary rp-draw" data-ask="draw" ${can && picked.length ? '' : 'disabled'}>${busy === 'draw' ? BUSY_WORDS.draw : picked.length ? `라이노에 그리기 (${picked.length}개)` : '그릴 그림을 고르세요'}</button>`);
}

function drawFoot(state, status, busy) {
  if (!state) { draw('rp-foot', ''); return; }
  const ready = ui.live.connected && status.code === 'ready';
  const notice = ui.error ? { text: ui.error, ok: false } : state.notice;
  draw('rp-foot', `
    ${notice ? `<p class="rp-notice ${notice.ok ? '' : 'is-bad'}" role="status">${escape(notice.text)}</p>` : ''}
    <div class="rp-actions">
      <button type="button" class="secondary" data-ask="pull" ${ready && !busy ? '' : 'disabled'}>${busy === 'pull' ? BUSY_WORDS.pull : 'Sida에서 가져오기'}</button>
      <button type="button" class="primary" data-ask="push" ${ready && !busy ? '' : 'disabled'}>${busy === 'push' ? BUSY_WORDS.push : 'Sida로 보내기'}</button>
    </div>
    <label class="rp-auto"><input type="checkbox" id="rp-auto" ${state.autosync ? 'checked' : ''} ${ready ? '' : 'disabled'}> 라이노에서 저장할 때마다 보내기</label>`);
}

function drawAll() {
  const state = ui.live.state;
  const status = ui.serverDown
    ? { code: 'down', text: 'Sida 앱에 연결할 수 없습니다. run.bat으로 Sida를 켜면 다시 이어집니다.' } : panelStatus(ui.live);
  document.body.dataset.status = status.code;
  document.body.dataset.tab = state ? ui.tab : 'model';
  drawHead(state, status);
  draw('rp-status', escape(status.text));
  el('rp-status').hidden = !status.text;
  drawFigures(state, status);
  drawLayers(state);
  const busy = panelBusy(ui.live, ui.asked, Date.now());
  drawDiagrams(state, status, busy);
  drawFoot(state, status, busy);
  drawChat(state, status);
}

// ------------------------------------------------------------------ asking the plugin

async function ask(command) {
  const state = ui.live.state;
  if (!state) return;
  ui.error = '';
  try {
    await api('/api/rhino/commands', { method: 'POST', body: { doc: state.doc, ...command } });
  } catch (error) {
    ui.error = error.message;
    ui.asked = null;
  }
  drawAll();
}

document.addEventListener('click', (event) => {
  const asked = event.target.closest('[data-ask]');
  const kind = event.target.closest('[data-kind]');
  const tab = event.target.closest('[data-tab]');
  const example = event.target.closest('[data-example]');
  if (tab) {
    ui.tab = tab.dataset.tab;
    drawAll();
    if (ui.tab === 'chat') el('rp-question').focus({ preventScroll: true });
  } else if (example) {
    el('rp-question').value = example.dataset.example;
    el('rp-question').focus();
  } else if (event.target.id === 'rp-new-talk') {
    newTalk();
    el('rp-question').focus();
  } else if (asked && !asked.disabled) {
    const what = asked.dataset.ask;
    ui.asked = { what, notice: ui.live.state?.notice?.n || 0, until: Date.now() + BUSY_MS };
    ask(what === 'draw' ? { type: 'draw', kinds: diagramChoices(ui.diagrams, ui.skipped).picked } : { type: what });
  } else if (kind) {
    const at = ui.skipped.indexOf(kind.dataset.kind);
    if (at < 0) ui.skipped.push(kind.dataset.kind); else ui.skipped.splice(at, 1);
    drawAll();
  } else if (event.target.id === 'rp-more') {
    ui.allLayers = !ui.allLayers;
    drawAll();
  }
});

document.addEventListener('change', (event) => {
  const target = event.target;
  if (target.id === 'rp-project') {
    if (target.value) ask({ type: 'set_project', project: target.value });
  } else if (target.id === 'rp-auto') {
    ask({ type: 'set_autosync', on: target.checked });
  } else if (target.dataset.layer !== undefined || target.dataset.height !== undefined) {
    const row = target.closest('.layer');
    const path = target.dataset.layer ?? target.dataset.height;
    const meaning = row.querySelector('select').value;
    const field = row.querySelector('input');
    const height = readFloorHeight(field ? field.value : '');
    if (height.error) {
      ui.error = height.error;
      drawAll();
      return;
    }
    ask({ type: 'set_layer', path, meaning, floor_height: height.value });
  }
  target.blur?.();  // so the part is written again with what Rhino now says
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && event.target.dataset?.height !== undefined) event.target.blur();
  // Enter sends the question, Shift+Enter breaks the line; not while a Hangul syllable is being composed.
  if (event.key === 'Enter' && event.target.id === 'rp-question' && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    el('rp-ask').requestSubmit();
  }
  if ((event.key === 'ArrowRight' || event.key === 'ArrowLeft') && event.target.dataset?.tab) {
    ui.tab = ui.tab === 'chat' ? 'model' : 'chat';
    drawAll();
    el(`rp-tab-${ui.tab}`)?.focus();
  }
});

el('rp-ask').addEventListener('submit', async (event) => {
  event.preventDefault();
  const field = el('rp-question');
  if (el('rp-send').disabled || !field.value.trim()) return;
  const text = field.value;
  field.value = '';
  if (!await send(text)) field.value = text;  // not sent: the question is not lost
});
chat.changed = () => drawAll();

// ------------------------------------------------------------------ reading Sida

async function readOnce() {
  try {
    if (!ui.meanings.length) {
      const hello = await api('/api/rhino/hello');
      ui.meanings = hello.meanings || [];
      ui.diagrams = hello.diagrams || [];
    }
    const live = await api(`/api/rhino/live${named ? `?doc=${encodeURIComponent(named)}` : ''}`);
    const fresh = live.rev !== ui.live.rev || live.connected !== ui.live.connected || ui.serverDown;
    ui.serverDown = false;
    ui.live = live;
    if (fresh || !ui.projects.length) ui.projects = (await api('/api/projects')).projects || [];
  } catch {
    ui.serverDown = true;
  }
  drawAll();
}

async function loop() {
  await readOnce();
  setTimeout(loop, POLL_MS);
}

// The panel just opened: have the plugin say its document again, so a page opened late is not stale.
if (named) api('/api/rhino/commands', { method: 'POST', body: { doc: named, type: 'report' } }).catch(() => {});
loop();
