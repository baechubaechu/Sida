// The settings panel: the AI (providers, ChatGPT sign-in, models), the Sida relay key, how the work
// goes, privacy, and run modes and keys typed in by hand.

import { PROVIDER_LABELS, MODE_LABELS, STATE_UPDATE_LABELS, escapeHtml as escape, DATA_KEYS, keyChanges, relayKeyView, settingsChanges, settingsDirty } from './model.js';
import { api } from './api.js';
import { render } from './render.js';
import { settingsBody, settingsDialog, settingsFooter, settingsForm, toast, ui } from './state.js';

// ------------------------------------------------------------------ settings

function draftFromSettings(settings) {
  return {
    mode: settings.mode,
    local_profile: settings.local_profile,
    conductor_provider: settings.conductor.provider,
    worker_provider: settings.worker.provider,
    chatgpt_model: settings.chatgpt.model,
    worker_chatgpt_model: settings.chatgpt.worker_model,
    rag_enabled: settings.rag_enabled,
    state_update: settings.state_update,
    telemetry_enabled: settings.telemetry_enabled,
    openrouter_key: '',
    keys: Object.fromEntries(DATA_KEYS.map(({ id, secret }) => [id, secret ? '' : settings.keys?.[id]?.value || ''])),
  };
}

const optionTag = (value, label, selected) => `<option value="${escape(value)}" ${value === selected ? 'selected' : ''}>${escape(label)}</option>`;

