// 자동 조경 (2026-11-20 지훈 "영역 지정하면 조경 알아서 해주는 그런거"): three layouts drawn by rule in
// the region picked (GET .../landscape, sida/experts/landscape/): 정형·자연형·광장형, each with how
// it stands against the 조경·교목·공개 공지 the rules ask (each with the 원문). The designer picks one,
// draws a region of their own (clicks on the ground; Enter or a double click closes it, Esc
// cancels, Backspace takes the last point back), shuffles the trees and places the plan on the
// table: a placed plan stays in 3D with the tool closed, goes into the CAD/Rhino export and is
// told to the Conductor. The ground lies flat on the table; the trees rise with the masses.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { LANDSCAPE_KINDS, LANDSCAPE_TREE_COLORS, landscapeCard, landscapeShown, landscapeTreeGroups, landscapeRing, treeTriangles } from './board-model.js';

const REFRESH_MS = 700; // after a mass edit, the plans are worked out again this long after the last one

export const landscapeMethods = {
  // Open or close the card; the first time (and after the site changed) the plans are asked for.
  async toggleLandscape() {
    if (this.landscapeBusy) return;
    if (this.landscapeOn) {
      this.landscapeOn = false;
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
  // Keep a change of the card (style, seed, use, mass, region, placed) and draw the plans again.
  async changeLandscape(changes) {
    await this.fetchLandscape(changes);
    this.drawLandscape();
  },
  landscapeAction(action, value) {
    const s = this.landscape?.settings || {};
    switch (action) {
      case 'style': this.changeLandscape({ style: value }); break;
      case 'shuffle': this.changeLandscape({ seed: (s.seed % 9999) + 1 }); break;
      case 'place': this.changeLandscape({ placed: !s.placed }); break;
      case 'whole': this.changeLandscape({ region: null }); break;
      case 'draw': this.startLandscapeRegion(); break;
      default: break;
    }
  },
  landscapeSelect(target) {
    if (target.id === 'landscape-use') this.changeLandscape({ use: target.value || null });
    if (target.id === 'landscape-mass') this.changeLandscape({ mass: target.value || null });
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
    const plan = (this.landscapeOn || data?.settings?.placed) ? landscapeShown(data) : null;
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
    const card = this.landscapeOn ? landscapeCard(this.landscape) : null;
    el.hidden = !card;
    if (!card) { el.innerHTML = ''; return; }
    const plan = card.plans.find((p) => p.selected) || card.plans[0];
    const drawing = Boolean(this.landscapeDrawing);
    const busy = this.landscapeBusy ? 'disabled' : '';
    const massForm = card.masses.length > 1 ? `<label class="landscape-field"><span>매스안</span>
        <select id="landscape-mass" ${busy}>${card.masses.map((m) => `<option value="${escape(m.id)}"${m.id === card.mass ? ' selected' : ''}>${escape(m.title || m.id)}</option>`).join('')}</select></label>` : '';
    const useForm = `<label class="landscape-field"><span>건물 용도 <small>공개 공지</small></span>
        <select id="landscape-use" ${busy}><option value="">고르기</option>${card.uses.map((u) => `<option value="${escape(u.key)}"${u.selected ? ' selected' : ''}>${escape(u.label)}</option>`).join('')}</select></label>`;
    el.innerHTML = `<header><h3>${card.title}</h3><button type="button" data-ui="landscape" aria-label="자동 조경 닫기" title="닫기">×</button></header>
      <div class="seg landscape-styles" role="group" aria-label="조경 안">${card.plans.map((p) => `<button type="button" data-landscape="style" data-value="${escape(p.style)}" aria-pressed="${p.selected}" ${busy}>${escape(p.label.split(' · ')[0])}${p.short ? `<i class="landscape-short" aria-label="모자란 항목 ${p.short}개">${p.short}</i>` : ''}</button>`).join('')}</div>
      <p class="landscape-about">${escape(plan.about)}</p>
      <ul class="envelope-lines landscape-checks">${plan.checks.map((c) => `<li class="is-${escape(c.state)}"><details><summary><span class="envelope-state">${escape(c.label)}</span> <b>${escape(c.title)}</b> ${escape(c.value)}${c.need && c.need !== '-' ? ` <small>/ ${escape(c.need)}</small>` : ''}</summary>
        ${c.detail ? `<p>${escape(c.detail)}</p>` : ''}${c.quote ? `<blockquote>${escape(c.quote)}</blockquote>` : ''}${c.source ? `<p class="source">${escape(c.source)}</p>` : ''}</details></li>`).join('')}</ul>
      <dl class="envelope-figures">${card.figures.map(([k, v]) => `<dt>${escape(k)}</dt><dd>${escape(v)}</dd>`).join('')}</dl>
      <div class="landscape-region" role="group" aria-label="조경할 영역">
        <span>영역</span>
        <button type="button" data-landscape="whole" aria-pressed="${!card.regionDrawn && !drawing}" ${busy}>대지 전체</button>
        ${drawing
          ? '<button type="button" data-landscape-region="finish">닫기 (Enter)</button><button type="button" data-landscape-region="cancel">취소</button>'
          : `<button type="button" data-landscape="draw" aria-pressed="${card.regionDrawn}" ${busy}>${card.regionDrawn ? '다시 그리기' : '영역 그리기'}</button>`}
      </div>
      ${massForm}
      ${useForm}
      <div class="landscape-actions">
        <button type="button" data-landscape="shuffle" title="나무 배치와 굽은 길을 다시 섞기" ${busy}>다시 섞기</button>
        <button type="button" class="${card.placed ? '' : 'is-primary'}" data-landscape="place" aria-pressed="${card.placed}" ${busy}
          title="${card.placed ? '제도판에서 치우기' : '이 안을 제도판에 놓기: 도구를 닫아도 3D에 남고, 내보내기와 Conductor에 들어감'}">${card.placed ? '제도판에서 치우기' : '이 안 제도판에 놓기'}</button>
      </div>
      ${card.note ? `<p class="envelope-note">${escape(card.note)}</p>` : ''}
      <p class="envelope-note">조례·조경기준으로 그린 참고 배치입니다. 나무는 한 그루를 1주로 셌고, 수종·포장 재료·높낮이는 설계자가 정합니다.</p>`;
  },
};
