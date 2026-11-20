// 자동 조경 (2026-11-20 지훈 "영역 지정하면 조경 알아서 해주는 그런거"): three layouts drawn by rule in
// the region picked (GET .../landscape, sida/experts/landscape/): 정형·자연형·광장형, each with how
// it stands against the 조경·교목·공개 공지 the rules ask (each with the 원문). The designer picks one,
// draws a region of their own (clicks on the ground; Enter or a double click closes it, Esc
// cancels, Backspace takes the last point back), shuffles the trees and places the plan on the
// table: a placed plan stays in 3D with the tool closed, goes into the CAD/Rhino export and is
// told to the Conductor. The ground lies flat on the table; the trees rise with the masses.
// 4단계 (11/20): the knobs (조절: plaza size, trees, path and shrub band widths) turn all three; the
// Conductor's proposals ("광장 넓히고 나무 더") come beside them to look at, compare (비교) and place.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import {
  LANDSCAPE_HEDGE, LANDSCAPE_KINDS, LANDSCAPE_PATH, LANDSCAPE_PLAZA, LANDSCAPE_TREES, LANDSCAPE_TREE_COLORS, landscapeCard, landscapeCompare,
  landscapeHedge, landscapeMiniPlan, landscapeRing, landscapeShown, landscapeTakeProposal, landscapeTreeGroups, treeTriangles,
} from './board-model.js';

const REFRESH_MS = 700; // after a mass edit, the plans are worked out again this long after the last one

