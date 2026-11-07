// The board's masses inside VWorld's own WebGL 3D map, laid over the board area (the "브이월드 3D"
// button, command `vworld`). VWorld's 3D buildings are shown live in VWorld's viewer
// (vworld3d.html) and never kept or exported. The designer picks a building with a click and
// hides it after confirming ([이 건물 숨기기] or Delete; Esc cancels); Ctrl+Z / Ctrl+Shift+Z (Ctrl+Y)
// undo and redo the hiding steps. The board keeps which buildings are hidden by VWorld's model id
// (PUT .../board/hidden). The board's own Three.js view and the export are unchanged.
//
// The map page is the app's own (this PC has a VWorld key) or the Sida data server's (it hasn't;
// another origin), so the two talk only by postMessage (vworld3d-frame.js has the messages).
import {
  massPolygons, siteRings, readLook, hideBuildings, startHistory, commitHistory, undoHistory, redoHistory, hideKey,
  vworldFrame,
} from './board-model.js';

const TAG = 'vworld3d';

// How this viewer likes the map (흰 모형, 바닥 사진 끄기, 건물 이름 끄기): kept for this page (closing
// and opening the view keeps it), not in the project. The screen keeps nothing in browser storage
// (tests/test_webapp.py), so a reload starts with the photos and names on.
let pageLook = readLook(null);

const TOGGLES = [
  ['white', '흰 모형', '건물의 사진을 빼고 흰 모형으로'],
  ['plain', '바닥 사진 끄기', '바닥 항공사진 대신 회색 바닥'],
  ['noNames', '건물 이름 끄기', '브이월드의 건물·장소 이름 글자를 끄기'],
];

export class VWorldView {
  // hooks: { saveHidden(ids) -> Promise, close() }
  constructor(hooks) {
    this.hooks = hooks;
    this.host = document.createElement('div');
    this.host.className = 'vworld-host';
    this.host.hidden = true;
    this.host.innerHTML = `<iframe title="브이월드 3D 지도" class="vworld-frame"></iframe>
      <div class="vworld-bar" role="toolbar" aria-label="브이월드 3D">
        <button type="button" data-vworld="close">제도판으로</button>
        <button type="button" data-vworld="site">대지 위 건물 숨기기</button>
        <button type="button" data-vworld="show-all">숨긴 건물 모두 보이기</button>
        <button type="button" data-vworld="undo" title="되돌리기 (Ctrl+Z)" aria-label="숨기기 되돌리기">↶</button>
        <button type="button" data-vworld="redo" title="다시 하기 (Ctrl+Shift+Z, Ctrl+Y)" aria-label="숨기기 다시 하기">↷</button>
        ${TOGGLES.map(([key, label, title]) => `<button type="button" data-vworld="look" data-look="${key}" aria-pressed="false" title="${title}">${label}</button>`).join('')}
        <span class="vworld-pick" hidden>고른 건물을 <button type="button" class="primary-small" data-vworld="hide-picked">이 건물 숨기기</button>
          <button type="button" data-vworld="unpick">취소</button><small>Delete: 숨기기 · Esc: 취소</small></span>
        <span class="vworld-note" role="status"></span>
      </div>
      <p class="vworld-credit">브이월드 3D 지도(국토교통부)를 실시간으로 보여 줍니다. 저장하거나 내보내지 않습니다. 건물을 누르면 골라지고, [이 건물 숨기기]로 숨깁니다.</p>`;
    document.body.append(this.host);
    this.frame = this.host.querySelector('iframe');
    this.note = this.host.querySelector('.vworld-note');
    this.pickBox = this.host.querySelector('.vworld-pick');
    this.host.addEventListener('click', (e) => this.onClick(e));
    // the keys while the view is open and the focus is outside the map (the map sends its own)
    window.addEventListener('keydown', (e) => {
      if (!this.open || e.target.closest?.('input, textarea, select, [contenteditable="true"]')) return;
      if (this.onKey({ key: e.key, ctrl: e.ctrlKey, meta: e.metaKey, shift: e.shiftKey })) {
        e.preventDefault();
        e.stopImmediatePropagation(); // not the board's own undo or command line
      }
    }, true);
    this.plan = null;
    this.frameKey = '';
    this.frameOrigin = '';
    this.loaded = false;
    this.calls = new Map(); // message id → { resolve, reject }
    this.nextId = 1;
    this.look = pageLook;
    this.history = startHistory([]);
    this.picked = '';
    window.addEventListener('message', (e) => this.onMessage(e));
    this.drawBar();
  }