// The settings panel, in the order people need it: the AI, the government data (Sida key), how
// the work goes, privacy, then a folded "고급" part for run modes and keys typed in by hand.
function renderSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  if (!s || !d) {
    settingsBody.innerHTML = `<p class="${ui.settingsError ? 'error-text' : 'muted'}">${escape(ui.settingsError || '설정을 불러오는 중입니다.')}</p>`;
    updateFooter();
    return;
  }
  const warnings = [
    s.warnings.openrouter_key_missing && 'OpenRouter 키가 없습니다. 아래 AI 연결에 키를 넣어 주세요.',
    s.warnings.rag_key_missing && '법령 검색을 켰지만 법제처 인증값이 없습니다. Sida 키를 받거나 고급의 정부 키에 넣어 주세요.',
    s.warnings.chatgpt_signed_out && 'ChatGPT 구독을 쓰게 되어 있지만 로그인되어 있지 않습니다.',
  ].filter(Boolean);
  const roles = [d.conductor_provider, d.worker_provider];
  const chatgpt = s.chatgpt;
  const modelSelect = (id, field, label, value) => `<label for="${id}">${label}</label>
    <select id="${id}" data-field="${field}">${(ui.chatgptModels?.length ? ui.chatgptModels : [{ slug: value, display_name: value }])
      .map((m) => optionTag(m.slug, m.display_name || m.slug, value)).join('')}</select>`;
  const chatgptPart = roles.includes('chatgpt') || chatgpt.signed_in
    ? `<div class="settings-sub" id="settings-chatgpt">
        <p class="settings-sub-title">ChatGPT 구독</p>
        <p>${chatgpt.signed_in ? `로그인됨: ${escape(chatgpt.email || 'ChatGPT')}` : '로그인되어 있지 않습니다.'}</p>
        ${chatgpt.signed_in && !chatgpt.plan_usage ? '<p class="error-text">구독 사용을 허용하지 않아 Sida가 쓸 수 없습니다. 다시 로그인해 주세요.</p>' : ''}
        <div class="settings-buttons">
          <button type="button" class="secondary small" data-settings="chatgpt-login">${chatgpt.signed_in ? '다시 로그인' : 'ChatGPT로 로그인'}</button>
          ${chatgpt.signed_in ? '<button type="button" class="secondary small" data-settings="chatgpt-logout">로그아웃</button>' : ''}
        </div>
        ${ui.chatgptNote ? `<p class="muted">${escape(ui.chatgptNote)}</p>` : ''}
        ${chatgpt.signed_in && d.conductor_provider === 'chatgpt' ? modelSelect('set-chatgpt-model', 'chatgpt_model', 'Conductor 모델', d.chatgpt_model) : ''}
        ${chatgpt.signed_in && d.worker_provider === 'chatgpt' ? modelSelect('set-worker-chatgpt-model', 'worker_chatgpt_model', '전문가 모델', d.worker_chatgpt_model)
          + '<p class="settings-hint">전문가 문서는 길어서 구독 사용량을 Conductor보다 많이 씁니다.</p>' : ''}
      </div>`
    : '';
  const keyStatus = s.keys?.openrouter;
  const openrouterKey = `<label for="set-openrouter">OpenRouter 키</label>
    <input id="set-openrouter" data-field="openrouter_key" type="password" autocomplete="off" placeholder="${escape(keyStatus?.set ? `저장됨 ${keyStatus.hint || ''}` : '키를 넣으면 저장할 때 확인합니다')}" value="${escape(d.openrouter_key)}">`;
  const usesOpenrouter = roles.includes('openrouter');
  const modes = d.mode === 'custom' ? [...s.options.modes, 'custom'] : s.options.modes;
  const dataKeys = DATA_KEYS.map(({ id, label, secret }) => {
    const status = s.keys?.[id];
    const hint = secret ? (status?.set ? `저장됨 ${status.hint || ''}` : '넣지 않음') : (id === 'relay_url' ? `비우면 ${s.relay?.default_url || '팀 서버'}` : '예: localhost');
    return `<label for="set-key-${id}">${escape(label)}</label>
      <input id="set-key-${id}" data-key="${id}" type="${secret ? 'password' : 'text'}" autocomplete="off" placeholder="${escape(hint)}" value="${escape(d.keys[id])}">`;
  }).join('');
  const providerSelect = (id, field, options, value) => `<select id="${id}" data-field="${field}">${options.map((p) => optionTag(p, PROVIDER_LABELS[p] || p, value)).join('')}</select>`;
  settingsBody.innerHTML = `
    ${s.first_run ? '<p class="settings-intro">처음 실행입니다. AI 연결을 확인하고 저장해 주세요.</p>' : ''}
    ${warnings.map((w) => `<p class="event-note warn">${escape(w)}</p>`).join('')}
    <section class="settings-section" aria-labelledby="settings-ai-title">
      <h3 id="settings-ai-title">AI 연결</h3>
      <p class="settings-note">지금 쓰는 모델: Conductor ${escape(s.conductor.model)}, 전문가 ${escape(s.worker.model)}</p>
      <label for="set-conductor">Conductor가 쓰는 AI</label>
      ${providerSelect('set-conductor', 'conductor_provider', s.options.conductor_providers, d.conductor_provider)}
      <label for="set-worker">전문가가 쓰는 AI</label>
      ${providerSelect('set-worker', 'worker_provider', s.options.worker_providers || s.options.providers, d.worker_provider)}
      ${chatgptPart}
      ${usesOpenrouter ? openrouterKey : ''}
    </section>
    <section class="settings-section" id="settings-relay" aria-labelledby="settings-relay-title">
      <h3 id="settings-relay-title">정부 자료</h3>
      <p class="settings-note">대지 조회와 법령 검색에 씁니다. 정부 키가 없어도 Sida 키가 있으면 됩니다.</p>
      ${relayKeyPart(s)}
    </section>
    <section class="settings-section" aria-labelledby="settings-work-title">
      <h3 id="settings-work-title">작업 방식</h3>
      <label for="set-state">전문가 결과를 설계 상태에 반영</label>
      <select id="set-state" data-field="state_update">${s.options.state_update.map((m) => optionTag(m, STATE_UPDATE_LABELS[m] || m, d.state_update)).join('')}</select>
      <label class="check"><input type="checkbox" data-field="rag_enabled" ${d.rag_enabled ? 'checked' : ''}> 법령 검색(법제처) 쓰기</label>
    </section>
    <section class="settings-section" aria-labelledby="settings-privacy-title">
      <h3 id="settings-privacy-title">개인정보</h3>
      <label class="check"><input type="checkbox" data-field="telemetry_enabled" ${d.telemetry_enabled ? 'checked' : ''}> 사용 기록 보내기</label>
      <p class="settings-hint">쓴 기능, 걸린 시간, 오류 종류만 팀에 보냅니다. 브리프·문서 원문은 보내지 않습니다.</p>
    </section>
    <details class="settings-section settings-advanced" ${ui.settingsAdvancedOpen ? 'open' : ''}>
      <summary><h3>고급</h3><span class="settings-note">실행 모드, API 키, 정부 키 직접 넣기</span></summary>
      <label for="set-mode">실행 모드</label>
      <select id="set-mode" data-field="mode">${modes.map((m) => optionTag(m, MODE_LABELS[m] || m, d.mode)).join('')}</select>
      <p class="settings-hint">Conductor와 전문가에 같은 AI를 한 번에 고릅니다. ChatGPT 구독은 위 AI 연결에서 역할마다 고릅니다.</p>
      ${d.mode === 'local' && s.options.local_profiles.length ? `<label for="set-profile">이 PC의 모델 묶음</label>
        <select id="set-profile" data-field="local_profile">${s.options.local_profiles.map((p) => optionTag(p, p, d.local_profile)).join('')}</select>` : ''}
      ${usesOpenrouter ? '' : openrouterKey}
      <p class="settings-sub-title">정부 키 직접 넣기</p>
      <p class="settings-hint">대지 조회(브이월드·공공데이터포털)와 법령 검색(법제처)에 씁니다. 이 PC에 키가 없는 서비스는 Sida 키로 Sida 자료 서버를 거쳐 부릅니다. 넣은 값은 이 PC의 .env에만 저장됩니다.</p>
      ${dataKeys}
    </details>`;
  updateFooter();
}