export const landscapeMethods = {
  // Open or close the card; the first time (and after the site changed) the plans are asked for.
  async toggleLandscape() {
    if (this.landscapeBusy) return;
    if (this.landscapeOn) {
      this.landscapeOn = false;
      this.landscapePreview = '';
      this.landscapeComparing = false;
      this.cancelLandscapeRegion(true);
      this.drawLandscape(); this.drawControls();
      return;
    }
    if (!this.site?.plan) { this.say('먼저 대지를 조회하세요. 대지 경계가 있어야 조경을 그릴 수 있습니다.'); return; }
    if (!this.landscape?.plans?.length || this.landscape.keptOnly) await this.fetchLandscape();
    this.landscapeOn = Boolean(this.landscape?.plans?.length);
    this.drawLandscape(); this.drawControls();
  },
  // Ask for the plans (with `changes`, keep them first). `quiet`: the table opening, which only
  // brings back a placed plan and asks no map.
  async fetchLandscape(changes = null, { quiet = false } = {}) {
    if (!this.hooks.landscape) return;
    const request = Symbol();
    this.landscapeRequest = request;
    if (!quiet) { this.landscapeBusy = true; this.drawControls(); }
    try {
      const data = changes ? await this.hooks.saveLandscape(changes) : await this.hooks.landscape(quiet);
      if (request !== this.landscapeRequest) return;
      this.landscape = { ...data, keptOnly: quiet };
      if (!(data.proposals || []).some((k) => k.id === this.landscapePreview)) this.landscapePreview = '';
    } catch (error) {
      if (request !== this.landscapeRequest) return;
      if (!quiet) this.say(`조경을 그리지 못했습니다. ${error.message}`);
    }
    this.landscapeBusy = false;
    if (!quiet) this.drawControls();
  },
  // The table opened (or the site came back): a placed plan stands again.
  restoreLandscape() {
    if (this.landscapeAsked || !this.site?.plan) return;
    this.landscapeAsked = true;
    this.fetchLandscape(null, { quiet: true }).then(() => this.drawLandscape());
  },
  // The site changed: what was worked out for the old one goes.
  forgetLandscape() {
    this.landscapeRequest = null;
    this.landscapeBusy = false;
    this.landscapeOn = false;
    this.landscape = null;
    this.landscapeAsked = false;
    this.landscapeKey = '';
    this.landscapePreview = '';
    this.landscapeComparing = false;
    clearTimeout(this.landscapeTimer);
    this.cancelLandscapeRegion(true);
    this.drawLandscape();
  },
  // The masses changed (an edit here, or the board read again): the plans shown are worked out
  // again a moment after the last change.
  landscapeMassesChanged() {
    const key = JSON.stringify(this.papers.filter((p) => p.kind === 'mass').map((p) => [p.id, p.blocks, p.floor_height]));
    const before = this.landscapeKey;
    this.landscapeKey = key;
    if (!before || before === key) return;
    if (!(this.landscapeOn || this.landscape?.settings?.placed)) return;
    clearTimeout(this.landscapeTimer);
    this.landscapeTimer = setTimeout(async () => {
      await this.fetchLandscape(null, { quiet: !this.landscapeOn });
      this.drawLandscape();
    }, REFRESH_MS);
  },
  // Keep a change of the card (style, seed, tune, use, mass, region, placed) and draw the plans again.
  async changeLandscape(changes) {
    await this.fetchLandscape(changes);
    this.drawLandscape();
  },
  // Turn one knob (the others stay as they are).
  tuneLandscape(knob, value) {
    const tune = { ...(this.landscape?.settings?.tune || {}), [knob]: value };
    this.landscapePreview = '';
    return this.changeLandscape({ tune });
  },
  landscapeAction(action, value) {
    const s = this.landscape?.settings || {};
    const proposal = (this.landscape?.proposals || []).find((k) => k.id === value);
    switch (action) {
      case 'style': this.landscapePreview = ''; this.changeLandscape({ style: value }); break;
      case 'shuffle': this.changeLandscape({ seed: (s.seed % 9999) + 1 }); break;
      case 'place': this.changeLandscape({ placed: !s.placed }); break;
      case 'whole': this.changeLandscape({ region: null }); break;
      case 'draw': this.startLandscapeRegion(); break;
      case 'plaza': case 'trees': this.tuneLandscape(action, value); break;
      case 'reset': this.landscapePreview = ''; this.changeLandscape({ tune: null }); break;
      case 'proposal': this.landscapePreview = this.landscapePreview === value ? '' : value; this.drawLandscape(); break;
      case 'take': // a proposal (or, from the comparison, a style) goes on the table
        this.landscapePreview = '';
        this.landscapeComparing = false;
        this.changeLandscape(proposal ? landscapeTakeProposal(proposal) : { style: value, placed: true });
        break;
      case 'drop': this.dropLandscapeProposal(value); break;
      case 'compare': this.landscapeComparing = !this.landscapeComparing; this.drawLandscapeCompare(); break;
      default: break;
    }
  },
  landscapeSelect(target) {
    if (target.id === 'landscape-use') this.changeLandscape({ use: target.value || null });
    if (target.id === 'landscape-mass') this.changeLandscape({ mass: target.value || null });
    if (target.id === 'landscape-path') this.tuneLandscape('path', Number(target.value));
    if (target.id === 'landscape-hedge') this.tuneLandscape('hedge', landscapeHedge(target.value));
  },
  // A slider moved: its figure follows before the plans are asked again (on change).
  landscapeSlide(target) {
    const out = target.id === 'landscape-path' || target.id === 'landscape-hedge' ? this.ui?.landscape?.querySelector(`output[for="${target.id}"]`) : null;
    if (!out) return;
    const v = target.id === 'landscape-hedge' ? landscapeHedge(target.value) : Number(target.value);
    out.textContent = target.id === 'landscape-hedge' && v === 0 ? '없음' : `${v.toFixed(1)}m`;
  },
  async dropLandscapeProposal(id) {
    if (!this.hooks.dropLandscapeProposal) return;
    try {
      const data = await this.hooks.dropLandscapeProposal(id);
      this.landscape = { ...data, keptOnly: false };
      if (this.landscapePreview === id) this.landscapePreview = '';
    } catch (error) {
      this.say(`조경 제안을 지우지 못했습니다. ${error.message}`);
    }
    this.drawLandscape();
  },
  // "조경 광장 넓게 나무 더" on the command line (command-model readLandscape): the card opens and
  // the knobs turn by rule. Returns a problem to say, or ''.
  landscapeCommand(cmd) {
    if (!this.site?.plan) return '먼저 대지를 조회하세요. 대지 경계가 있어야 조경을 그릴 수 있습니다.';
    if (this.landscapeBusy) return '조경을 그리는 중입니다. 끝나면 다시 해 주세요.';
    const run = async () => {
      if (!this.landscapeOn) {
        if (!this.landscape?.plans?.length || this.landscape.keptOnly) await this.fetchLandscape();
        this.landscapeOn = Boolean(this.landscape?.plans?.length);
        if (!this.landscapeOn) { this.drawLandscape(); this.drawControls(); return; }
      }
      const s = this.landscape.settings || {};
      const changes = {};
      if (cmd.style) changes.style = cmd.style;
      if (cmd.reset) changes.tune = null;
      if (Object.keys(cmd.tune || {}).length) changes.tune = { ...(cmd.reset ? {} : s.tune || {}), ...cmd.tune };
      if (cmd.shuffle) changes.seed = (s.seed % 9999) + 1;
      if (cmd.place) changes.placed = true;
      this.landscapePreview = '';
      if (cmd.compare) this.landscapeComparing = true;
      if (Object.keys(changes).length) await this.changeLandscape(changes);
      else this.drawLandscape();
      this.drawControls();
    };
    run();
    return '';
  },
  // The Conductor proposed a layout (engine event domain_tool, open "landscape"): the card opens
  // on the newest proposal, the table unchanged.
  async showLandscapeProposal() {
    if (!this.site?.plan) return;
    await this.fetchLandscape();
    const newest = (this.landscape?.proposals || []).at(-1);
    this.landscapeOn = Boolean(this.landscape?.plans?.length);
    this.landscapePreview = newest?.id || '';
    this.drawLandscape(); this.drawControls();
  },

  // ---------------------------------------------------------------- the region drawn by hand

  startLandscapeRegion() {
    this.landscapeDrawing = [];
    if (this.view.tilt > 30) this.animateTo({ tilt: 0 }); // drawn in plan
    this.say('땅 위를 눌러 조경할 영역의 꼭짓점을 찍으세요. Enter나 두 번 눌러 닫고, Esc는 취소, Backspace는 한 점 되돌리기입니다.');
    this.drawLandscapeCard();
    this.drawLandscapeDraft();
  },
  landscapePoint(clientX, clientY) {
    const g = this.ground(clientX, clientY);
    if (!g || !this.landscapeDrawing) return;
    this.landscapeDrawing.push([g.x, g.y]);
    this.drawLandscapeDraft();
  },
  landscapeBack() {
    if (!this.landscapeDrawing?.length) return;
    this.landscapeDrawing.pop();
    this.drawLandscapeDraft();
  },
  finishLandscapeRegion() {
    const ring = landscapeRing(this.landscapeDrawing);
    if (!ring) { this.say('영역은 꼭짓점이 셋 이상이어야 합니다.'); return; }
    this.cancelLandscapeRegion(true);
    this.changeLandscape({ region: ring });
  },
  cancelLandscapeRegion(quietly = false) {
    if (!this.landscapeDrawing) return;
    this.landscapeDrawing = null;
    this.gl?.draft.clear();
    this.invalidate();
    if (!quietly) this.say('영역 그리기를 취소했습니다.');
    this.drawLandscapeCard();
  },
  drawLandscapeDraft() {
    if (!this.gl || !this.landscapeDrawing) return;
    const pts = this.landscapeDrawing.map(([x, y]) => [x, y, 0]);
    if (pts.length === 1) pts.push([pts[0][0] + 0.01, pts[0][1], 0]);
    if (pts.length) this.drawDraft(pts, pts.length >= 3);
    else { this.gl.draft.clear(); this.invalidate(); }
  },

  // ---------------------------------------------------------------- drawing

  // The plan shown (while the card is open) or placed: the ground kinds flat on the table, a
  // little apart so they do not flicker, the trees standing on it; the trees rise with the
  // masses (render()).
  drawLandscape() {
    this.drawLandscapeCard();
    if (!this.gl) return;
    const group = this.gl.landscape;
    group.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
    group.clear();
    const data = this.landscape;
    const plan = (this.landscapeOn || data?.settings?.placed) ? landscapeShown(data, this.landscapeOn ? this.landscapePreview : '') : null;
    if (!plan) { this.invalidate(); return; }
    const frame = this.site?.plan?.frame || { x: 0, y: 0, angle: 0 };
    const base = this.blockBase(frame, { u: 0, v: 0, w: 0, d: 0 }); // the ground under the site's middle
    LANDSCAPE_KINDS.forEach(([kind, , color], k) => {
      const parts = plan.zones?.[kind] || [];
      if (!parts.length) return;
      const material = new THREE.MeshLambertMaterial({ color, side: THREE.DoubleSide });
      for (const part of parts) {
        const shape = new THREE.Shape(part.outer.map(([x, y]) => new THREE.Vector2(x, y)));
        for (const hole of part.holes || []) shape.holes.push(new THREE.Path(hole.map(([x, y]) => new THREE.Vector2(x, y))));
        const mesh = new THREE.Mesh(new THREE.ShapeGeometry(shape), material);
        mesh.position.z = base + 0.04 + k * 0.012;
        mesh.receiveShadow = true;
        group.add(mesh);
      }
    });
    for (const { kind, trees } of landscapeTreeGroups(plan, base + 0.1)) {
      const tri = treeTriangles(trees, { around: 7, rings: 4 });
      const mesh = (positions, color) => {
        const geom = new THREE.BufferGeometry();
        geom.setAttribute('position', new THREE.Float32BufferAttribute(positions, 3));
        geom.computeVertexNormals();
        const m = new THREE.Mesh(geom, new THREE.MeshLambertMaterial({ color }));
        m.castShadow = true;
        return m;
      };
      group.add(mesh(tri.crowns, LANDSCAPE_TREE_COLORS[kind]), mesh(tri.trunks, LANDSCAPE_TREE_COLORS.trunk));
    }
    this.invalidate();
  },
  drawLandscapeCard() {
    const el = this.ui?.landscape;
    if (!el) return;
    const card = this.landscapeOn ? landscapeCard(this.landscape, this.landscapePreview) : null;
    el.hidden = !card;
    this.drawLandscapeCompare();
    if (!card) { el.innerHTML = ''; return; }
    const looked = card.proposal;
    const plan = looked || card.plans.find((p) => p.selected) || card.plans[0];
    const drawing = Boolean(this.landscapeDrawing);
    const busy = this.landscapeBusy ? 'disabled' : '';
    const k = card.knobs;
    const massForm = card.masses.length > 1 ? `<label class="landscape-field"><span>매스안</span>
        <select id="landscape-mass" ${busy}>${card.masses.map((m) => `<option value="${escape(m.id)}"${m.id === card.mass ? ' selected' : ''}>${escape(m.title || m.id)}</option>`).join('')}</select></label>` : '';
    const useForm = `<label class="landscape-field"><span>건물 용도 <small>공개 공지</small></span>
        <select id="landscape-use" ${busy}><option value="">고르기</option>${card.uses.map((u) => `<option value="${escape(u.key)}"${u.selected ? ' selected' : ''}>${escape(u.label)}</option>`).join('')}</select></label>`;
    const seg = (knob, label, options) => `<div class="landscape-knob"><span id="landscape-${knob}-label">${label}</span>
        <div class="seg" role="group" aria-labelledby="landscape-${knob}-label">${options.map(([key, word]) => `<button type="button" data-landscape="${knob}" data-value="${key}" aria-pressed="${k[knob] === key}" ${busy}>${word}</button>`).join('')}</div></div>`;
    const knobs = `<section class="landscape-tune" aria-label="조절">
        <header><h4>조절</h4>${k.changed ? `<button type="button" data-landscape="reset" title="네 가지 조절값을 안의 기본으로" ${busy}>처음대로</button>` : ''}</header>
        ${seg('plaza', '광장 크기', LANDSCAPE_PLAZA)}
        ${seg('trees', '나무 수', LANDSCAPE_TREES)}
        <div class="landscape-knob"><label for="landscape-path">길 폭</label><output for="landscape-path">${k.pathValue.toFixed(1)}m</output>
          <input id="landscape-path" type="range" min="${LANDSCAPE_PATH[0]}" max="${LANDSCAPE_PATH[1]}" step="0.1" value="${k.pathValue}" ${busy}></div>
        <div class="landscape-knob"><label for="landscape-hedge">관목 띠 폭 <small>이웃 경계</small></label><output for="landscape-hedge">${k.hedgeValue === 0 ? '없음' : `${k.hedgeValue.toFixed(1)}m`}</output>
          <input id="landscape-hedge" type="range" min="${LANDSCAPE_HEDGE[0]}" max="${LANDSCAPE_HEDGE[1]}" step="0.1" value="${k.hedgeValue}" ${busy}></div>
        <p class="landscape-hint">세 안 모두에 적용하고 다시 검사합니다. 명령창에 "조경 광장 넓게"처럼 써도 됩니다.</p>
      </section>`;
    const proposals = card.proposals.length ? `<section class="landscape-proposals" aria-label="Conductor 조경 제안">
        <h4>Conductor 제안</h4>
        <ul>${card.proposals.map((p) => `<li class="${p.selected ? 'is-selected' : ''}">
          <button type="button" class="landscape-proposal" data-landscape="proposal" data-value="${escape(p.id)}" aria-pressed="${p.selected}" ${busy}>
            <b>${escape(p.title)}</b>${p.short ? ` <i class="landscape-short-text">모자람 ${p.short}</i>` : ''}${p.reason ? `<small>${escape(p.reason)}</small>` : ''}</button>
          <button type="button" class="landscape-drop" data-landscape="drop" data-value="${escape(p.id)}" aria-label="${escape(p.title)} 제안 지우기" title="지우기" ${busy}>×</button></li>`).join('')}</ul>
      </section>` : '';
    const actions = looked
      ? `<button type="button" data-landscape="proposal" data-value="${escape(looked.id)}" ${busy}>돌아가기</button>
         <button type="button" data-landscape="compare" aria-pressed="${Boolean(this.landscapeComparing)}" ${busy}>비교</button>
         <button type="button" class="is-primary" data-landscape="take" data-value="${escape(looked.id)}" title="이 제안의 안·조절값으로 바꾸고 제도판에 놓기" ${busy}>이 안 제도판에 놓기</button>`
      : `<button type="button" data-landscape="shuffle" title="나무 배치와 굽은 길을 다시 섞기" ${busy}>다시 섞기</button>
         <button type="button" data-landscape="compare" aria-pressed="${Boolean(this.landscapeComparing)}" title="세 안과 제안을 나란히 보기" ${busy}>비교</button>
         <button type="button" class="${card.placed ? '' : 'is-primary'}" data-landscape="place" aria-pressed="${card.placed}" ${busy}
          title="${card.placed ? '제도판에서 치우기' : '이 안을 제도판에 놓기: 도구를 닫아도 3D에 남고, 내보내기와 Conductor에 들어감'}">${card.placed ? '제도판에서 치우기' : '이 안 제도판에 놓기'}</button>`;
    el.innerHTML = `<header><h3>${card.title}</h3><button type="button" data-ui="landscape" aria-label="자동 조경 닫기" title="닫기">×</button></header>
      <div class="seg landscape-styles" role="group" aria-label="조경 안">${card.plans.map((p) => `<button type="button" data-landscape="style" data-value="${escape(p.style)}" aria-pressed="${p.selected}" ${busy}>${escape(p.label.split(' · ')[0])}${p.short ? `<i class="landscape-short" aria-label="모자란 항목 ${p.short}개">${p.short}</i>` : ''}</button>`).join('')}</div>
      ${looked ? `<p class="landscape-looking">Conductor 제안을 보는 중: <b>${escape(looked.about)}</b>. 제도판은 놓기 전까지 그대로입니다.</p>` : `<p class="landscape-about">${escape(plan.about)}</p>`}
      <ul class="envelope-lines landscape-checks">${plan.checks.map((c) => `<li class="is-${escape(c.state)}"><details><summary><span class="envelope-state">${escape(c.label)}</span> <b>${escape(c.title)}</b> ${escape(c.value)}${c.need && c.need !== '-' ? ` <small>/ ${escape(c.need)}</small>` : ''}</summary>
        ${c.detail ? `<p>${escape(c.detail)}</p>` : ''}${c.quote ? `<blockquote>${escape(c.quote)}</blockquote>` : ''}${c.source ? `<p class="source">${escape(c.source)}</p>` : ''}</details></li>`).join('')}</ul>
      ${proposals}
      ${looked ? '' : knobs}
      <dl class="envelope-figures">${card.figures.map(([key, v]) => `<dt>${escape(key)}</dt><dd>${escape(v)}</dd>`).join('')}</dl>
      <div class="landscape-region" role="group" aria-label="조경할 영역">
        <span>영역</span>
        <button type="button" data-landscape="whole" aria-pressed="${!card.regionDrawn && !drawing}" ${busy}>대지 전체</button>
        ${drawing
          ? '<button type="button" data-landscape-region="finish">닫기 (Enter)</button><button type="button" data-landscape-region="cancel">취소</button>'
          : `<button type="button" data-landscape="draw" aria-pressed="${card.regionDrawn}" ${busy}>${card.regionDrawn ? '다시 그리기' : '영역 그리기'}</button>`}
      </div>
      ${massForm}
      ${useForm}
      <div class="landscape-actions">${actions}</div>
      ${card.note ? `<p class="envelope-note">${escape(card.note)}</p>` : ''}
      <p class="envelope-note">조례·조경기준으로 그린 참고 배치입니다. 나무는 한 그루를 1주로 셌고, 수종·포장 재료·높낮이는 설계자가 정합니다.</p>`;
  },
  // 비교: the three styles (with the knobs) and the proposals side by side, a small plan over the
  // same rows of figures; "이 안 놓기" places one.
  drawLandscapeCompare() {
    const el = this.ui?.landscapeCompare;
    if (!el) return;
    const cols = this.landscapeOn && this.landscapeComparing ? landscapeCompare(this.landscape) : [];
    el.hidden = !cols.length;
    if (!cols.length) { el.innerHTML = ''; return; }
    const busy = this.landscapeBusy ? 'disabled' : '';
    const need = this.landscape?.requirement;
    const asks = [need?.landscape?.area_m2 ? `조경 ${Math.round(need.landscape.area_m2)}㎡ 이상` : '', need?.planting?.trees ? `교목 ${need.planting.trees}주 이상` : ''].filter(Boolean).join(', ');
    const labels = cols[0].rows.map((r) => r.label);
    const cell = (r) => r ? `${escape(r.value)}${r.state ? ` <span class="is-${r.state[0]}">${r.state[1]}</span>` : ''}${r.diff ? ` <small>${escape(r.diff)}</small>` : ''}` : '';
    el.style.setProperty('--cols', cols.length);
    el.innerHTML = `<header><h3>조경안 비교</h3>${asks ? `<span>기준: ${escape(asks)}</span>` : ''}<button type="button" data-landscape="compare" aria-label="비교 닫기" title="닫기">×</button></header>
      <div class="landscape-compare-grid" role="table" aria-label="조경안 비교">
        <div role="row" class="is-head"><span role="columnheader"></span>${cols.map((c) => `<span role="columnheader" class="${c.kind === 'proposal' ? 'is-proposal' : ''}"><small>${escape(c.head)}</small><b>${escape(c.title)}</b></span>`).join('')}</div>
        <div role="row"><span role="rowheader">평면</span>${cols.map((c) => `<span role="cell" class="landscape-mini${c.placed ? ' is-placed' : ''}">${landscapeMiniPlan(c.plan, { width: 160, height: 160, label: `${c.title} 평면` })}</span>`).join('')}</div>
        ${labels.map((label, i) => `<div role="row"><span role="rowheader">${escape(label)}</span>${cols.map((c) => `<span role="cell">${cell(c.rows[i])}</span>`).join('')}</div>`).join('')}
        <div role="row"><span role="rowheader"></span>${cols.map((c) => `<span role="cell">${c.placed
          ? '<button type="button" disabled>놓여 있음</button>'
          : `<button type="button" class="${c.kind === 'proposal' ? 'is-primary' : ''}" data-landscape="take" data-value="${escape(c.key)}" ${busy}>이 안 놓기</button>`}</span>`).join('')}</div>
      </div>
      <p class="envelope-note">숫자는 규칙으로 그린 배치를 잰 값입니다. 괄호는 ${this.landscape?.settings?.placed ? '놓인 안' : '보고 있는 안'}과의 차이입니다.</p>`;
  },
};
