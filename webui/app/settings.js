// The settings dialog: run mode, providers, ChatGPT sign-in, keys, the Sida relay key.

import { PROVIDER_LABELS, MODE_LABELS, STATE_UPDATE_LABELS, escapeHtml as escape, DATA_KEYS, keyChanges, relayKeyView } from './model.js';
import { api } from './api.js';
import { render } from './render.js';
import { settingsBody, settingsDialog, settingsForm, toast, ui } from './state.js';

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

function renderSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  if (!s || !d) {
    settingsBody.innerHTML = `<p class="${ui.settingsError ? 'error-text' : 'muted'}">${escape(ui.settingsError || '설정을 불러오는 중입니다.')}</p>`;
    return;
  }
  const warnings = [
    s.warnings.openrouter_key_missing && 'OpenRouter 키가 없습니다. 클라우드 모델을 쓰려면 아래에 키를 넣어 주세요.',
    s.warnings.rag_key_missing && '법령 검색을 켰지만 법제처 인증값이 없습니다. 아래 정부 데이터 키에 넣어 주세요.',
    s.warnings.chatgpt_signed_out && 'ChatGPT 구독으로 돌리게 되어 있지만 로그인되어 있지 않습니다.',
  ].filter(Boolean);
  const modes = d.mode === 'custom' ? [...s.options.modes, 'custom'] : s.options.modes;
  const chatgpt = s.chatgpt;
  const models = ui.chatgptModels?.length ? ui.chatgptModels : [{ slug: d.chatgpt_model, display_name: d.chatgpt_model }];
  const modelSelect = (id, field, label, value) => `<label for="${id}">${label}</label>
    <select id="${id}" data-field="${field}">${(ui.chatgptModels?.length ? models : [{ slug: value, display_name: value }])
      .map((m) => optionTag(m.slug, m.display_name || m.slug, value)).join('')}</select>`;
  const chatgptBlock = d.conductor_provider === 'chatgpt' || d.worker_provider === 'chatgpt' || chatgpt.signed_in
    ? `<fieldset class="settings-group"><legend>ChatGPT 구독</legend>
        <p>${chatgpt.signed_in ? `로그인됨: ${escape(chatgpt.email || 'ChatGPT')}` : '로그인되어 있지 않습니다.'}</p>
        ${chatgpt.signed_in && !chatgpt.plan_usage ? '<p class="error-text">구독 사용을 허용하지 않아 Sida가 쓸 수 없습니다. 다시 로그인해 주세요.</p>' : ''}
        <div class="settings-buttons">
          <button type="button" class="secondary small" data-settings="chatgpt-login">${chatgpt.signed_in ? '다시 로그인' : 'ChatGPT로 로그인'}</button>
          ${chatgpt.signed_in ? '<button type="button" class="secondary small" data-settings="chatgpt-logout">로그아웃</button>' : ''}
        </div>
        ${ui.chatgptNote ? `<p class="muted">${escape(ui.chatgptNote)}</p>` : ''}
        ${chatgpt.signed_in ? modelSelect('set-chatgpt-model', 'chatgpt_model', 'Conductor 모델', d.chatgpt_model) : ''}
        ${chatgpt.signed_in && d.worker_provider === 'chatgpt' ? modelSelect('set-worker-chatgpt-model', 'worker_chatgpt_model', '전문가 모델', d.worker_chatgpt_model)
          + '<p class="muted small-text">전문가 문서는 길어서 구독 사용량을 Conductor보다 많이 씁니다.</p>' : ''}
      </fieldset>`
    : '';
  const keyStatus = s.keys?.openrouter;
  const dataKeys = DATA_KEYS.map(({ id, label, secret }) => {
    const status = s.keys?.[id];
    const hint = secret ? (status?.set ? `저장됨 ${status.hint || ''}` : '넣지 않음') : (id === 'relay_url' ? `비우면 ${s.relay?.default_url || '팀 서버'}` : '예: localhost');
    return `<label for="set-key-${id}">${escape(label)}</label>
      <input id="set-key-${id}" data-key="${id}" type="${secret ? 'password' : 'text'}" autocomplete="off" placeholder="${escape(hint)}" value="${escape(d.keys[id])}">`;
  }).join('');
  settingsBody.innerHTML = `
    ${s.first_run ? '<p class="settings-intro">처음 실행입니다. 실행 방식을 확인하고 저장해 주세요.</p>' : ''}
    ${warnings.map((w) => `<p class="event-note warn">${escape(w)}</p>`).join('')}
    <label for="set-mode">실행 모드</label>
    <select id="set-mode" data-field="mode">${modes.map((m) => optionTag(m, MODE_LABELS[m] || m, d.mode)).join('')}</select>
    ${d.mode === 'local' && s.options.local_profiles.length ? `<label for="set-profile">로컬 프로필</label>
      <select id="set-profile" data-field="local_profile">${s.options.local_profiles.map((p) => optionTag(p, p, d.local_profile)).join('')}</select>` : ''}
    <label for="set-conductor">Conductor</label>
    <select id="set-conductor" data-field="conductor_provider">${s.options.conductor_providers.map((p) => optionTag(p, PROVIDER_LABELS[p] || p, d.conductor_provider)).join('')}</select>
    <label for="set-worker">전문가</label>
    <select id="set-worker" data-field="worker_provider">${(s.options.worker_providers || s.options.providers).map((p) => optionTag(p, PROVIDER_LABELS[p] || p, d.worker_provider)).join('')}</select>
    <p class="muted small-text">지금 모델: Conductor ${escape(s.conductor.model)}, 전문가 ${escape(s.worker.model)}</p>
    ${chatgptBlock}
    <label for="set-openrouter">OpenRouter 키</label>
    <input id="set-openrouter" data-field="openrouter_key" type="password" autocomplete="off" placeholder="${escape(keyStatus?.set ? `저장됨 ${keyStatus.hint || ''}` : '키를 넣으면 저장할 때 확인합니다')}" value="${escape(d.openrouter_key)}">
    <label for="set-state">전문가 결과를 설계 상태에</label>
    <select id="set-state" data-field="state_update">${s.options.state_update.map((m) => optionTag(m, STATE_UPDATE_LABELS[m] || m, d.state_update)).join('')}</select>
    <label class="check"><input type="checkbox" data-field="rag_enabled" ${d.rag_enabled ? 'checked' : ''}> 법령 검색(법제처) 쓰기</label>
    <label class="check"><input type="checkbox" data-field="telemetry_enabled" ${d.telemetry_enabled ? 'checked' : ''}> 사용 기록 보내기 (브리프·문서 원문은 보내지 않음)</label>
    ${relayKeyBlock(s)}
    <fieldset class="settings-group"><legend>정부 데이터 키</legend>
      <p class="muted small-text">대지 조회(브이월드·공공데이터포털)와 법령 검색(법제처)에 씁니다. 이 PC에 키가 없는 서비스는 Sida 키로 Sida 자료 서버를 거쳐 부릅니다. 넣은 값은 이 PC의 .env에만 저장됩니다.</p>
      ${dataKeys}
    </fieldset>
    <p class="error-text" role="alert">${escape(ui.settingsError)}</p>
    <div class="form-actions"><button type="button" class="primary" data-settings="save">저장</button></div>`;
}

