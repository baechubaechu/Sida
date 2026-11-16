// Sections (단면, 2026-11-11 지훈): the 단면 tool draws a line on the table; the line becomes a
// section paper whose drawing follows the scheme and the surroundings; in 3D the table can be cut
// along it (everything on the near side taken away, the cut faces filled). The cut and the drawing
// come from section-model.js, the same rules as the server's file (sida/board_section.py).
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { paperName, groundAt, fmt } from './board-model.js';
import {
  sectionCut, sectionSolids, sectionSvg, sectionFigures, sectionFrame, nearEnd, draggedLine, nextSectionName,
  SECTION_DEFAULTS, MIN_SECTION_LENGTH,
} from './section-model.js';

const NO_PLANES = [];
const END_PX = 12; // how near (screen px) a press must be to a section line's end to drag it
const CAP = { ground: 0x8a929b, building: 0x6d7680 };

export const sectionMethods = {
  // ------------------------------------------------------------------ what a section cuts
  sectionInput() {
    const scheme = this.papers.find((p) => p.id === this.active && p.kind === 'mass') || null;
    const around = this.aroundOn ? this.around : null;
    return {
      scheme, frame: this.site?.plan?.frame || null, terrain: around?.terrain || null,
      buildings: around?.buildings || [], hiddenParts: this.aroundPartsHidden || new Set(),
    };
  },
  // Changes when anything a section drawing shows changes (its paper's own fields aside).
  sectionKey() {
    const i = this.sectionInput();
    return JSON.stringify([i.scheme?.id, i.scheme?.blocks, i.scheme?.floor_height, i.frame, Boolean(i.terrain),
      this.around?.radius, this.around?.buildings?.length, [...i.hiddenParts].sort()]);
  },
  sectionResult(p) {
    const key = JSON.stringify([this.sectionKey(), p.line, p.flip, p.depth]);
    this.sectionMemo = this.sectionMemo || new Map();
    const kept = this.sectionMemo.get(p.id);
    if (kept?.key === key) return kept.result;
    const i = this.sectionInput();
    const result = p.line ? sectionCut(p.line, sectionSolids(i), i.terrain, { flip: Boolean(p.flip), depth: p.depth ?? SECTION_DEFAULTS.depth }) : null;
    this.sectionMemo.set(p.id, { key, result });
    return result;
  },
  // The drawing and its numbers, on the paper and (larger) in the 속성 panel.
  sectionBody(p, large = false) {
    const result = this.sectionResult(p);
    if (!result) return '<p class="muted">단면선이 없습니다.</p>';
    const scheme = this.sectionInput().scheme;
    const notes = [
      scheme ? `${paperName(scheme)} 기준` : '세운 매스안 없음',
      this.aroundOn && this.around ? '' : '주변 3D를 켜면 지형과 주변 건물이 들어갑니다',
    ].filter(Boolean);
    return `<div class="section-sheet${large ? ' is-large' : ''}">${sectionSvg(result, { name: p.title || 'A', heights: large })}</div>
      <p class="figure">${escape(sectionFigures(result).join(' · '))}</p>
      <p class="source">${escape(notes.join(' · '))}${large ? '' : ` · 1:${escape(String(p.scale ?? 500))}`}</p>`;
  },

  // ------------------------------------------------------------------ the lines on the table
  // Each section's line on the ground, the arrows at its ends toward the side it looks at, its
  // names, the ends of a selected one as handles; then the papers' drawings and the 3D cut again.
  drawSections() {
    if (!this.gl) return;
    const g = this.gl;
    if (!g.sections) {
      g.sections = new THREE.Group();
      g.cuts = new THREE.Group();
      g.scene.add(g.sections, g.cuts);
    }
    g.sections.traverse((o) => { o.geometry?.dispose(); });
    g.sections.clear();
    for (const tag of this.sectionTags || []) g.cssScene.remove(tag);
    this.sectionTags = [];
    const papers = this.papers.filter((p) => p.kind === 'section' && p.line);
    if (this.cutId && !papers.some((p) => p.id === this.cutId)) this.cutId = '';
    const terrain = this.aroundOn ? this.around?.terrain : null;
    const z = (x, y) => (terrain ? groundAt(terrain, x, y) : 0) + 0.3;
    for (const p of papers) {
      if (this.layerHidden(p)) continue;
      const f = sectionFrame(p.line, Boolean(p.flip));
      if (!f) continue;
      const on = this.selected.includes(p.id) || this.cutId === p.id;
      const color = new THREE.Color(on ? this.colors.pick : this.colors.ghost);
      const [[x0, y0]] = p.line;
      const steps = Math.max(1, Math.ceil(f.length / 2));
      const pts = Array.from({ length: steps + 1 }, (_, k) => {
        const s = (f.length * k) / steps;
        const x = x0 + f.d[0] * s, y = y0 + f.d[1] * s;
        return new THREE.Vector3(x, y, z(x, y));
      });
      const line = new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineDashedMaterial({ color, dashSize: 4, gapSize: 1.5, depthTest: false }));
      line.computeLineDistances();
      line.renderOrder = 5;
      g.sections.add(line);
      const size = Math.min(8, Math.max(2, f.length * 0.05));
      p.line.forEach(([x, y], k) => {
        // an arrow toward the looked-at side, and the name a little past the end
        const tip = [x + f.n[0] * size * 1.6, y + f.n[1] * size * 1.6];
        const tri = new THREE.Shape([new THREE.Vector2(x + f.d[0] * size * 0.6, y + f.d[1] * size * 0.6), new THREE.Vector2(...tip),
          new THREE.Vector2(x - f.d[0] * size * 0.6, y - f.d[1] * size * 0.6)]);
        const arrow = new THREE.Mesh(new THREE.ShapeGeometry(tri), new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide, depthTest: false }));
        arrow.position.z = z(x, y);
        arrow.renderOrder = 5;
        g.sections.add(arrow);
        if (on && this.selected.includes(p.id)) {
          const round = Array.from({ length: 20 }, (_, i) => new THREE.Vector3(Math.cos((i * Math.PI) / 10) * size * 0.45, Math.sin((i * Math.PI) / 10) * size * 0.45, 0));
          const ring = new THREE.LineLoop(new THREE.BufferGeometry().setFromPoints(round), new THREE.LineBasicMaterial({ color, depthTest: false }));
          ring.position.set(x, y, z(x, y) + 0.05);
          ring.renderOrder = 6;
          g.sections.add(ring);
        }
        const tag = document.createElement('div');
        tag.className = `section-tag${on ? ' is-on' : ''}`;
        tag.textContent = k === 0 ? (p.title || 'A') : `${p.title || 'A'}′`;
        const obj = new THREE.CSS3DObject(tag);
        const back = k === 0 ? -1 : 1;
        obj.position.set(x + f.d[0] * back * size * 1.4, y + f.d[1] * back * size * 1.4, z(x, y) + 0.1);
        obj.scale.setScalar(0.1 * Math.max(1, size / 4));
        g.cssScene.add(obj);
        this.sectionTags.push(obj);
      });
    }
    for (const p of papers) this.drawPaper(p);
    this.drawCut();
    this.invalidate();
  },

  // ------------------------------------------------------------------ the 3D cut
  // The plane the table is cut along (the near side taken away) and the cut faces, filled.
  drawCut() {
    const g = this.gl;
    if (!g?.cuts) return;
    g.cuts.traverse((o) => { o.geometry?.dispose(); o.material?.dispose?.(); });
    g.cuts.clear();
    this.cutPlane = null;
    const p = this.papers.find((x) => x.id === this.cutId && x.kind === 'section');
    const f = p && sectionFrame(p.line, Boolean(p.flip));
    if (!f) return;
    const [x0, y0] = p.line[0];
    this.cutPlane = new THREE.Plane(new THREE.Vector3(f.n[0], f.n[1], 0), -(f.n[0] * x0 + f.n[1] * y0));
    // the cut runs across the whole range, past the line's ends
    const i = this.sectionInput();
    const reach = i.terrain ? Math.abs(i.terrain.min) * 1.5 : 400;
    const mid = -(f.d[0] * x0 + f.d[1] * y0); // s of the point nearest the site's middle
    const result = sectionCut(p.line, sectionSolids(i), i.terrain, { flip: Boolean(p.flip), depth: 0, from: mid - reach, to: mid + reach });
    // a point (s along the line, h up) of the cut, just on the kept side of the plane
    const at = (s, h, lift = 0) => new THREE.Vector3(x0 + f.d[0] * s + f.n[0] * (0.03 + lift), y0 + f.d[1] * s + f.n[1] * (0.03 + lift), h);
    const face = (points, color) => {
      const geom = new THREE.ShapeGeometry(new THREE.Shape(points.map(([s, h]) => new THREE.Vector2(s, h))));
      const pos = geom.getAttribute('position');
      for (let k = 0; k < pos.count; k += 1) pos.setXYZ(k, ...at(pos.getX(k), pos.getY(k)).toArray());
      geom.computeBoundingSphere();
      g.cuts.add(new THREE.Mesh(geom, new THREE.MeshBasicMaterial({ color, side: THREE.DoubleSide })));
    };
    const zs = result.profile.flat().map(([, h]) => h);
    const low = Math.min(0, ...zs) - 6;
    for (const run of result.profile) face([[run[0][0], low], ...run, [run[run.length - 1][0], low]], CAP.ground);
    const floors = [];
    for (const c of result.cut) {
      face([[c.a, c.base], [c.b, c.base], [c.b, c.top], [c.a, c.top]], c.kind === 'mass' ? this.colors.ink : CAP.building);
      if (c.kind !== 'mass') continue;
      for (let k = 1; k < (c.floors || 0); k += 1) {
        const h = c.base + k * c.storey;
        floors.push(at(c.a, h, -0.02), at(c.b, h, -0.02)); // between the cut face and the plane
      }
    }
    if (floors.length) g.cuts.add(new THREE.LineSegments(new THREE.BufferGeometry().setFromPoints(floors), new THREE.LineBasicMaterial({ color: 0xffffff })));
  },
  // Each frame (render): the cut only in 3D, and the lines and faces rising with the masses.
  applyCut(fold, rise) {
    const g = this.gl;
    if (!g?.sections) return;
    g.sections.scale.z = rise;
    g.cuts.scale.z = rise;
    const on = Boolean(fold && this.cutPlane);
    g.renderer.clippingPlanes = on ? [this.cutPlane] : NO_PLANES;
    g.cuts.visible = on;
    if (g.sun) g.sun.castShadow = !on; // the shadow map is not cut: no shadows of what was taken away
  },
  // Cut the 3D view along a section (or stop cutting it).
  toggleCut(id) {
    this.cutId = this.cutId === id ? '' : id;
    this.drawSections();
    if (this.cutId) {
      const p = this.find(id);
      // stand on the side taken away and look at the cut, across the middle of the line
      const f = sectionFrame(p.line, Boolean(p.flip));
      const [[x0, y0], [x1, y1]] = p.line;
      if (this.eye) this.exitEye();
      this.animateTo({ x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: 0, span: Math.max(60, f.length * 1.3), turn: (Math.atan2(f.n[0], f.n[1]) * 180) / Math.PI, tilt: 62 }, 600);
      this.say(`${paperName(p)}에서 3D를 잘라 봅니다. 화살표 쪽이 남습니다. 같은 버튼으로 끕니다.`);
    } else {
      this.say('3D 자르기를 껐습니다.');
    }
    if (this.detailId) this.drawDetail();
    this.hooks.pdfPages?.(); // the 속성 panel's buttons follow
  },

  // ------------------------------------------------------------------ drawing and moving a line
  sectionGesture(e, g0) {
    if (!g0) { this.say('단면선은 땅 위에서 끌어 긋습니다.'); return null; }
    return { kind: 'section', a: g0, line: null, x: e.clientX, y: e.clientY };
  },
  // A press near an end of a selected section's line: drag that end.
  sectionEndAt(clientX, clientY) {
    if (!this.gl) return null;
    const r = this.root.getBoundingClientRect();
    for (const p of this.papers) {
      if (p.kind !== 'section' || !p.line || !this.selected.includes(p.id) || this.layerLocked(p)) continue;
      const k = nearEnd(p.line.map(([x, y]) => {
        const v = new THREE.Vector3(x, y, 0).project(this.gl.camera);
        return [((v.x + 1) / 2) * r.width + r.left, ((1 - v.y) / 2) * r.height + r.top];
      }), { x: clientX, y: clientY }, END_PX);
      if (k >= 0) return { kind: 'section-end', id: p.id, k, before: p.line.map((pt) => [...pt]), moved: false };
    }
    return null;
  },
  sectionMove(g, e) {
    const at = this.ground(e.clientX, e.clientY);
    if (!at) return;
    if (g.kind === 'section') {
      g.line = draggedLine(g.a, at, e.shiftKey);
      const [[x0, y0], [x1, y1]] = g.line;
      this.drawDraft([[x0, y0, 0], [x1, y1, 0]], false);
      this.say(`단면선 ${fmt(Math.hypot(x1 - x0, y1 - y0), 1)} m${e.shiftKey ? ' · 15° 단위' : ''}`);
      return;
    }
    const p = this.papers.find((x) => x.id === g.id);
    if (!p) return;
    const other = g.before[1 - g.k];
    const moved = draggedLine({ x: other[0], y: other[1] }, at, e.shiftKey)[1];
    if (Math.hypot(moved[0] - other[0], moved[1] - other[1]) < 1) return;
    p.line = g.k === 0 ? [moved, other] : [other, moved];
    g.moved = true;
    this.say(`단면선 ${fmt(Math.hypot(moved[0] - other[0], moved[1] - other[1]), 1)} m`);
    this.drawSections();
  },
  sectionUp(g, cancelled) {
    if (g.kind === 'section') {
      this.gl.draft.clear();
      this.invalidate();
      const line = g.line;
      if (cancelled || !line) return;
      if (Math.hypot(line[1][0] - line[0][0], line[1][1] - line[0][1]) < MIN_SECTION_LENGTH) {
        this.say(`단면선은 ${MIN_SECTION_LENGTH}m 넘게 끌어 그어 주세요.`);
        return;
      }
      const title = nextSectionName(this.papers);
      this.setTool('select');
      this.hooks.add({ kind: 'section', title, line, ...SECTION_DEFAULTS }).then((done) => {
        if (!done?.paper) return;
        this.record([{ op: 'add', paper: done.paper }]);
        this.select([done.paper.id]);
        this.say(`단면 ${title}–${title}′을(를) 만들었습니다. 종이에 단면도가 그려지고, 속성에서 3D 자르기·방향·내려받기를 고릅니다.`);
      });
      return;
    }
    const p = this.papers.find((x) => x.id === g.id);
    if (!p) return;
    if (cancelled || !g.moved) {
      p.line = g.before;
      this.drawSections();
      return;
    }
    this.record([{ op: 'update', id: p.id, before: { line: g.before }, after: { line: p.line } }]);
    this.save(p.id, { line: p.line });
    this.drawSections();
  },

  // ------------------------------------------------------------------ the paper's buttons
  sectionActions(p, on) {
    if (p.kind !== 'section' || !this.papers.some((x) => x.id === p.id)) return '';
    return `<button type="button" ${on('section-cut')} aria-pressed="${this.cutId === p.id}">${this.cutId === p.id ? '3D 자르기 끄기' : '3D에서 자르기'}</button>
      <button type="button" ${on('section-flip')}>보는 방향 뒤집기</button>
      <span class="detail-files" role="group" aria-label="단면도 내려받기">${['svg', 'pdf', 'dxf'].map((fmt2) => `<button type="button" ${on(`section-${fmt2}`)}>${fmt2.toUpperCase()}</button>`).join('')}</span>`;
  },
  // A section paper's button (속성 panel or detail window). True when it was one.
  sectionAction(action, p) {
    if (p?.kind !== 'section') return false;
    if (action === 'section-cut') this.toggleCut(p.id);
    else if (action === 'section-flip') this.editPapers([{ id: p.id, changes: { flip: !p.flip } }]);
    else if (['section-svg', 'section-pdf', 'section-dxf'].includes(action)) this.hooks.sectionFile?.(p.id, action.slice(8), p.title || 'A');
    else return false;
    return true;
  },
};
