// 대지분석 다이어그램: a panel of the site analysis diagrams the server draws by rule from the
// surroundings (GET .../site/diagrams, sida/experts/site/site_diagrams.py). Each card shows its
// SVG, picks its range (기본: the range that suits the kind, 좁게/넓게 one step under or over it, in the
// shape picked for 주변 3D) and, for the shadow, one hour of
// 동지 9~15시 or all of them; the choice is kept for the project. A card goes on the table as a
// picture paper (so the deck takes it as a photo), or down as an SVG or PNG file.
// Methods of DraftingTable (table.js adds them to its prototype).

import { escapeHtml as escape } from './model.js';
import { siteDiagramQuery, siteDiagramLabel, SITE_DIAGRAM_RANGES } from './board-model.js';
import { diagramFileName } from './rhino-model.js';

// The diagram cards (the table's panel and the representation planner's 대지 다이어그램 tab share
// them): each with its picture, its range buttons, the shadow's hour and its files. `choice(kind)`
// is the kept {range, hour}, `url(diagram, choice)` the picture's address, `place` adds 제도판에 놓기.
// The buttons carry data-diagram (range, hour, place, svg, png) and data-kind.
export function diagramCards(data, { choice, url, place = false }) {
  const hours = data.hours || [];
  return data.diagrams.map((d) => {
    const picked = choice(d.kind);
    if (!d.ready) {
      return `<figure class="diagram-card is-off"><figcaption><b>${escape(d.title)}</b></figcaption><p class="diagram-why">${escape(d.reason)}</p></figure>`;
    }
    const ranges = d.kind === 'sun_path' ? '' : `<span class="seg" role="group" aria-label="${escape(d.title)} 범위">${SITE_DIAGRAM_RANGES.map(([id, word]) =>
      `<button type="button" data-diagram="range" data-kind="${d.kind}" data-value="${id}" aria-pressed="${picked.range === id}" title="${word}: ${escape(d.ranges?.[id]?.words || '')}">${word}</button>`).join('')}</span>`;
    const hour = d.kind === 'shadow' ? `<label class="diagram-hour">시각 <select data-diagram-hour="shadow" aria-label="그림자 시각">
        <option value="all" ${picked.hour === null ? 'selected' : ''}>9~15시 겹쳐 보기</option>
        ${hours.map((h) => `<option value="${h}" ${picked.hour === h ? 'selected' : ''}>${h}시</option>`).join('')}</select></label>` : '';
    return `<figure class="diagram-card">
      <figcaption><b>${escape(d.title)}</b>${ranges}</figcaption>
      ${hour}
      <img src="${escape(url(d, picked))}" alt="${escape(siteDiagramLabel(d, picked))}" loading="lazy" decoding="async">
      <div class="diagram-actions" role="group" aria-label="${escape(d.title)}">
        ${place ? `<button type="button" data-diagram="place" data-kind="${d.kind}" title="이 다이어그램을 그림 종이로 제도판에 올리기 (발표 자료에도 들어갑니다)">제도판에 놓기</button>` : ''}
        <button type="button" data-diagram="svg" data-kind="${d.kind}" title="SVG 파일로 받기">SVG</button>
        <button type="button" data-diagram="png" data-kind="${d.kind}" title="PNG 파일로 받기">PNG</button>
      </div></figure>`;
  }).join('');
}