// The footer under the scrolling body: "저장 안 한 변경 있음" while the form differs from what is
// saved, the last error, and the save button (always in reach).
function updateFooter() {
  const dirty = settingsDirty(ui.settings, ui.settingsDraft);
  settingsFooter.querySelector('#settings-dirty').textContent = dirty ? '저장 안 한 변경 있음' : '';
  settingsFooter.querySelector('#settings-error').textContent = ui.settingsError || '';
}

// "Sida 키 받기": ask the team's relay for a key, then wait for the team to approve it.
function relayKeyPart(s) {
  const view = relayKeyView(ui.relayKey, Boolean(s.keys?.relay_token?.set));
  const form = view.form || (view.offer && ui.relayKeyOpen);
  const d = ui.relayKeyDraft;
  const busy = ui.relayKeyBusy ? 'disabled' : '';
  return `${view.note ? `<p class="${view.tone === 'muted' ? 'settings-hint' : `event-note ${view.tone}`}">${escape(view.note)}</p>` : ''}
    ${view.offer && !ui.relayKeyOpen ? `<p class="settings-ok">Sida 키가 저장되어 있습니다.</p>
      <div class="settings-buttons"><button type="button" class="secondary small" data-settings="relay-offer">키 새로 요청</button></div>` : ''}
    ${form ? `<label for="set-relay-name">이름 (소속)</label>
      <input id="set-relay-name" data-relay="name" maxlength="80" autocomplete="name" placeholder="예: 홍길동 (OO대 건축학과)" value="${escape(d.name)}">
      <label for="set-relay-contact">연락처 (이메일이나 카톡 아이디, 선택)</label>
      <input id="set-relay-contact" data-relay="contact" maxlength="120" autocomplete="email" value="${escape(d.contact)}">
      <p class="settings-hint">이름과 연락처는 키를 승인하는 팀만 봅니다.</p>
      <div class="settings-buttons"><button type="button" class="secondary small" data-settings="relay-ask" ${busy}>키 요청</button></div>` : ''}
    ${view.waiting ? `<div class="settings-buttons">
      <button type="button" class="secondary small" data-settings="relay-check" ${busy}>승인됐는지 확인</button>
      <button type="button" class="secondary small" data-settings="relay-cancel" ${busy}>요청 취소</button></div>` : ''}`;
}

// Ask the relay whether the waiting request was answered; a key that arrived is saved by the
// server, so the settings are read again to show it.
export async function checkRelayKey({ quiet = false } = {}) {
  try {
    const answer = await api('/api/settings/relay-key');
    if (answer.state === 'none' && quiet) return false;
    ui.relayKey = answer;
    if (answer.state === 'approved') {
      toast('Sida 키를 받았습니다. 이제 정부 키 없이 대지 조회와 법령 검색을 쓸 수 있습니다.', 'success');
      return true;
    }
    if (answer.state === 'refused' && quiet) toast('Sida 키 요청이 거절됐습니다. 설정에서 확인해 주세요.', 'error');
  } catch (error) {
    if (!quiet) ui.settingsError = error.message;
  }
  return false;
}

