// 법규 볼륨: the room the 정북일조 rule and the ratios leave on the site (GET .../site/envelope),
// drawn as translucent floors over the site, a card with its rule lines (each with the 원문) and
// the reference schemes, which go on the table as mass schemes of their own. Blocks of the scheme
// standing in 3D that rise above the envelope are marked.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { envelopeCard, envelopeOver, envelopeSchemePaper, viewFor, freeSpot, PAPER_SIZE } from './board-model.js';

export const envelopeMethods = {
  // Show or hide the envelope; the first time (and after the site changed) it is asked for.
  async toggleEnvelope() {
    if (this.envelopeBusy) return;
    if (this.envelopeOn) {
      this.envelopeOn = false;
      this.drawEnvelope(); this.drawMasses(); this.drawControls();
      return;
    }
    if (!this.site?.plan) { this.say('먼저 대지를 조회하세요. 대지 경계가 있어야 법규 볼륨을 계산할 수 있습니다.'); return; }
    if (!this.envelope && this.hooks.envelope) {
      const request = Symbol();
      this.envelopeRequest = request;
      this.envelopeBusy = true;
      this.drawControls();
      try {
        const envelope = await this.hooks.envelope();
        if (request !== this.envelopeRequest) return;
        this.envelope = envelope;
      } catch (error) {
        if (request !== this.envelopeRequest) return;
        this.say(`법규 볼륨을 계산하지 못했습니다. ${error.message}`);
      }
      this.envelopeBusy = false;
    }
    this.envelopeOn = Boolean(this.envelope);
    this.drawEnvelope(); this.drawMasses(); this.drawControls();
    // Lean the table (when flat) and step back so the whole envelope is in view.
    if (this.envelopeOn && this.envelope.levels?.length) {
      const tall = this.envelope.levels[this.envelope.levels.length - 1].z;
      this.animateTo({ ...(this.view.tilt ? {} : viewFor('3d', this.view) || {}), span: Math.max(this.view.span, tall * 1.8) });
    }
  },
  // The site changed: what was worked out for the old one goes.
  forgetEnvelope() {
    this.envelopeRequest = null;
    this.envelopeBusy = false;
    this.envelopeOn = false;
    this.envelope = null;
    this.drawEnvelope();
  },
  // Each level of the envelope as walls from the level below up to it and a lid, see-through, with
  // its outline; the group rises with the masses (render()).
  drawEnvelope() {
    this.drawEnvelopeCard();
    if (!this.gl) return;
    const group = this.gl.envelope;
    group.traverse((o) => o.geometry?.dispose());
    group.clear();
    const data = this.envelopeOn ? this.envelope : null;
    if (!data?.levels?.length) { this.invalidate(); return; }
    const tone = new THREE.Color(this.colors.ghost);
    const fill = new THREE.MeshBasicMaterial({ color: tone, transparent: true, opacity: 0.05, side: THREE.DoubleSide, depthWrite: false });
    const lid = new THREE.MeshBasicMaterial({ color: tone, transparent: true, opacity: 0.07, side: THREE.DoubleSide, depthWrite: false });
    const ink = new THREE.LineBasicMaterial({ color: tone, transparent: true, opacity: 0.45 });
    const frame = this.site?.plan?.frame || { x: 0, y: 0, angle: 0 };
    const base = this.blockBase(frame, { u: 0, v: 0, w: 0, d: 0 }); // the ground under the site's middle
    let below = 0;
    for (const level of data.levels) {
      const z = base + level.z;
      for (const ring of level.rings) {
        const walls = [];
        ring.forEach(([x1, y1], k) => {
          const [x2, y2] = ring[(k + 1) % ring.length];
          const a = new THREE.Vector3(x1, y1, base + below), b = new THREE.Vector3(x2, y2, base + below);
          const at = new THREE.Vector3(x1, y1, z), bt = new THREE.Vector3(x2, y2, z);
          walls.push(a, b, bt, a, bt, at);
        });
        group.add(new THREE.Mesh(new THREE.BufferGeometry().setFromPoints(walls), fill));
        const top = new THREE.Mesh(new THREE.ShapeGeometry(new THREE.Shape(ring.map(([x, y]) => new THREE.Vector2(x, y)))), lid);
        top.position.z = z;
        group.add(top);
        group.add(new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(ring.map(([x, y]) => new THREE.Vector3(x, y, z + 0.02))), ink));
      }
      below = level.z;
    }
    this.invalidate();
  },
  // The blocks of a mass scheme that pass the envelope: a Set of their indices (empty while it is off).
  envelopeOverSet(paper) {
    if (!this.envelopeOn || paper?.kind !== 'mass') return new Set();
    return new Set(envelopeOver(this.envelope, paper).map((o) => o.index));
  },
  drawEnvelopeCard() {
    const el = this.ui?.envelope;
    if (!el) return;
    const card = this.envelopeOn ? envelopeCard(this.envelope) : null;
    el.hidden = !card;
    if (!card) { el.innerHTML = ''; return; }
    const active = this.papers.find((p) => p.id === this.active && p.kind === 'mass');
    const over = active ? envelopeOver(this.envelope, active) : [];
    const overText = !active ? '' : over.length
      ? `<p class="envelope-over" role="status">${escape(active.title || '매스안')}: ${over.map((o) => `${o.index + 1}동 ${o.over}m`).join(', ')} 넘음</p>`
      : (this.envelope.grid ? `<p class="envelope-fit" role="status">${escape(active.title || '매스안')}: 모든 동이 정북일조 높이 안</p>` : '');
    el.innerHTML = `<header><h3>${card.title}</h3><button type="button" data-ui="envelope" aria-label="법규 볼륨 닫기" title="닫기">×</button></header>
      <dl class="envelope-figures">${card.figures.map(([k, v]) => `<dt>${escape(k)}</dt><dd>${escape(v)}</dd>`).join('')}</dl>
      ${overText}
      ${card.schemes.length ? `<div class="envelope-schemes"><b>참고 매스</b>${card.schemes.map((s) => `<div class="envelope-scheme"><span><strong>${escape(s.name)}</strong> <small>${escape(s.text)}</small></span>
        <button type="button" data-envelope-place="${s.index}" title="이 참고 매스를 새 매스안으로 제도판에 놓기">매스안으로 놓기</button></div>`).join('')}</div>` : ''}
      <ul class="envelope-lines">${card.lines.map((l) => `<li class="is-${escape(l.status)}"><details><summary><span class="envelope-state">${escape(l.label)}</span> <b>${escape(l.title)}</b> ${escape(l.value)}</summary>
        ${l.detail ? `<p>${escape(l.detail)}</p>` : ''}${l.quote ? `<blockquote>${escape(l.quote)}</blockquote>` : ''}${l.source ? `<p class="source">${escape(l.source)}</p>` : ''}</details></li>`).join('')}</ul>
      <p class="envelope-note">공공 자료와 조문으로 계산한 참고용입니다. 대지 안의 공지·건축선·고도지구 등은 반영하지 않았으니 설계에 앞서 확인하세요.</p>`;
  },
  // A reference scheme put on the table as a new mass scheme beside the site, standing in 3D.
  async placeEnvelopeScheme(index) {
    const scheme = this.envelope?.schemes?.[Number(index)];
    if (!scheme) return;
    const [w, h] = PAPER_SIZE.mass;
    const done = await this.hooks.add({ ...envelopeSchemePaper(scheme), w, h, ...freeSpot(this.papers, this.bounds, w, h) });
    if (!done?.paper) return;
    this.record([{ op: 'add', paper: done.paper }]);
    this.showScheme(done.paper.id);
    this.say(`"${done.paper.title}"을 매스안으로 놓았습니다.`);
  },
};