export const diagramsMethods = {
  // Open or close the panel; the list is asked for when it opens (the surroundings are read from
  // the map packs, out to the widest range).
  async toggleDiagrams() {
    if (this.diagramsOpen) { this.diagramsOpen = false; this.drawDiagramPanel(); this.drawControls(); return; }
    if (!this.site?.plan) { this.say('먼저 대지를 조회하세요. 대지 경계가 있어야 주변으로 다이어그램을 그릴 수 있습니다.'); return; }
    this.diagramsOpen = true;
    this.drawControls();
    if (!this.siteDiagrams) await this.loadDiagrams();
    else this.drawDiagramPanel();
  },
  async loadDiagrams() {
    if (!this.hooks.siteDiagrams) return;
    const request = Symbol();
    this.diagramsRequest = request;
    this.diagramsBusy = true;
    this.diagramsError = '';
    this.drawDiagramPanel();
    try {
      const got = await this.hooks.siteDiagrams();
      if (request !== this.diagramsRequest) return;
      this.siteDiagrams = got;
      this.diagramsVersion = Date.now(); // a new list draws the pictures again (the surroundings may have changed)
    } catch (error) {
      if (request !== this.diagramsRequest) return;
      this.diagramsError = error.message || String(error);
    }
    this.diagramsBusy = false;
    this.drawDiagramPanel();
  },
  // The site or the surroundings' range changed: what was drawn for the old one goes.
  forgetDiagrams() {
    this.diagramsRequest = null;
    this.diagramsBusy = false;
    this.siteDiagrams = null;
    if (this.diagramsOpen) this.loadDiagrams();
  },
  diagramChoice(kind) {
    const d = this.siteDiagrams?.diagrams?.find((x) => x.kind === kind);
    return d ? { range: d.range, hour: Number.isInteger(d.hour) ? d.hour : null } : { range: 'default', hour: null };
  },
  drawDiagramPanel() {
    const el = this.ui?.diagrams;
    if (!el) return;
    el.hidden = !this.diagramsOpen;
    if (!this.diagramsOpen) { el.innerHTML = ''; return; }
    const data = this.siteDiagrams;
    const head = `<header><h3>대지분석 다이어그램</h3><button type="button" data-ui="diagrams" aria-label="대지분석 다이어그램 닫기" title="닫기">×</button></header>`;
    if (this.diagramsBusy && !data) { el.innerHTML = `${head}<p class="diagram-note" role="status">주변 자료를 모으는 중입니다.</p>`; return; }
    if (this.diagramsError && !data) {
      el.innerHTML = `${head}<p class="diagram-note" role="alert">다이어그램을 그릴 자료를 받지 못했습니다. ${escape(this.diagramsError)}</p>
        <button type="button" class="diagram-retry" data-diagram="reload">다시 시도</button>`;
      return;
    }
    if (!data) { el.innerHTML = head; return; }
    const cards = diagramCards(data, {
      choice: (kind) => this.diagramChoice(kind),
      url: (d, choice) => this.hooks.siteDiagramUrl(d.kind, `${siteDiagramQuery(d.kind, choice)}&v=${this.diagramsVersion || 0}`),
      place: true,
    });
    el.innerHTML = `${head}
      <p class="diagram-note">다이어그램마다 알맞은 범위(기본)에서 한 단계 좁히거나 넓힐 수 있는 참고 도면입니다. 모양은 주변 3D 범위를 따릅니다. 파일에 담을 수 있는 공공 자료만 씁니다${data.source ? ` (건물: ${escape(data.source)})` : ''}.</p>
      <div class="diagram-cards">${cards}</div>`;
  },
  // A card's button: its range, a file, or the table.
  async diagramAction(action, kind, value) {
    if (action === 'reload') { this.loadDiagrams(); return; }
    const d = this.siteDiagrams?.diagrams?.find((x) => x.kind === kind);
    if (!d) return;
    const choice = this.diagramChoice(kind);
    if (action === 'range' || action === 'hour') {
      const next = action === 'range' ? { ...choice, range: value } : { ...choice, hour: value === 'all' ? null : Number(value) };
      Object.assign(d, next);
      this.drawDiagramPanel();
      try {
        Object.assign(d, await this.hooks.keepSiteDiagram(kind, next));
      } catch (error) {
        this.say(`고른 범위를 저장하지 못했습니다. ${error.message}`);
      }
      return;
    }
    const label = siteDiagramLabel(d, choice);
    const query = siteDiagramQuery(kind, choice);
    try {
      if (action === 'svg' || action === 'png') {
        const blob = await this.hooks.siteDiagramFile(kind, query, action);
        this.hooks.saveFile(blob, diagramFileName('', label, action));
        this.say(`${label}을(를) ${action.toUpperCase()}로 내려받았습니다.`);
      } else if (action === 'place') {
        this.say(`${label}을(를) 제도판에 올리는 중입니다…`);
        const png = await this.hooks.siteDiagramFile(kind, query, 'png');
        await this.addPhotos([new File([png], diagramFileName('', label, 'png'), { type: 'image/png' })]);
      }
    } catch (error) {
      this.say(`${d.title}을(를) 만들지 못했습니다. ${error instanceof TypeError ? 'Sida 서버에 연결할 수 없습니다.' : error.message}`);
    }
  },
};