async function relayKeyAction(action) {
  ui.relayKeyBusy = true;
  renderSettings();
  try {
    if (action === 'relay-ask') {
      const { name, contact } = ui.relayKeyDraft;
      if (!name.trim()) throw new Error('이름을 넣어 주세요.');
      ui.relayKey = await api('/api/settings/relay-key', { method: 'POST', body: { name: name.trim(), contact: contact.trim() } });
      ui.relayKeyOpen = false;
    }
    if (action === 'relay-check' && await checkRelayKey()) {
      await loadSettings();
      if (ui.settings) ui.settingsDraft = { ...ui.settingsDraft, keys: draftFromSettings(ui.settings).keys };
    }
    if (action === 'relay-cancel') ui.relayKey = await api('/api/settings/relay-key', { method: 'DELETE' });
    ui.settingsError = '';
  } catch (error) {
    ui.settingsError = error.status === 429 ? '요청이 너무 많습니다. 한 시간 뒤에 다시 요청해 주세요.'
      : error.status === 502 ? 'Sida 자료 서버에 연결하지 못했습니다. 인터넷 연결을 확인하고 다시 시도해 주세요.'
        : error.message;
  } finally {
    ui.relayKeyBusy = false;
    renderSettings();
  }
}

export async function loadSettings() {
  try {
    ui.settings = await api('/api/settings');
    ui.settingsError = '';
  } catch (error) {
    ui.settingsError = error.message;
  }
}

// The ChatGPT model list takes about a second (OpenAI is asked), so it is kept while the app is
// open and asked again only for another account or after signing in again (`fresh`).
let modelsAccount = null;
async function loadChatgptModels({ fresh = false } = {}) {
  if (!ui.settings?.chatgpt.signed_in) { ui.chatgptModels = null; modelsAccount = null; return; }
  const account = ui.settings.chatgpt.email || '';
  if (!fresh && ui.chatgptModels?.length && modelsAccount === account) return;
  try {
    ui.chatgptModels = (await api('/api/settings/chatgpt/models')).models;
    modelsAccount = account;
  } catch (error) { ui.chatgptModels = null; ui.chatgptNote = `모델 목록을 받지 못했습니다. ${error.message}`; }
}

// Put the arrived model list into the model menus without redrawing the form, so a field being
// typed in keeps its focus.
function fillModelMenus() {
  if (!ui.chatgptModels?.length || !ui.settingsDraft || !settingsDialog.open) return;
  for (const select of settingsBody.querySelectorAll('#set-chatgpt-model, #set-worker-chatgpt-model')) {
    const value = ui.settingsDraft[select.dataset.field];
    select.innerHTML = ui.chatgptModels.map((m) => optionTag(m.slug, m.display_name || m.slug, value)).join('');
  }
}

function showPart(target) {
  const part = target && settingsBody.querySelector(target);
  if (!part) return;
  const folded = part.closest('details');
  if (folded && !folded.open) { folded.open = true; ui.settingsAdvancedOpen = true; }
  part.scrollIntoView({ block: 'center' });
  // A group gets the focus itself, so Enter cannot press one of its buttons by accident.
  if (!part.matches('input, select')) part.tabIndex = -1;
  part.focus({ preventScroll: true });
}

// The form is drawn at once from the settings the app already has, then again if fresh ones (a
// few hundredths of a second later) differ; the ChatGPT model menus fill in when the list arrives.
// `target`: a selector in the form to scroll to and focus (the sidebar's status lines open the
// part that needs attention). `opener`: the button pressed; the panel comes out on its side (the
// list's sidebar is on the left, the work screen's gear on the right; the right without one).
export async function openSettings(target = '', opener = null) {
  ui.settingsError = '';
  ui.chatgptNote = '';
  if (ui.settings) ui.settingsDraft = draftFromSettings(ui.settings);
  renderSettings();
  if (!settingsDialog.open) {
    const r = opener?.getBoundingClientRect();
    settingsDialog.classList.toggle('from-left', Boolean(r && r.left + r.width / 2 < innerWidth / 2));
    settingsDialog.showModal();
  }
  showPart(target);
  const shown = JSON.stringify([ui.settings, ui.relayKey]);
  await loadSettings();
  if (ui.settings && await checkRelayKey()) await loadSettings();
  // Redraw only when something changed, so a field clicked meanwhile keeps its focus.
  if (JSON.stringify([ui.settings, ui.relayKey]) !== shown || ui.settingsError) {
    if (ui.settings) ui.settingsDraft = draftFromSettings(ui.settings);
    renderSettings();
    showPart(target);
  }
  await loadChatgptModels();
  if (ui.chatgptNote) renderSettings(); // the list could not be fetched: show why
  else fillModelMenus();
}

async function saveSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  if (!s || !d) return;
  const changes = settingsChanges(s, d);
  try {
    if (d.openrouter_key.trim()) {
      await api('/api/settings/keys/openrouter', { method: 'PUT', body: { value: d.openrouter_key.trim() } });
    }
    for (const [key, value] of keyChanges(d.keys, s.keys)) {
      await api(`/api/settings/keys/${key}`, { method: 'PUT', body: { value } });
    }
    ui.settings = await api('/api/settings', { method: 'PUT', body: changes });
    ui.settingsDraft = draftFromSettings(ui.settings);
    ui.settingsError = '';
    settingsDialog.close();
    toast('설정을 저장했습니다.', 'success');
    render(false);
  } catch (error) {
    ui.settingsError = error.message;
    renderSettings();
  }
}

