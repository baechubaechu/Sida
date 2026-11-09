// The papers on the table: drawing each kind, pins and peeks in 3D, the AI section (tray),
// photos and PDFs, resizing, notes, tracing sheets, folding.
// Methods of DraftingTable (table.js adds them to its prototype).

import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { drawPage, pdfInfo } from './pdf-view.js';
import { paperGlyph, PX, PAPER_SIZE, isOverlaid, freeSpot, folded, pinnedPapers, peekSpot, paperName, resultPreview, KIND_LABELS, originLabel, figureLines, toggleSelected, fmt, photoPlan, shrunkSize, photoPaperSize, photoTitle, pickPhotoFiles, PHOTO_SIZES, MAX_PHOTOS_AT_ONCE, MAX_PHOTO_BYTES, isPdfFile, isPdfPaper, pdfCanvasSize, pdfNeedsRedraw, resizable, resizedPaper, paperTextScale } from './board-model.js';
import { PHOTO_GAP, cm, strokePath } from './table-shared.js';

export const papersMethods = {
  foldChanged(fold) {
    this.root.classList.toggle('is-3d', fold);
    if (!fold && this.peekId) { this.peekId = ''; this.drawPeek(); }
    if (fold && !this.toldFold && this.pins.size) {
      this.toldFold = true;
      this.say('3D에서는 종이가 이름표로 접힙니다. 이름표를 누르면 내용이 열립니다.');
    }
  },
  // Each pin stands where its paper lies; the open card follows its pin. In plan only the
  // pins of folded papers (`only`) show.
  placePins(only = null) {
    const { camera } = this.gl;
    // In plan a folded paper is a circle; in 3D every paper is its title (a circle while dragged).
    for (const el of this.pins.values()) el.classList.toggle('is-flat', Boolean(only));
    const w = this.size?.w || this.root.clientWidth;
    const h = this.size?.h || this.root.clientHeight;
    const at = new THREE.Vector3();
    let anchor = null;
    for (const [id, el] of this.pins) {
      const p = this.papers.find((x) => x.id === id);
      if (!p) continue;
      at.set(p.x, p.y, 0.1).project(camera);
      const x = ((at.x + 1) / 2) * w;
      const y = ((1 - at.y) / 2) * h;
      const shown = (!only || only.has(id)) && at.z < 1 && x > -40 && x < w + 40 && y > -20 && y < h + 60;
      el.hidden = !shown;
      if (shown) el.style.transform = `translate(${x.toFixed(1)}px, ${y.toFixed(1)}px) translate(-50%, calc(-100% - 8px))`;
      if (id === this.peekId && shown) anchor = { x, y: y - 8 - el.offsetHeight / 2, w: el.offsetWidth };
    }
    const card = this.ui.peek;
    if (!this.peekId || card.hidden) return;
    if (!anchor) { card.style.visibility = 'hidden'; return; }
    // Keep clear of the view panel on the right and the toolbars at the top and bottom.
    const box = { left: (this.trayOpen ? this.ui.tray.offsetWidth : 0) + 12, top: 12, right: w - (this.ui.tilt.offsetWidth || 0) - 24, bottom: h - 64 };
    const spot = peekSpot(anchor, { w: card.offsetWidth, h: card.offsetHeight }, box);
    card.style.visibility = '';
    card.style.transform = `translate(${spot.x.toFixed(1)}px, ${spot.y.toFixed(1)}px)`;
  },
  // A pin folding into its circle (dot) or opening back into its title, its width animated.
  morphPin(id, dot) {
    const el = this.pins.get(id);
    if (!el || el.classList.contains('is-dot') === dot) return;
    const from = el.offsetWidth;
    el.classList.toggle('is-dot', dot);
    el.style.width = '';
    const to = el.offsetWidth;
    if (!from || !to || matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    el.classList.add('is-morphing');
    el.style.width = `${from}px`;
    void el.offsetWidth; // start from the old width
    el.style.width = `${to}px`;
    const done = () => { el.classList.remove('is-morphing'); el.style.width = ''; };
    el.addEventListener('transitionend', done, { once: true });
    setTimeout(done, 400);
  },
  slot(id) {
    if (!this.slots.has(id)) {
      const el = document.createElement('div');
      el.className = 'slot';
      this.slots.set(id, el);
    }
    return this.slots.get(id);
  },
  syncPapers() {
    if (!this.gl) return;
    const g = this.gl;
    const want = new Map(this.papers.map((p) => [p.id, p]));
    for (const [id, obj] of g.objects) {
      if (!want.has(id)) { g.cssScene.remove(obj); g.objects.delete(id); this.slots.delete(id); this.drawn.delete(id); }
    }
    for (const [id, p] of want) {
      let obj = g.objects.get(id);
      if (!obj) {
        obj = new THREE.CSS3DObject(this.slot(id));
        obj.scale.setScalar(PX);
        g.cssScene.add(obj);
        g.objects.set(id, obj);
      }
      obj.position.set(p.x, p.y, p.kind === 'tracing' ? 0.3 : 0.1);
      this.drawPaper(p);
    }
    g.traces.clear();
    const mat = new THREE.LineBasicMaterial({ color: this.colors.pen });
    for (const p of this.papers) {
      if (!isOverlaid(p, this.home) || this.layerHidden(p)) continue;
      for (const s of p.strokes || []) {
        g.traces.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(s.map(([x, y]) => new THREE.Vector3(x, y, 0.15))), mat));
      }
    }
    this.drawPins();
    this.drawPeek();
    this.invalidate();
  },
  drawPaper(p) {
    const overlaid = isOverlaid(p, this.home);
    const state = {
      p: { ...p, x: 0, y: 0 }, sel: this.selected.includes(p.id), overlaid, editing: this.editing === p.id,
      active: this.active === p.id, f: this.figures[p.id], site: p.kind === 'site' ? this.site : null,
    };
    const key = JSON.stringify(state);
    if (this.drawn.get(p.id) === key) return;
    this.drawn.set(p.id, key);
    const el = this.slot(p.id);
    const cls = `paper kind-${p.kind} ${state.sel ? 'is-selected' : ''} ${overlaid ? 'is-overlaid' : ''} ${state.active ? 'is-active' : ''}`;
    // A resized paper's writing grows with it: laid out at its first size and zoomed (the paper
    // still takes p.w × p.h on the table).
    const z = paperTextScale(p);
    const size = z === 1 ? `width:${p.w}px;height:${p.h}px` : `width:${p.w / z}px;height:${p.h / z}px;zoom:${z}`;
    const made = originLabel(p, this.hooks.experts());
    const madeTag = made ? `<span class="paper-made">${escape(made)}</span>` : '';
    // A pin at the top middle of each paper (2026-11-09 지훈): it makes the paper a circle on the table.
    const foldButton = overlaid || state.editing ? ''
      : `<button type="button" class="paper-pin" data-fold="${escape(p.id)}" aria-label="${escape(paperName(p))} 핀으로 만들기" data-tip="핀으로 만들기"><span aria-hidden="true"></span></button>`;
    // Corner grips: a drag on one resizes the paper (2026-11-07 지훈), the opposite corner staying put.
    const grips = resizable(p) && !state.editing
      ? ['nw', 'ne', 'sw', 'se'].map((c) => `<i class="paper-grip" data-grip="${c}" data-for="${escape(p.id)}" aria-hidden="true"></i>`).join('') : '';
    if (p.kind === 'note') {
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${madeTag}${foldButton}
        ${state.editing
    ? `<textarea aria-label="메모 내용" maxlength="4000">${escape(p.text || '')}</textarea>`
    : `<p>${escape(p.text || '메모')}</p>`}</article>${grips}`;
      if (state.editing) {
        const area = el.querySelector('textarea');
        requestAnimationFrame(() => { area.focus(); area.select(); });
      }
      return;
    }
    if (p.kind === 'photo') {
      const pdf = isPdfPaper(p);
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${madeTag}${foldButton}
        ${pdf ? `<div class="pdf-page" role="img" aria-label="${escape(paperName(p))}"></div>`
    : `<img src="${escape(this.hooks.photoUrl(p.id))}" alt="${escape(paperName(p))}" draggable="false" decoding="async">`}
        ${p.title ? `<span class="paper-tag">${escape(p.title)}</span>` : ''}</article>${grips}`;
      if (pdf) this.showPdf(el.querySelector('.pdf-page'), `card:${p.id}`, p, pdfCanvasSize(p.w, p.h, this.paperZoom, window.devicePixelRatio));
      return;
    }
    if (p.kind === 'tracing') {
      el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="width:${this.home.w}px;height:${this.home.h}px">
        ${this.traceSvg(p)}<span class="paper-tag">${escape(paperName(p))}${overlaid ? ' · 덮음' : ''}</span>${foldButton}</article>`;
      return;
    }
    const { title, body } = this.paperContent(p, state.active, state.f);
    el.innerHTML = `<article class="${cls}" data-paper="${escape(p.id)}" style="${size}">${foldButton}
      <header class="paper-head"><span class="paper-kind">${escape(KIND_LABELS[p.kind] || p.kind)}</span>${madeTag}<h3>${escape(title)}</h3>
        <button type="button" class="paper-open" data-inspect="${escape(p.id)}" aria-label="${escape(title)} 상세 보기">상세 보기 ↗</button></header>
      <div class="paper-body">${body}</div></article>${grips}`;
  },
  // What a site, mass or expert paper says: the same on the table and in its card in 3D.
  paperContent(p, active, f, card = false) {
    if (p.kind === 'site') {
      const lines = this.site?.lines || [];
      return {
        title: '대지 사실',
        body: lines.length
          ? `<ul class="facts">${lines.map((l) => `<li>${escape(l)}</li>`).join('')}</ul>
            <p class="source">정부 자료(대지 사실)${this.site?.plan ? '' : ' · 필지 경계 미확인'}</p>`
          : '<p class="muted">대지 사실이 아직 없습니다. 대지 주소를 조회하면 필지 경계와 면적이 여기에 나옵니다.</p>',
      };
    }
    if (p.kind === 'mass') {
      const blocks = (p.blocks || []).map((b) => `${fmt(b.w, 1)}×${fmt(b.d, 1)}m ${b.floors}층`).join(' + ');
      return {
        title: paperName(p),
        body: `<p class="blocks">${escape(blocks)}</p>
          ${figureLines(f).map((l) => `<p class="figure">${escape(l)}</p>`).join('')}
          ${card ? '' : `<p class="source">${active ? '3D로 보는 안' : '누르면 3D로 세웁니다'} · 상세 보기에서 고칩니다</p>`}`,
      };
    }
    if (p.kind === 'expert') {
      return {
        title: paperName(p),
        body: `<pre class="preview">${escape(resultPreview(p.text))}</pre>
          <button type="button" class="paper-link" data-open-expert="${escape(p.agent || '')}">결과 문서 보기 ↗</button>`,
      };
    }
    return { title: paperName(p), body: '' };
  },
  traceSvg(p) {
    const b = this.bounds;
    const m = (this.home.w * PX - (b.maxX - b.minX)) / 2;
    const marks = [[b.minX, b.minY], [b.maxX, b.minY], [b.minX, b.maxY], [b.maxX, b.maxY]]
      .map(([x, y]) => `<path class="reg" d="M${x - 3} ${-y} H${x + 3} M${x} ${-y - 3} V${-y + 3}"/>`).join('');
    return `<svg viewBox="${b.minX - m} ${-(b.maxY + m)} ${b.maxX - b.minX + m * 2} ${b.maxY - b.minY + m * 2}" aria-hidden="true">${marks}
      ${(p.strokes || []).map((s) => `<path class="trace" d="${strokePath(s)}"/>`).join('')}<path class="trace draft" d=""/></svg>`;
  },
  // ------------------------------------------------------------------ pins and cards (3D)

  // Pins are rebuilt only when papers come or go; selection and the open card just restyle
  // them, so a pin keeps keyboard focus.
  drawPins() {
    const want = pinnedPapers(this.papers, this.home).filter((p) => !this.layerHidden(p)); // not on a layer turned off
    const key = JSON.stringify(want.map((p) => [p.id, paperName(p), p.kind]));
    if (key !== this.pinKey) {
      this.pinKey = key;
      this.pins.clear();
      this.pinLayer.innerHTML = want.map((p) => `<button type="button" class="pin kind-${p.kind}" data-pin="${escape(p.id)}"
        aria-label="${escape(paperName(p))} 열기" title="${escape(paperName(p))} · 누르면 열기, Shift+클릭: 대화에 보낼 종이로 고르기" hidden>
        <span class="pin-glyph" aria-hidden="true">${escape(paperGlyph(p))}</span><span class="pin-kind">${escape(KIND_LABELS[p.kind] || p.kind)}</span><span class="pin-name">${escape(paperName(p))}</span><b hidden>3D</b></button>`).join('');
      for (const el of this.pinLayer.querySelectorAll('[data-pin]')) this.pins.set(el.dataset.pin, el);
    }
    for (const [id, el] of this.pins) {
      const active = this.active === id && el.classList.contains('kind-mass');
      el.classList.toggle('is-selected', this.selected.includes(id));
      el.classList.toggle('is-active', active);
      el.querySelector('b').hidden = !active;
      el.setAttribute('aria-pressed', String(this.peekId === id));
    }
    this.invalidate();
  },
  drawPeek() {
    const card = this.ui.peek;
    const p = this.papers.find((x) => x.id === this.peekId);
    if (!p) { card.hidden = true; card.innerHTML = ''; return; }
    const id = escape(p.id);
    const picked = this.selected.includes(p.id);
    const made = originLabel(p, this.hooks.experts());
    let body;
    if (p.kind === 'note') body = `<p class="note-text">${escape(p.text || '메모')}</p>`;
    else if (p.kind === 'tracing') body = `<div class="peek-trace">${this.traceSvg(p)}</div><p class="source">획 ${(p.strokes || []).length}개 · 대지에서 떼어 둔 종이</p>`;
    else if (isPdfPaper(p)) body = `<div class="peek-photo pdf-page" style="aspect-ratio: ${p.w} / ${p.h}"></div>`;
    else if (p.kind === 'photo') body = `<img class="peek-photo" src="${escape(this.hooks.photoUrl(p.id))}" alt="${escape(paperName(p))}" draggable="false">`;
    else body = this.paperContent(p, this.active === p.id, this.figures[p.id], true).body;
    const actions = [
      p.kind === 'mass' && this.active !== p.id ? `<button type="button" data-peek="show" data-id="${id}">3D로 세우기</button>` : '',
      p.kind === 'mass' ? `<button type="button" data-peek="edit" data-id="${id}">고치기</button>` : '',
      p.kind === 'note' ? `<button type="button" data-peek="write" data-id="${id}">평면에서 고치기</button>` : '',
      `<button type="button" data-peek="pick" data-id="${id}" aria-pressed="${picked}">${picked ? '대화에 보냄' : '대화에 보내기'}</button>`,
      p.folded ? `<button type="button" data-peek="unfold" data-id="${id}">펴기</button>` : '',
      `<button type="button" data-peek="plan" data-id="${id}">평면에서 보기</button>`,
      `<button type="button" data-peek="inspect" data-id="${id}">상세 보기</button>`,
    ].join('');
    card.className = `table-ui peek kind-${p.kind}`;
    card.innerHTML = `<header><p class="tray-meta">${escape(KIND_LABELS[p.kind] || p.kind)}${made ? ` · ${escape(made)}` : ''}</p>
        <button type="button" class="tray-close" data-peek="close" aria-label="닫기">×</button></header>
      <h4>${escape(paperName(p))}</h4>
      <div class="peek-body">${body}</div>
      <div class="tray-actions">${actions}</div>`;
    if (isPdfPaper(p)) this.showPdf(card.querySelector('.pdf-page'), `peek:${p.id}`, p, pdfCanvasSize(p.w, p.h, 300 / Math.max(p.w, p.h), window.devicePixelRatio));
    card.hidden = false;
    card.style.visibility = 'hidden'; // placed beside its pin on the next frame
    this.invalidate();
  },
  openPeek(id) {
    this.peekId = this.peekId === id ? '' : id;
    const p = this.papers.find((x) => x.id === id);
    if (this.peekId && p?.kind === 'mass' && this.active !== id) this.showScheme(id);
    else { this.drawPins(); this.drawPeek(); }
  },
  // Back to the plan, centred on a paper.
  planAt(p, then) {
    this.peekId = '';
    this.drawPeek();
    this.animateTo({ x: p.x, y: p.y, tilt: 0, turn: 0, span: Math.max(60, Math.min(this.view.span, 160)) });
    if (then) setTimeout(then, 480);
  },
  // ------------------------------------------------------------------ the AI section

  drawTray() {
    const t = this.ui.tray;
    t.classList.toggle('open', this.trayOpen);
    this.root.classList.toggle('tray-open', this.trayOpen);
    if (!this.trayOpen) { t.innerHTML = ''; return; }
    const experts = this.hooks.experts();
    const named = (id) => { const p = this.papers.find((x) => x.id === id) || this.tray.find((x) => x.id === id); return p ? paperName(p) : id; };
    const cards = [...this.tray].reverse().map((p) => {
      const id = escape(p.id);
      const picked = this.selected.includes(p.id);
      let body = '';
      if (p.kind === 'mass') {
        body = `<p class="blocks">${escape((p.blocks || []).map((b) => `${fmt(b.w, 1)}×${fmt(b.d, 1)}m ${b.floors}층`).join(' + '))}</p>
          ${figureLines(this.figures[p.id]).map((l) => `<p class="figure">${escape(l)}</p>`).join('')}`;
      } else if (p.kind === 'note') {
        body = `<p class="note-text">${escape(p.text || '')}</p>`;
      } else if (p.kind === 'expert') {
        body = `<pre class="preview">${escape(resultPreview(p.text, 5))}</pre>`;
      }
      return `<article class="tray-card kind-${p.kind} ${picked ? 'is-selected' : ''}" data-tray="${id}">
        <p class="tray-meta">${escape(originLabel(p, experts) || 'AI')} · ${escape(KIND_LABELS[p.kind] || p.kind)}</p>
        <h4>${escape(paperName(p))}</h4>
        ${p.based_on ? `<p class="tray-why">${escape(named(p.based_on))}의 수정안</p>` : ''}
        ${p.reason ? `<p class="tray-why">${escape(p.reason)}</p>` : ''}
        ${body}
        <div class="tray-actions">
          <button type="button" class="tray-place" data-tray-action="place" data-id="${id}">제도판에 놓기</button>
          ${p.kind === 'mass' ? `<button type="button" data-tray-action="preview" data-id="${id}" aria-pressed="${this.preview === p.id}">3D 미리 보기</button>` : ''}
          ${p.kind === 'expert' ? `<button type="button" data-open-expert="${escape(p.agent || '')}">결과 문서</button>` : ''}
          <button type="button" data-tray-action="pick" data-id="${id}" aria-pressed="${picked}">${picked ? '대화에 보냄' : '대화에 보내기'}</button>
          <button type="button" class="tray-discard" data-tray-action="discard" data-id="${id}" aria-label="${escape(paperName(p))} 버리기">버리기</button>
        </div></article>`;
    }).join('');
    t.innerHTML = `<header><h3>AI 섹션</h3><button type="button" class="tray-close" data-ui="tray" aria-label="AI 섹션 닫기">×</button></header>
      <p class="tray-intro">Conductor와 전문가가 만든 종이입니다. 마음에 드는 것만 제도판에 놓으세요.</p>
      ${cards || '<p class="tray-empty">아직 없습니다. Conductor에게 매스안이나 메모를 부탁하거나 전문가를 실행하면 여기에 놓입니다.</p>'}`;
  },
  async placeFromTray(id) {
    const p = this.tray.find((x) => x.id === id);
    if (!p) return;
    const [w, h] = PAPER_SIZE[p.kind] || [p.w, p.h];
    const spot = freeSpot(this.papers, this.bounds, w, h);
    if (this.preview === id) this.preview = '';
    const done = await this.hooks.place(id, { ...spot, w, h });
    if (!done) return;
    if (p.kind === 'mass') this.showScheme(id);
    this.say(`${paperName(p)}을(를) 제도판에 놓았습니다.`);
    this.animateTo({ x: spot.x, y: spot.y, span: Math.max(this.view.span, 120), tilt: 0, turn: 0 });
  },
  saveTitle(id, value) {
    const p = this.papers.find((x) => x.id === id);
    const title = value.trim().slice(0, 120);
    if (!p || (p.title || '') === title) return;
    this.record([{ op: 'update', id, before: { title: p.title || '' }, after: { title } }]);
    p.title = title;
    this.drawPaper(p);
    this.drawPins();
    this.save(id, { title });
  },
  // ------------------------------------------------------------------ photos
  // A photo comes from the 사진 올리기 button (or the photo command), a drop on the table, or a
  // paste. It goes up as it is when the server takes it; otherwise it is redrawn smaller first.

  pickPhotos() {
    this.photoInput.value = '';
    this.photoInput.click();
  },
  // files: a FileList or array; at: where on the table (metres) the first one goes, else beside the site.
  async addPhotos(files, at = null) {
    const { files: pictures, skipped } = pickPhotoFiles(files);
    if (!pictures.length) { this.say('사진이나 PDF 파일이 아닙니다. JPEG, PNG, GIF, WebP 사진이나 PDF를 올려 주세요.'); return; }
    if (skipped) this.say(`사진·PDF 파일만, 한 번에 ${MAX_PHOTOS_AT_ONCE}개까지 올립니다. ${skipped}개는 건너뜁니다.`);
    let spot = at;
    const added = [];
    const failed = [];
    for (const file of pictures) {
      this.say(`사진을 올리는 중입니다… (${added.length + failed.length + 1}/${pictures.length})`);
      const ready = await this.preparePhoto(file);
      if (!ready) { failed.push(file.name || '사진'); continue; }
      // A drawing (PDF) starts larger than a photo: it is there to be read.
      const { w, h } = photoPaperSize(ready.width, ready.height, ready.pdf ? PHOTO_SIZES.large : PHOTO_SIZES.medium);
      const place = spot || freeSpot(this.papers, this.bounds, w, h);
      const done = await this.hooks.addPhoto(ready.blob, ready.name, { title: photoTitle(file.name), x: cm(place.x), y: cm(place.y), w, h });
      if (!done?.paper) { failed.push(file.name || '사진'); continue; }
      added.push(done.paper);
      if (spot) spot = { x: spot.x + (w * PX) / 2 + PHOTO_GAP + (w * PX) / 2, y: spot.y };
    }
    if (added.length) {
      this.record(added.map((paper) => ({ op: 'add', paper })));
      this.select(added.map((p) => p.id));
      if (!at) { const last = added[added.length - 1]; this.animateTo({ x: last.x, y: last.y, tilt: 0, turn: 0, span: Math.max(this.view.span, 120) }); }
    }
    const lines = [];
    if (added.length) lines.push(`${added.length}개를 제도판에 올렸습니다. 누르면 크게 보고 이름을 붙일 수 있고, 모서리를 끌면 크기가 바뀝니다.`);
    if (failed.length) lines.push(`${failed.join(', ')}은(는) 올리지 못했습니다. 브라우저가 열 수 있는 사진(JPEG, PNG 등)이나 20MB 이하의 PDF인지 확인해 주세요.`);
    this.say(lines.join(' '));
  },
  // {blob, name, width, height, pdf}, or null when the browser cannot open the picture. A PDF goes
  // up as it is (its first page gives the paper its shape); the table draws it from the PDF.
  async preparePhoto(file) {
    if (isPdfFile(file)) {
      if (file.size > MAX_PHOTO_BYTES) return null;
      const info = await pdfInfo(file);
      return info && { blob: file, name: file.name || 'drawing.pdf', width: info.width, height: info.height, pdf: true };
    }
    let bitmap;
    try { bitmap = await createImageBitmap(file); } catch { return null; }
    const { width, height } = bitmap;
    if (photoPlan(file.type, file.size, width, height) === 'keep') {
      bitmap.close();
      return { blob: file, name: file.name || 'photo', width, height };
    }
    const size = shrunkSize(width, height);
    const canvas = document.createElement('canvas');
    Object.assign(canvas, size);
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = '#fff'; // a transparent picture lies on white paper
    ctx.fillRect(0, 0, size.width, size.height);
    ctx.drawImage(bitmap, 0, 0, size.width, size.height);
    bitmap.close();
    const blob = await new Promise((resolve) => { canvas.toBlob(resolve, 'image/jpeg', 0.88); });
    if (!blob) return null;
    const base = String(file.name || 'photo').replace(/\.[A-Za-z0-9]{1,5}$/, '');
    return { blob, name: `${base}.jpg`, ...size };
  },
  resizePhoto(id, longest) {
    const p = this.papers.find((x) => x.id === id && x.kind === 'photo');
    if (!p) return;
    const { w, h } = photoPaperSize(p.w, p.h, longest);
    if (w === p.w && h === p.h) return;
    this.record([{ op: 'update', id, before: { w: p.w, h: p.h }, after: { w, h } }]);
    Object.assign(p, { w, h });
    this.syncPapers();
    this.drawDetail();
    this.save(id, { w, h });
  },
  // ------------------------------------------------------------------ PDF pages
  // A PDF paper shows one page, drawn from the PDF at the size it is seen (pdf-view.js), in the
  // paper on the table, in the detail panel and in its card in 3D. Each keeps its canvas, so a
  // redraw of the paper (picked, moved) moves the drawn page over instead of drawing it again.

  // Put the page into holder, drawing it again when it is wanted sharper (or much smaller) than
  // it was drawn, or another page is asked for. Resolves to the PDF's number of pages (0: not drawn).
  async showPdf(holder, key, p, size) {
    const url = this.hooks.photoUrl(p.id);
    let entry = this.pdfs.get(key);
    if (!entry || entry.url !== url) {
      const canvas = document.createElement('canvas');
      canvas.className = 'pdf-canvas';
      entry = { canvas, url, page: 0, size: null };
      this.pdfs.set(key, entry);
    }
    if (holder && entry.canvas.parentElement !== holder) holder.append(entry.canvas);
    const page = p.page || 1;
    if (entry.page === page && !pdfNeedsRedraw(entry.size, size)) return this.pdfPages.get(url) || 0;
    Object.assign(entry, { page, size });
    try {
      const pages = await drawPage(entry.canvas, url, page, size.width);
      if (pages) this.pdfPages.set(url, pages);
      this.invalidate();
      return pages;
    } catch {
      entry.size = null;
      holder?.classList.add('is-broken');
      this.say(`${paperName(p)} PDF를 그리지 못했습니다. 파일이 손상되었거나 암호가 걸려 있을 수 있습니다.`);
      return 0;
    }
  },
  // After a zoom: draw the PDF papers again at the new sharpness (only those that need it).
  refreshPdfs() {
    for (const p of this.papers) {
      if (!isPdfPaper(p)) continue;
      const holder = this.slots.get(p.id)?.querySelector('.pdf-page');
      if (holder) this.showPdf(holder, `card:${p.id}`, p, pdfCanvasSize(p.w, p.h, this.paperZoom, window.devicePixelRatio));
    }
    for (const key of this.pdfs.keys()) {
      const [where, id] = key.split(/:(.*)/s);
      if (where === 'card' && !this.papers.some((p) => p.id === id)) this.pdfs.delete(key);
    }
  },
  turnPage(id, step) {
    const p = this.papers.find((x) => x.id === id && isPdfPaper(x));
    const pages = p && this.pdfPages.get(this.hooks.photoUrl(id));
    if (!p || !pages) return;
    const page = Math.min(pages, Math.max(1, (p.page || 1) + step));
    if (page === (p.page || 1)) return;
    this.record([{ op: 'update', id, before: { page: p.page || 1 }, after: { page } }]);
    p.page = page;
    this.syncPapers();
    this.drawDetail();
    this.save(id, { page });
  },
  // ------------------------------------------------------------------ resizing a paper
  // A drag on a corner grip resizes the paper; a photo or PDF keeps its shape.

  resizeGesture(grip, e) {
    const p = this.papers.find((x) => x.id === grip.dataset.for);
    const g0 = this.ground(e.clientX, e.clientY);
    if (!p || !resizable(p) || !g0) return null;
    if (!this.selected.includes(p.id)) this.select([p.id]);
    return { kind: 'resize', id: p.id, corner: grip.dataset.grip, from: { x: p.x, y: p.y, w: p.w, h: p.h }, g0, moved: false, x: e.clientX, y: e.clientY };
  },
  resizeMove(g, e) {
    if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
    const at = this.ground(e.clientX, e.clientY);
    const p = this.papers.find((x) => x.id === g.id);
    if (!at || !p) return;
    g.moved = true;
    // The pointer may have pressed a little inside the corner: keep that offset.
    const sx = g.corner.includes('e') ? 1 : -1;
    const sy = g.corner.includes('n') ? 1 : -1;
    const corner = { x: g.from.x + (sx * g.from.w * PX) / 2, y: g.from.y + (sy * g.from.h * PX) / 2 };
    const point = { x: at.x + corner.x - g.g0.x, y: at.y + corner.y - g.g0.y };
    // As in a drawing program: the opposite corner stays; Alt keeps the middle (all four sides
    // move); Ctrl keeps the shape (a photo always does). Read on every move, so they can be
    // pressed or let go during the drag.
    const ratio = p.kind === 'photo' || e.ctrlKey || e.metaKey;
    if (e.altKey) this.altResized = true;
    Object.assign(p, resizedPaper(g.from, g.corner, point, { ratio, center: e.altKey }));
    // Only the size changes while dragging (the paper is drawn again when the drag ends); its
    // writing grows or shrinks with it as it goes (paperTextScale), not in one jump at the end.
    const article = this.slots.get(p.id)?.querySelector('[data-paper]');
    const z = paperTextScale(p);
    if (article) Object.assign(article.style, { width: `${p.w / z}px`, height: `${p.h / z}px`, zoom: z === 1 ? '' : String(z) });
    this.gl?.objects.get(p.id)?.position.set(p.x, p.y, 0.1);
    this.say(`${fmt(p.w * PX, 1)} × ${fmt(p.h * PX, 1)} m · Alt: 가운데 기준 · Ctrl: 비율 유지`);
    this.invalidate();
  },
  resizeEnd(g) {
    const p = this.papers.find((x) => x.id === g.id);
    if (!p || !g.moved) return;
    const after = { x: p.x, y: p.y, w: p.w, h: p.h };
    if (Object.keys(after).every((k) => after[k] === g.from[k])) return;
    this.record([{ op: 'update', id: p.id, before: { ...g.from }, after }]);
    this.syncPapers();
    if (this.detailId === p.id) this.drawDetail();
    this.save(p.id, after);
  },
  saveNoteText(id, text) {
    const p = this.papers.find((x) => x.id === id);
    if (!p || (p.text || '') === text) return;
    this.record([{ op: 'update', id, before: { text: p.text || '' }, after: { text } }]);
    p.text = text;
    this.drawPaper(p);
    this.drawPins();
    this.save(id, { text });
  },
  // Fold a paper into its name tag (in plan too) or open it again; saved with the paper.
  setFolded(id, on) {
    const p = this.papers.find((x) => x.id === id);
    if (!p || Boolean(p.folded) === on) return;
    this.record([{ op: 'update', id, before: { folded: !on }, after: { folded: on } }]);
    if (on) p.folded = true;
    else delete p.folded;
    if (!on && this.peekId === id && !folded(this.view.tilt)) this.peekId = '';
    this.drawPins();
    this.drawPeek();
    if (on && !this.toldPlanFold) {
      this.toldPlanFold = true;
      this.say('핀으로 만든 종이는 동그라미로 남습니다. 동그라미를 누르고 [펴기]를 누르면 다시 펼쳐집니다.');
    }
    this.save(id, { folded: on });
  },
  layTracing() {
    const covering = this.papers.find((p) => isOverlaid(p, this.home));
    if (covering) {
      this.select([covering.id]);
      this.setTool('pen');
      this.say(`${paperName(covering)}이(가) 이미 대지 위에 있습니다. 그 위에 그리세요.`);
      return;
    }
    const n = this.papers.filter((p) => p.kind === 'tracing').length + 1;
    const sheet = { kind: 'tracing', title: `트레이싱 ${n}`, strokes: [], overlaid: true, x: this.home.x, y: this.home.y, w: this.home.w, h: this.home.h };
    this.hooks.add(sheet).then((done) => {
      if (!done?.paper) return;
      this.record([{ op: 'add', paper: done.paper }]);
      this.select([done.paper.id]);
      this.setTool('pen');
      this.animateTo({ tilt: 0 });
      this.say('대지 위에 트레이싱지를 덮었습니다. 펜으로 그린 뒤 종이를 옆으로 끌어내면 떼어집니다.');
    });
  },
  removeSelected() {
    const ids = this.selected.filter((id) => this.papers.some((p) => p.id === id && p.kind !== 'site'));
    if (!ids.length) return;
    this.record(this.papers.filter((p) => ids.includes(p.id)).map((p) => ({ op: 'remove', paper: structuredClone(p) })));
    if (ids.includes(this.detailId)) this.closeDetail();
    this.papers = this.papers.filter((p) => !ids.includes(p.id));
    this.select(this.selected.filter((id) => !ids.includes(id)));
    this.syncPapers();
    this.drawMasses();
    for (const id of ids) this.hooks.remove(id);
  },
  peekAction(action, id) {
    const p = this.papers.find((x) => x.id === id);
    if (action === 'close' || !p) { this.peekId = ''; this.drawPins(); this.drawPeek(); return; }
    switch (action) {
      case 'show': this.showScheme(id); break;
      case 'edit': this.openForm(p); break;
      case 'pick': this.select(toggleSelected(this.selected, id, true)); break;
      case 'plan': this.planAt(p); break;
      case 'unfold': this.setFolded(id, false); break;
      case 'inspect': this.inspect(id); break;
      case 'write': this.setFolded(id, false); this.planAt(p, () => { this.editing = id; this.select([id]); }); break;
      default: break;
    }
  }
};