// "Sida 키 받기": ask the team's relay for a key, then wait for the team to approve it.
function relayKeyBlock(s) {
  const view = relayKeyView(ui.relayKey, Boolean(s.keys?.relay_token?.set));
  const form = view.form || (view.offer && ui.relayKeyOpen);
  const d = ui.relayKeyDraft;
  const busy = ui.relayKeyBusy ? 'disabled' : '';
  return `<fieldset class="settings-group"><legend>Sida 키 받기</legend>
    ${view.note ? `<p class="${view.tone === 'muted' ? 'muted small-text' : `event-note ${view.tone}`}">${escape(view.note)}</p>` : ''}
    ${view.offer && !ui.relayKeyOpen ? `<p class="muted small-text">Sida 키가 저장되어 있습니다.</p>
      <div class="settings-buttons"><button type="button" class="secondary small" data-settings="relay-offer">키 새로 요청</button></div>` : ''}
    ${form ? `<label for="set-relay-name">이름 (소속)</label>
      <input id="set-relay-name" data-relay="name" maxlength="80" autocomplete="name" placeholder="예: 홍길동 (OO대 건축학과)" value="${escape(d.name)}">
      <label for="set-relay-contact">연락처 (이메일이나 카톡 아이디, 선택)</label>
      <input id="set-relay-contact" data-relay="contact" maxlength="120" autocomplete="email" value="${escape(d.contact)}">
      <p class="muted small-text">이름과 연락처는 키를 승인하는 팀만 봅니다.</p>
      <div class="settings-buttons"><button type="button" class="secondary small" data-settings="relay-ask" ${busy}>키 요청</button></div>` : ''}
    ${view.waiting ? `<div class="settings-buttons">
      <button type="button" class="secondary small" data-settings="relay-check" ${busy}>승인됐는지 확인</button>
      <button type="button" class="secondary small" data-settings="relay-cancel" ${busy}>요청 취소</button></div>` : ''}
  </fieldset>`;
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

async function loadChatgptModels() {
  if (!ui.settings?.chatgpt.signed_in) { ui.chatgptModels = null; return; }
  try { ui.chatgptModels = (await api('/api/settings/chatgpt/models')).models; }
  catch (error) { ui.chatgptModels = null; ui.chatgptNote = `모델 목록을 받지 못했습니다. ${error.message}`; }
}

export async function openSettings() {
  ui.settingsError = '';
  ui.chatgptNote = '';
  renderSettings();
  if (!settingsDialog.open) settingsDialog.showModal();
  await loadSettings();
  if (ui.settings && await checkRelayKey()) await loadSettings();
  if (ui.settings) ui.settingsDraft = draftFromSettings(ui.settings);
  await loadChatgptModels();
  renderSettings();
}

async function saveSettings() {
  const s = ui.settings;
  const d = ui.settingsDraft;
  const changes = {};
  if (d.mode !== s.mode && d.mode !== 'custom') changes.mode = d.mode;
  if (d.local_profile !== s.local_profile) changes.local_profile = d.local_profile;
  if (d.conductor_provider !== s.conductor.provider) changes.conductor_provider = d.conductor_provider;
  if (d.worker_provider !== s.worker.provider) changes.worker_provider = d.worker_provider;
  if (d.chatgpt_model && d.chatgpt_model !== s.chatgpt.model) changes.chatgpt_model = d.chatgpt_model;
  if (d.worker_chatgpt_model && d.worker_chatgpt_model !== s.chatgpt.worker_model) changes.worker_chatgpt_model = d.worker_chatgpt_model;
  if (d.rag_enabled !== s.rag_enabled) changes.rag_enabled = d.rag_enabled;
  if (d.state_update !== s.state_update) changes.state_update = d.state_update;
  if (d.telemetry_enabled !== s.telemetry_enabled) changes.telemetry_enabled = d.telemetry_enabled;
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
});

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
    await loadChatgptModels();
  }
  renderSettings();
});