  // Ask the map page; resolves with its answer (null when no map page is loaded).
  ask(method, ...args) {
    if (!this.loaded || !this.frameOrigin) return Promise.resolve(null);
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      this.calls.set(id, { resolve, reject });
      this.frame.contentWindow.postMessage({ sida: TAG, id, method, args }, this.frameOrigin);
    });
  }

  // Answers and events from the map page only (its window and its origin).
  onMessage(e) {
    const m = e.data;
    if (e.source !== this.frame.contentWindow || e.origin !== this.frameOrigin || m?.sida !== TAG) return;
    if (m.event === 'pick') { this.onPick(typeof m.id === 'string' ? m.id : ''); return; }
    if (m.event === 'key') { this.onKey({ key: String(m.key || ''), ctrl: Boolean(m.ctrl), meta: Boolean(m.meta), shift: Boolean(m.shift) }); return; }
    const call = this.calls.get(m.id);
    if (!call) return;
    this.calls.delete(m.id);
    if (m.error) call.reject(new Error(m.error)); else call.resolve(m.result);
  }

  // A new map page: the questions to the old one get no answer.
  dropCalls() {
    for (const call of this.calls.values()) call.resolve(null);
    this.calls.clear();
  }

  get open() { return !this.host.hidden; }

  say(text) { this.note.textContent = text; }

  drawBar() {
    for (const b of this.host.querySelectorAll('[data-look]')) b.setAttribute('aria-pressed', String(Boolean(this.look[b.dataset.look])));
    this.host.querySelector('[data-vworld="undo"]').disabled = !this.history.past.length;
    this.host.querySelector('[data-vworld="redo"]').disabled = !this.history.future.length;
    this.pickBox.hidden = !this.picked;
  }

  toggleLook(key) {
    this.look = { ...this.look, [key]: !this.look[key] };
    pageLook = this.look;
    this.drawBar();
    this.ask('setLook', this.look);
  }

  // Lay the view over this box (the board area), as the table host is.
  place(r) {
    if (!r || !r.width) return;
    Object.assign(this.host.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  }

  // Open over the board: the site's middle, the active scheme's masses and the hidden buildings.
  // `webgl3d` is GET /api/site/map's: which map page to open (the app's or the data server's).
  async show({ webgl3d, plan, paper, hidden, firstTime }) {
    this.plan = plan;
    this.host.hidden = false;
    this.history = startHistory(hidden || []);
    this.picked = '';
    this.drawBar();
    const frame = vworldFrame(webgl3d, plan.origin, window.location.origin);
    if (!frame) { this.say('브이월드 3D 지도를 열 수 없습니다.'); return; }
    if (this.frameKey !== frame.key) { // a new page only when the page or key changes; the map then stays loaded
      this.frameKey = frame.key;
      this.dropCalls();
      this.loaded = false;
      this.frameOrigin = new URL(frame.src, window.location.href).origin;
      this.frame.src = frame.src;
      await new Promise((resolve) => this.frame.addEventListener('load', resolve, { once: true }));
      this.loaded = true;
    }
    this.say('브이월드 3D 지도를 여는 중…');
    const ok = await this.ask('show', {
      center: plan.origin, polygons: massPolygons(paper, plan), hidden: this.history.present, appearance: this.look,
    });
    if (!ok) { this.say((await this.ask('failed')) || '브이월드 3D 지도를 열지 못했습니다.'); return; }
    this.say(paper ? `${paper.title || '매스안'}을(를) 지반 위에 세웠습니다.` : '제도판에 매스안이 없습니다.');
    if (firstTime) await this.hideSite();
  }

  update(paper) {
    if (this.open && this.plan) this.ask('setMasses', massPolygons(paper, this.plan));
  }

  // A hiding step: the new hidden list is drawn, kept for undo and saved in the project.
  async change(next, done) {
    const before = this.history;
    this.history = commitHistory(this.history, next);
    if (this.history === before) return;
    await this.apply(done);
  }

  async apply(done) {
    this.picked = '';
    this.ask('setHidden', this.history.present);
    this.drawBar();
    try {
      await this.hooks.saveHidden(this.history.present);
      this.say(done);
    } catch (error) {
      this.say(`숨긴 건물을 저장하지 못했습니다. ${error.message}`);
    }
  }

  async hideSite() {
    if (!this.loaded || !this.plan) return;
    this.say('대지 위 건물을 찾는 중…');
    const ids = (await this.ask('findSite', siteRings(this.plan), this.plan.origin)) || [];
    if (!ids.length) { this.say('대지 위에서 숨길 건물을 찾지 못했습니다. 건물을 눌러 고른 뒤 숨기세요.'); return; }
    await this.change(hideBuildings(this.history.present, ids), `대지 위 건물 ${ids.length}개를 숨겼습니다. 되돌리려면 Ctrl+Z.`);
  }

  onPick(id) {
    this.picked = id;
    this.drawBar();
    if (id) this.say('');
  }

  hidePicked() {
    if (!this.picked) return;
    const n = this.history.present.length + 1;
    this.change(hideBuildings(this.history.present, [this.picked]), `건물을 숨겼습니다 (숨긴 건물 ${n}개). 되돌리려면 Ctrl+Z.`);
  }

  unpick() { this.picked = ''; this.ask('unpick'); this.drawBar(); }

  undo() {
    const next = undoHistory(this.history);
    if (next === this.history) { this.say('되돌릴 것이 없습니다.'); return; }
    this.history = next;
    this.apply(`되돌렸습니다 (숨긴 건물 ${next.present.length}개).`);
  }

  redo() {
    const next = redoHistory(this.history);
    if (next === this.history) { this.say('다시 할 것이 없습니다.'); return; }
    this.history = next;
    this.apply(`다시 했습니다 (숨긴 건물 ${next.present.length}개).`);
  }

  // A key from the page or from the map: true when it was the view's (hide, cancel, undo, redo).
  onKey(k) {
    const what = hideKey(k, Boolean(this.picked));
    if (what === 'hide') this.hidePicked();
    else if (what === 'cancel') this.unpick();
    else if (what === 'undo') this.undo();
    else if (what === 'redo') this.redo();
    return Boolean(what);
  }

  hide() { this.unpick(); this.host.hidden = true; }

  onClick(e) {
    const button = e.target.closest('[data-vworld]');
    const what = button?.dataset.vworld;
    if (what === 'close') this.hooks.close();
    else if (what === 'site') this.hideSite();
    else if (what === 'look') this.toggleLook(button.dataset.look);
    else if (what === 'hide-picked') this.hidePicked();
    else if (what === 'unpick') this.unpick();
    else if (what === 'undo') this.undo();
    else if (what === 'redo') this.redo();
    else if (what === 'show-all') this.change([], '숨긴 건물을 모두 다시 보입니다. 되돌리려면 Ctrl+Z.');
  }
}