settingsDialog.addEventListener('change', (event) => {
  const field = event.target.dataset.field;
  if (!field || !ui.settingsDraft) return;
  const d = ui.settingsDraft;
  d[field] = event.target.type === 'checkbox' ? event.target.checked : event.target.value;
  if (field === 'mode' && d.mode !== 'custom') {
    // A mode sets both roles; keep the role choices consistent with it.
    const provider = d.mode === 'cloud' ? 'openrouter' : 'ollama';
    d.conductor_provider = provider;
    d.worker_provider = provider;
  }
  if (field === 'conductor_provider' || field === 'worker_provider') {
    d.mode = d.conductor_provider === d.worker_provider && d.conductor_provider !== 'chatgpt'
      ? (d.conductor_provider === 'openrouter' ? 'cloud' : 'local') : 'custom';
  }
  if (field !== 'openrouter_key') renderSettings();
});

settingsDialog.addEventListener('input', (event) => {
  if (!ui.settingsDraft) return;
  if (event.target.dataset.field === 'openrouter_key') ui.settingsDraft.openrouter_key = event.target.value;
  if (event.target.dataset.key) ui.settingsDraft.keys[event.target.dataset.key] = event.target.value;
  if (event.target.dataset.relay) ui.relayKeyDraft[event.target.dataset.relay] = event.target.value;
  updateFooter();
});

// Remember whether "고급" is open across redraws.
settingsDialog.addEventListener('toggle', (event) => {
  if (event.target.matches?.('.settings-advanced')) ui.settingsAdvancedOpen = event.target.open;
}, true);

settingsDialog.addEventListener('click', async (event) => {
  const button = event.target.closest('[data-settings]');
  if (!button) return;
  const action = button.dataset.settings;
  if (action === 'save') saveSettings();
  if (action === 'close') settingsDialog.close();
  if (['relay-ask', 'relay-check', 'relay-cancel'].includes(action)) relayKeyAction(action);
  if (action === 'relay-offer') { ui.relayKeyOpen = true; renderSettings(); }
  if (action === 'chatgpt-login') {
    try {
      const { authorize_url: url } = await api('/api/settings/chatgpt/login', { method: 'POST', body: {} });
      window.open(url, '_blank', 'noopener');
      ui.chatgptNote = '열린 창에서 로그인을 마치고 이 화면으로 돌아오면 상태가 바뀝니다. 10분 안에 끝내 주세요.';
    } catch (error) {
      ui.chatgptNote = error.message;
    }
    renderSettings();
  }
  if (action === 'chatgpt-logout') {
    try {
      const { revoked } = await api('/api/settings/chatgpt', { method: 'DELETE' });
      ui.chatgptNote = revoked ? '로그아웃했습니다.' : '이 PC에서는 로그아웃했지만 OpenAI 쪽 연결 해제를 확인하지 못했습니다. ChatGPT 설정에서 Sida 연결을 끊어 주세요.';
    } catch (error) {
      ui.chatgptNote = error.message;
    }
    const draft = ui.settingsDraft;
    await loadSettings();
    ui.settingsDraft = { ...draftFromSettings(ui.settings), ...draft, chatgpt_model: ui.settings.chatgpt.model, worker_chatgpt_model: ui.settings.chatgpt.worker_model };
    ui.chatgptModels = null;
    renderSettings();
  }
});



settingsForm.addEventListener('submit', (event) => {
  event.preventDefault(); // Enter in a field must not close the dialog unsaved
});

window.addEventListener('focus', async () => {
  // Coming back from the ChatGPT sign-in window.
  if (!settingsDialog.open || !ui.settings || !ui.settingsDraft) return;
  const before = ui.settings.chatgpt.signed_in;
  const draft = ui.settingsDraft;
  await loadSettings();
  if (!ui.settings) return;
  ui.settingsDraft = { ...draft };
  if (ui.settings.chatgpt.signed_in !== before) {
    ui.chatgptNote = ui.settings.chatgpt.signed_in ? 'ChatGPT 로그인을 확인했습니다.' : '';
    await loadChatgptModels({ fresh: true });
  }
  renderSettings();
});
