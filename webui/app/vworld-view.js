// The board's masses inside VWorld's own WebGL 3D map, laid over the board area (the "브이월드 3D"
// button, command `vworld`). VWorld's 3D buildings are shown live in VWorld's viewer
// (vworld3d.html) and never kept or exported; the designer can click a building to hide it (the
// site's old building, say), and the board keeps which ones by VWorld's model id
// (PUT .../board/hidden). The board's own Three.js view and the export are unchanged.
import { massPolygons, siteRings, readLook } from './board-model.js';

// How this viewer likes the map (흰 모형, 바닥 사진 끄기): kept for this page (closing and opening
// the view keeps it), not in the project. The screen keeps nothing in browser storage
// (tests/test_webapp.py), so a reload starts with the photos on.
let pageLook = readLook(null);
function storedLook() { return pageLook; }
function storeLook(look) { pageLook = readLook(JSON.stringify(look)); }

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
        <button type="button" data-vworld="white" aria-pressed="false" title="건물의 사진을 빼고 흰 모형으로">흰 모형</button>
        <button type="button" data-vworld="plain" aria-pressed="false" title="바닥 항공사진 대신 회색 바닥">바닥 사진 끄기</button>
        <span class="vworld-note" role="status"></span>
      </div>
      <p class="vworld-credit">브이월드 3D 지도(국토교통부)를 실시간으로 보여 줍니다. 저장하거나 내보내지 않습니다. 건물을 누르면 숨겨집니다.</p>`;
    document.body.append(this.host);
    this.frame = this.host.querySelector('iframe');
    this.note = this.host.querySelector('.vworld-note');
    this.host.addEventListener('click', (e) => this.onClick(e));
    this.plan = null;
    this.script = '';
    this.look = storedLook();
    this.drawLook();
  }

  drawLook() {
    this.host.querySelector('[data-vworld="white"]').setAttribute('aria-pressed', String(this.look.white));
    this.host.querySelector('[data-vworld="plain"]').setAttribute('aria-pressed', String(this.look.plain));
  }

  toggleLook(key) {
    this.look = { ...this.look, [key]: !this.look[key] };
    storeLook(this.look);
    this.drawLook();
    this.frame.contentWindow.sidaVWorld?.setLook(this.look);
  }

  get open() { return !this.host.hidden; }

  say(text) { this.note.textContent = text; }

  // Lay the view over this box (the board area), as the table host is.
  place(r) {
    if (!r || !r.width) return;
    Object.assign(this.host.style, { left: `${r.left}px`, top: `${r.top}px`, width: `${r.width}px`, height: `${r.height}px` });
  }

  // Open over the board: the site's middle, the active scheme's masses and the hidden buildings.
  async show({ script, plan, paper, hidden, firstTime }) {
    this.plan = plan;
    this.host.hidden = false;
    if (this.script !== script) { // a new page only when the key changes; the map then stays loaded
      this.script = script;
      const at = new URLSearchParams({ script, lon: String(plan.origin.lon), lat: String(plan.origin.lat) });
      this.frame.src = `/app/vworld3d.html#${at}`;
      await new Promise((resolve) => this.frame.addEventListener('load', resolve, { once: true }));
    }
    const page = this.frame.contentWindow.sidaVWorld;
    this.say('브이월드 3D 지도를 여는 중…');
    const ok = page && await page.show({
      center: plan.origin, polygons: massPolygons(paper, plan), hidden, appearance: this.look,
      onHidden: (ids, byClick) => this.saved(ids, byClick),
    });
    if (!ok) { this.say(page?.failed() || '브이월드 3D 지도를 열지 못했습니다.'); return; }
    this.say(paper ? `${paper.title || '매스안'}을(를) 지반 위에 세웠습니다.` : '제도판에 매스안이 없습니다.');
    if (firstTime) await this.hideSite();
  }

  update(paper) {
    if (this.open && this.plan) this.frame.contentWindow.sidaVWorld?.setMasses(massPolygons(paper, this.plan));
  }

  async hideSite() {
    const page = this.frame.contentWindow.sidaVWorld;
    if (!page || !this.plan) return;
    this.say('대지 위 건물을 찾는 중…');
    const ids = await page.hideSite(siteRings(this.plan), this.plan.origin);
    this.say(ids.length ? `대지 위 건물 ${ids.length}개를 숨겼습니다. 다시 보려면 [숨긴 건물 모두 보이기].` : '대지 위에서 숨길 건물을 찾지 못했습니다. 건물을 직접 누르세요.');
  }

  async saved(ids, byClick) {
    try {
      await this.hooks.saveHidden(ids);
      if (byClick) this.say(`건물을 숨겼습니다 (숨긴 건물 ${ids.length}개).`);
    } catch (error) {
      this.say(`숨긴 건물을 저장하지 못했습니다. ${error.message}`);
    }
  }

  hide() { this.host.hidden = true; }

  onClick(e) {
    const what = e.target.closest('[data-vworld]')?.dataset.vworld;
    if (what === 'close') this.hooks.close();
    else if (what === 'site') this.hideSite();
    else if (what === 'white' || what === 'plain') this.toggleLook(what);
    else if (what === 'show-all') { this.frame.contentWindow.sidaVWorld?.showAll(); this.say('숨긴 건물을 모두 다시 보입니다.'); }
  }
}
