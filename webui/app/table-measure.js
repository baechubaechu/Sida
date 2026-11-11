// The tape (줄자) and the radius tool (반경): two clicks each (2026-11-10 지훈, as in Naver Map).
// The first click sets the start (the radius tool's centre), the line or circle then follows the
// pointer with its length, and the second click keeps it. Both snap like the tape always has
// (tapePoint). The radius command also draws circles about the site's middle ("radius 250 500").
// What is measured is only shown, never saved; Esc while measuring drops the open one, and Esc
// again or another tool clears the rest.
// Methods of DraftingTable (table.js adds them to its prototype). The steps are board-model.js's.

import * as THREE from './vendor/three.js';
import { emptyMeasure, measureClick, measureLength, siteCircles, circlePoints, riseFor } from './board-model.js';
import { distanceLabel } from './model.js';

export const measureMethods = {
  measureState() {
    if (!this.measure) this.measure = emptyMeasure();
    return this.measure;
  },
  // The group the lines and circles are drawn in, and the labels laid over the scene.
  measureParts() {
    if (!this.gl) return null;
    if (!this.gl.measure) {
      const group = new THREE.Group();
      group.renderOrder = 10;
      this.gl.scene.add(group);
      const labels = document.createElement('div');
      labels.className = 'measure-labels';
      labels.setAttribute('aria-hidden', 'true');
      this.root.insertBefore(labels, this.snapEl);
      const css = getComputedStyle(document.documentElement);
      this.gl.measure = { group, labels, color: css.getPropertyValue('--measure').trim() || '#126b89' };
    }
    return this.gl.measure;
  },

  // A left press with the tape or the radius tool (no drag: the press is the click).
  measureDown(e) {
    const p = this.tapePoint(e);
    if (!p) { this.say('땅이나 매스 위를 찍어 주세요.'); return; }
    const kind = this.tool;
    const out = measureClick(this.measureState(), kind, p);
    this.measure = out.state;
    if (!out.made && out.state.start === p) {
      this.say(kind === 'radius' ? '중심을 찍었습니다. 끝점을 찍으면 원이 생깁니다. Esc는 취소합니다.' : '첫 점을 찍었습니다. 두 번째 점을 찍으세요. Esc는 취소합니다.');
      this.measurePreview = p;
    } else if (!out.made) {
      this.say(kind === 'radius' ? '끝점을 중심에서 떨어진 곳에 찍으세요.' : '두 번째 점을 첫 점과 다른 곳에 찍으세요.');
    } else {
      this.measurePreview = null;
      this.say(kind === 'radius'
        ? `반경 ${distanceLabel(out.made.r)} 원을 남겼습니다. 다시 찍으면 하나 더 그립니다. Esc는 모두 지웁니다.`
        : `거리 ${distanceLabel(out.made.length)}`);
    }
    this.drawMeasure();
  },
  // The pointer moving with the tape or the radius tool: the snap, and the open line or circle.
  measureMove(e) {
    const p = this.tapePoint(e);
    const start = this.measure?.start;
    if (!start || !p) return;
    this.measurePreview = p;
    const length = measureLength(this.tool, start, p);
    this.say(`${this.tool === 'radius' ? '반경' : '거리'} ${distanceLabel(length)}${this.snapEl.hidden ? '' : ' · 스냅'}`);
    this.drawMeasure();
  },
  // Esc: drop the line or circle being drawn, or else clear what was measured (the tool stays).
  // False when there was nothing, so Esc goes on to its usual work.
  cancelMeasure() {
    const m = this.measure;
    if (m?.start) {
      this.measure = { ...m, start: null };
      this.measurePreview = null;
      this.say('그리던 것을 취소했습니다. Esc를 한 번 더 누르면 모두 지웁니다.');
    } else if (m?.circles.length || m?.line) {
      this.measure = null;
      this.say('재기 표시를 지웠습니다.');
    } else return false;
    this.drawMeasure();
    return true;
  },
  clearMeasure() {
    if (!this.measure) return;
    this.measure = null;
    this.measurePreview = null;
    this.drawMeasure();
  },
  // The radius command's answer: circles of these radii (metres) about the middle of the site,
  // with the view zoomed out to hold the largest.
  circlesAtSite(radii) {
    if (!radii?.length) return;
    if (this.tool !== 'radius') this.setTool('radius');
    const centre = this.home; // the middle of the site's bounds
    this.measure = siteCircles(this.measureState(), centre, radii);
    this.measurePreview = null;
    this.drawMeasure();
    const span = 2.4 * Math.max(...radii);
    this.animateTo({ x: centre.x, y: centre.y, span: Math.max(this.view.span, span) });
    this.say(`대지 가운데에서 반경 ${radii.map(distanceLabel).join(' · ')} 원을 그렸습니다. Esc는 모두 지웁니다.`);
  },

  // Draw what is measured: kept circles (with their radius line), the kept tape line, and the
  // open one following the pointer. The labels are placed on every frame (placeMeasure).
  drawMeasure() {
    const parts = this.measureParts();
    if (!parts) return;
    const { group, color } = parts;
    for (const child of [...group.children]) { child.geometry?.dispose(); child.material?.dispose(); }
    group.clear();
    const m = this.measure || emptyMeasure();
    const line = (points, opts = {}) => {
      const geom = new THREE.BufferGeometry().setFromPoints(points.map(([x, y, z]) => new THREE.Vector3(x, y, z + 0.3)));
      const material = opts.dashed
        ? new THREE.LineDashedMaterial({ color, dashSize: opts.dash, gapSize: opts.dash / 2, depthTest: false, transparent: true })
        : new THREE.LineBasicMaterial({ color, depthTest: false, transparent: true });
      const obj = new (opts.closed ? THREE.LineLoop : THREE.Line)(geom, material);
      if (opts.dashed) obj.computeLineDistances();
      obj.renderOrder = 10;
      group.add(obj);
    };
    const circle = (c, r, b, live) => {
      const shape = new THREE.Shape(circlePoints({ x: 0, y: 0 }, r).map(([x, y]) => new THREE.Vector2(x, y)));
      const fill = new THREE.Mesh(new THREE.ShapeGeometry(shape), new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.07, depthWrite: false }));
      fill.position.set(c.x, c.y, (c.z || 0) + 0.25);
      group.add(fill);
      line(circlePoints(c, r), live ? { closed: true } : { closed: true, dashed: true, dash: Math.max(0.6, r / 40) });
      line([[c.x, c.y, c.z || 0], [b.x, b.y, c.z || 0]]);
    };
    for (const k of m.circles) circle(k.c, k.r, k.b, false);
    const p = this.measurePreview;
    if (m.start && p && this.tool === 'radius') {
      const r = measureLength('radius', m.start, p);
      if (r > 0.01) circle(m.start, r, p, true);
    }
    const tape = m.start && p && this.tool === 'tape' ? { a: m.start, b: p } : m.line;
    if (tape) line([[tape.a.x, tape.a.y, tape.a.z || 0], [tape.b.x, tape.b.y, tape.b.z || 0]]);
    this.invalidate();
  },

  // The labels over the scene ("반경 250 m", "12.4 m"), where the camera sees their points.
  placeMeasure() {
    const parts = this.gl?.measure;
    if (!parts) return;
    const rise = this.eye ? 1 : riseFor(this.view.tilt);
    parts.group.scale.z = rise;
    const m = this.measure;
    const p = this.measurePreview;
    const items = [];
    if (m) {
      for (const k of m.circles) items.push({ at: k.b, z: k.c.z, text: `반경 ${distanceLabel(k.r)}` });
      if (m.start && p) {
        const length = measureLength(this.tool, m.start, p);
        if (length > 0.01) items.push({ at: p, z: this.tool === 'radius' ? m.start.z : p.z, text: `${this.tool === 'radius' ? '반경 ' : ''}${distanceLabel(length)}`, live: true });
      } else if (m.line && this.tool === 'tape') {
        const { a, b } = m.line;
        items.push({ at: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }, z: ((a.z || 0) + (b.z || 0)) / 2, text: distanceLabel(m.line.length) });
      }
    }
    const w = this.size?.w || this.root.clientWidth;
    const h = this.size?.h || this.root.clientHeight;
    const html = [];
    for (const item of items) {
      const v = new THREE.Vector3(item.at.x, item.at.y, (item.z || 0) * rise + 0.3).project(this.gl.camera);
      if (v.z > 1 || v.z < -1) continue;
      const x = ((v.x + 1) / 2) * w;
      const y = ((1 - v.y) / 2) * h;
      if (x < -80 || x > w + 80 || y < -40 || y > h + 40) continue;
      html.push(`<span class="measure-label${item.live ? ' is-live' : ''}" style="transform: translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)">${item.text}</span>`);
    }
    const out = html.join('');
    if (parts.labels.innerHTML !== out) parts.labels.innerHTML = out;
  },
};
