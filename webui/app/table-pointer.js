// Mouse, wheel, keyboard and touch on the table: Rhino-like navigation, selection boxes, the
// tools' gestures, dragging papers and blocks, carrying papers to the idea board.
// Methods of DraftingTable (table.js adds them to its prototype).

import { PX, PAPER_SIZE, zoomAround, dragMode, wheelZoom, panBy, EDGE_TILT, isOverlaid, blockCorners, paperName, toggleSelected, boxPick, boxMode, parseBlockKey, fmt, frameDelta, editBlocks, axisDrag, blockKey, toFrame, rectBlock, pushBlock, copyBlocks, turnBlocks, scaleBlocks, snapAngle, MAX_BLOCKS, numericToolClick, isPdfFile, buildingInfo } from './board-model.js';
import { SNAP, typing, MODEL_TOOLS, cm, strokePath } from './table-shared.js';

export const pointerMethods = {
  // ------------------------------------------------------------------ input

  listen() {
    const root = this.root;
    root.addEventListener('wheel', (e) => this.onWheel(e), { passive: false });
    // Focus on a pin at the edge must not scroll the table (older browsers without overflow: clip).
    root.addEventListener('scroll', () => { root.scrollLeft = 0; root.scrollTop = 0; });
    root.addEventListener('pointerdown', (e) => this.onDown(e));
    root.addEventListener('pointermove', (e) => this.onMove(e));
    root.addEventListener('pointerup', () => this.onUp());
    root.addEventListener('pointercancel', () => this.onUp(true));
    root.addEventListener('dblclick', (e) => this.onDouble(e));
    root.addEventListener('contextmenu', (e) => { if (!typing(e.target) && !e.target.closest('dialog')) e.preventDefault(); });
    root.addEventListener('keydown', (e) => this.onKey(e));
    // Ctrl+Z also works while the focus is elsewhere on the page (a button beside the table, or
    // nothing), but never in a text field or another dialog, which keep their own undo.
    this.onWindowKey = (e) => {
      if (!(e.ctrlKey || e.metaKey) || !this.root.isConnected || this.root.parentElement?.hidden) return;
      const at = document.activeElement;
      if (this.root.contains(at) || typing(at) || at?.closest?.('dialog')) return;
      this.onKey(e);
    };
    window.addEventListener('keydown', this.onWindowKey);
    root.addEventListener('click', (e) => this.onClick(e));
    root.addEventListener('input', (e) => this.onInput(e));
    root.addEventListener('change', (e) => {
      if (e.target.dataset.ui === 'ghost') { this.ghost = e.target.checked; this.drawMasses(); }
      if (e.target.dataset.ui === 'contour-step') { this.contourStep = Number(e.target.value) || 1; this.drawAround(); }
      if (e.target.dataset.ui === 'around-size') this.changeRange({ size: e.target.value });
      if (e.target.dataset.ui === 'around-shape') this.changeRange({ shape: e.target.value });
      if (e.target.dataset.ui === 'around-orient') this.changeRange({ orient: e.target.value });
      if (e.target === this.photoInput && this.photoInput.files.length) this.addPhotos([...this.photoInput.files]);
      if (e.target.dataset.detailTitle) this.saveTitle(e.target.dataset.detailTitle, e.target.value);
    });
    // Photo files dragged in from the desktop land where they are dropped.
    const carriesFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
    root.addEventListener('dragover', (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      e.dataTransfer.dropEffect = 'copy';
      this.dropEl.hidden = false;
    });
    root.addEventListener('dragleave', (e) => { if (!root.contains(e.relatedTarget)) this.dropEl.hidden = true; });
    root.addEventListener('drop', (e) => {
      if (!carriesFiles(e)) return;
      e.preventDefault();
      this.dropEl.hidden = true;
      const at = this.view.tilt < EDGE_TILT ? this.ground(e.clientX, e.clientY) : null;
      this.addPhotos([...e.dataTransfer.files], at || null);
    });
    // A picture pasted (Ctrl+V of a screenshot or a copied image) while the table is in view.
    this.onPaste = (e) => {
      if (!this.root.isConnected || this.root.parentElement?.hidden) return;
      const at = document.activeElement;
      if (typing(at) || at?.closest?.('dialog')) return;
      const files = [...(e.clipboardData?.files || [])].filter((f) => f.type.startsWith('image/') || isPdfFile(f));
      if (!files.length) return;
      e.preventDefault();
      this.addPhotos(files);
    };
    window.addEventListener('paste', this.onPaste);
    root.addEventListener('submit', (e) => { e.preventDefault(); if (e.target.dataset.form === 'scheme') this.saveForm(); if (e.target.dataset.form === 'tool-number') this.applyToolNumber(); });
    this.ui.number.addEventListener('close', () => { this.numberEdit = null; this.root.focus({ preventScroll: true }); });
    root.addEventListener('focusout', (e) => {
      // A note being written is saved when it loses focus.
      if (e.target.dataset?.detailNote) { this.saveNoteText(e.target.dataset.detailNote, e.target.value); return; }
      if (e.target.tagName !== 'TEXTAREA' || !this.editing) return;
      const id = this.editing;
      const p = this.papers.find((x) => x.id === id);
      this.editing = '';
      if (p) { this.saveNoteText(id, e.target.value); this.drawPaper(p); }
    });
    const detail = this.ui.detail;
    detail.addEventListener('close', () => { this.saveDetailNote(); this.detailId = ''; });
    // The panel sits beside the table without blocking it, so Esc is handled here (a panel that
    // is not modal does not close on Esc by itself).
    detail.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      e.preventDefault();
      e.stopPropagation();
      this.closeDetail();
      this.root.focus({ preventScroll: true });
    });
  },
  onClick(e) {
    const t = e.target.closest('button, [data-open-expert]');
    if (!t) return;
    if (t.dataset.ui === 'view-scale') { this.openViewScale(); return; }
    if (t.dataset.ui === 'number-cancel') { this.ui.number.close(); return; }
    if (t.dataset.openExpert) { this.closeDetail(); this.hooks.openExpert(t.dataset.openExpert); return; }
    if (t.dataset.inspect) { this.select([t.dataset.inspect]); this.inspect(t.dataset.inspect); return; }
    if (t.dataset.detail) { this.detailAction(t.dataset.detail); return; }
    if (t.dataset.tool) { this.setTool(t.dataset.tool); return; }
    if (t.dataset.active) { this.showScheme(t.dataset.active); return; }
    if (t.dataset.fold) { this.setFolded(t.dataset.fold, true); return; }
    if (t.dataset.pin) {
      if (performance.now() < (this.skipClickUntil || 0)) return;
      // A click picks the pin's paper (Shift adds or takes away) and opens its card; a picked pin drags.
      if (e.shiftKey) this.select(toggleSelected(this.selected, t.dataset.pin, true));
      else { if (!this.selected.includes(t.dataset.pin)) this.select([t.dataset.pin]); this.openPeek(t.dataset.pin); }
      return;
    }
    if (t.dataset.peek) {
      this.peekAction(t.dataset.peek, t.dataset.id);
      // The card was redrawn under the pointer: keep the keys (Esc, Delete) on the table.
      if (!this.root.contains(document.activeElement)) this.root.focus({ preventScroll: true });
      return;
    }
    if (t.dataset.tilt) { this.showView(t.dataset.tilt); return; }
    const id = t.dataset.id;
    switch (t.dataset.trayAction) {
      case 'place': this.placeFromTray(id); return;
      case 'discard': if (this.preview === id) { this.preview = ''; this.drawMasses(); } this.hooks.discard(id); return;
      case 'preview': this.preview = this.preview === id ? '' : id; this.drawMasses(); this.drawTray(); if (this.preview) this.showView('3d'); return;
      case 'pick': this.select(toggleSelected(this.selected, id, true)); return;
      default: break;
    }
    switch (t.dataset.ui) {
      case 'scheme-new': this.openForm(); break;
      case 'undo': this.travel('undo'); break;
      case 'redo': this.travel('redo'); break;
      case 'trace': this.layTracing(); break;
      case 'photo': this.pickPhotos(); break;
      case 'around': this.toggleAround(); break;
      case 'model-panel': this.openModel(); break;
      case 'model-stepped': this.toggleStepped(); break;
      case 'around-note': this.aroundNoteOpen = !this.aroundNoteOpen; this.drawAroundNote(); break;
      case 'delete': this.removeSelected(); break;
      case 'tray': this.trayOpen = !this.trayOpen; this.drawTray(); this.drawControls(); break;
      case 'north': this.animateTo({ turn: 0 }); break;
      case 'zoom-in': this.animateTo({ span: this.view.span / 1.4 }, 200); break;
      case 'zoom-out': this.animateTo({ span: this.view.span * 1.4 }, 200); break;
      case 'fit': this.fit(); break;
      case 'form-close': this.form = null; this.drawForm(); break;
      case 'row-add': if (this.form.rows.length < 20) { this.form.rows.push({ u: '0', v: '0', w: '20', d: '15', floors: '3', a: '0' }); this.drawForm(); } break;
      case 'row-remove': this.form.rows.splice(Number(t.dataset.row), 1); this.drawForm(); break;
      default: break;
    }
  },
  onInput(e) {
    const t = e.target;
    if (t.dataset.ui === 'tilt-range') {
      this.tween += 1;
      this.setView({ ...this.view, tilt: Number(t.value) });
      return;
    }
    if (!this.form || !t.closest('.scheme-form')) return;
    if (t.dataset.row !== undefined) this.form.rows[Number(t.dataset.row)][t.dataset.key] = t.value;
    else if (t.dataset.key) this.form[t.dataset.key] = t.value;
  },
  onWheel(e) {
    if (e.target.closest('.tray, .scheme-form, dialog') || typing(e.target)) return;
    e.preventDefault();
    this.hooks.viewMoved?.();
    const v = this.view;
    this.tween += 1;
    const pinch = e.ctrlKey || e.metaKey;
    if (!pinch && e.shiftKey && !e.deltaX) {
      this.setView({ ...v, turn: v.turn + e.deltaY * 0.15 });
    } else if (!pinch && e.deltaX) {
      // A trackpad's two-finger slide: the table goes along with the fingers.
      const a = v.tilt < EDGE_TILT && this.ground(e.clientX, e.clientY);
      const b = a && this.ground(e.clientX + e.deltaX, e.clientY + e.deltaY);
      if (a && b) this.setView({ ...v, x: v.x + (b.x - a.x), y: v.y + (b.y - a.y) });
      else this.setView(panBy(v, -e.deltaX, -e.deltaY, this.root.clientHeight));
    } else {
      // The wheel zooms around the point under the cursor, as in Rhino.
      // Seen near edge-on (an elevation) the table under the cursor is far off or missing: zoom on the middle.
      const g0 = (v.tilt < EDGE_TILT && this.ground(e.clientX, e.clientY)) || v;
      this.setView(zoomAround(v, g0.x, g0.y, wheelZoom(e.deltaY, e.deltaMode, pinch)));
    }
  },
  onDown(e) {
    // Dragging a pin moves its paper straight away, picked or not (2026-11-02 지훈); a picked
    // pin takes the other picked papers along. The pointer is not captured, so a press without
    // a drag stays a click on the pin.
    const pinId = e.button === 0 && !e.shiftKey && e.target.closest('[data-pin]')?.dataset.pin;
    if (pinId) {
      const g0 = this.ground(e.clientX, e.clientY);
      const ids = new Set(this.selected.includes(pinId) ? this.selected.filter((id) => this.papers.some((p) => p.id === id)) : [pinId]);
      if (g0) this.gesture = { kind: 'move', pin: true, g0, ids, id: pinId, shift: false, from: new Map(this.papers.map((q) => [q.id, { x: q.x, y: q.y, overlaid: q.overlaid }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    if (e.target.closest('.table-ui, dialog') || typing(e.target) || e.target.closest('button, a')) return;
    e.preventDefault(); // no text selection while dragging across the panes
    this.root.focus({ preventScroll: true });
    this.root.setPointerCapture(e.pointerId);
    this.tween += 1;
    const v = this.view;
    const grip = e.button === 0 && this.gumAxes && e.target.closest('[data-gumball]')?.dataset.gumball;
    if (grip) { this.gesture = this.gumballGesture(grip, e); return; }
    const corner = e.button === 0 && !e.shiftKey && !(e.ctrlKey || e.metaKey) && e.target.closest('[data-grip]');
    if (corner) { this.gesture = this.resizeGesture(corner, e); if (this.gesture) return; }
    const mode = dragMode({ button: e.button, shift: e.shiftKey, ctrl: e.ctrlKey || e.metaKey, alt: e.altKey });
    if (mode === 'orbit') { this.gesture = { kind: 'orbit', x: e.clientX, y: e.clientY, v }; return; }
    const g0 = this.ground(e.clientX, e.clientY);
    if (mode) { this.gesture = { kind: mode, g0: (v.tilt < EDGE_TILT && g0) || { x: v.x, y: v.y }, edge: v.tilt >= EDGE_TILT || !g0, v, x: e.clientX, y: e.clientY, moved: false, button: e.button }; return; }
    if (e.button !== 0) return;
    if (MODEL_TOOLS.has(this.tool)) { this.gesture = this.modelGesture(e, g0); return; }
    // Empty table (or the sky above it, in a view near edge-on): a selection box, as in Rhino.
    const box = { kind: 'box', x: e.clientX, y: e.clientY, add: e.shiftKey, remove: e.ctrlKey || e.metaKey, moved: false };
    if (!g0) {
      if (this.tool === 'select') this.gesture = box;
      return;
    }
    if (this.tool === 'pen') {
      const sheet = [...this.papers].reverse().find((p) => p.kind === 'tracing'
        && Math.abs(g0.x - p.x) <= (p.w * PX) / 2 && Math.abs(g0.y - p.y) <= (p.h * PX) / 2);
      if (!sheet) { this.say('트레이싱지 위에만 그릴 수 있습니다. 먼저 [트레이싱지 덮기]를 누르세요.'); return; }
      const off = { x: sheet.x - this.home.x, y: sheet.y - this.home.y };
      this.gesture = { kind: 'draw', id: sheet.id, off, points: [[cm(g0.x - off.x), cm(g0.y - off.y)]] };
      return;
    }
    if (this.tool === 'note') {
      const [w, h] = PAPER_SIZE.note;
      this.setTool('select');
      this.hooks.add({ kind: 'note', text: '', x: g0.x, y: g0.y, w, h }).then((done) => {
        if (!done?.paper) return;
        this.record([{ op: 'add', paper: done.paper }]);
        this.editing = done.paper.id;
        this.select([done.paper.id]);
      });
      return;
    }
    const paperId = e.target.closest('[data-paper]')?.dataset.paper;
    const block = !paperId && this.tool === 'select' && this.blockAt(e.clientX, e.clientY);
    if (block) {
      // A click on a building picks that block alone (Shift adds or takes away); dragging it
      // moves the picked blocks on the ground, as an object in Rhino.
      if (e.shiftKey) { this.pickBlocks(this.picked.includes(block) ? this.picked.filter((k) => k !== block) : [...this.picked, block]); return; }
      if (!this.picked.includes(block)) {
        if (this.selected.length) this.select([]);
        const { id } = parseBlockKey(block);
        if (this.active !== id) this.showScheme(id);
        this.pickBlocks([block]);
      }
      this.gesture = this.gumballGesture('free', e);
      return;
    }
    if (paperId) {
      if (!e.shiftKey && this.picked.length) this.pickBlocks([]);
      const next = e.shiftKey || this.selected.includes(paperId) ? (e.shiftKey ? toggleSelected(this.selected, paperId, true) : this.selected) : [paperId];
      if (next !== this.selected) this.select(next);
      const p = this.papers.find((x) => x.id === paperId);
      if (p?.kind === 'mass' && !e.shiftKey && this.active !== paperId) this.showScheme(paperId);
      this.gesture = { kind: 'move', g0, ids: new Set(next), id: paperId, shift: e.shiftKey, from: new Map(this.papers.map((q) => [q.id, { x: q.x, y: q.y, overlaid: q.overlaid }])), moved: false, x: e.clientX, y: e.clientY };
      return;
    }
    const info = this.tool === 'select' && !e.shiftKey && this.aroundBuildingAt(e.clientX, e.clientY);
    if (info) this.say(buildingInfo(info));
    this.gesture = box;
  },
  onMove(e) {
    const g = this.gesture;
    if (!g) { if (this.tool === 'tape' && !e.target.closest('.table-ui, dialog')) this.tapePoint(e); else this.snapEl.hidden = true; return; }
    if ((g.kind === 'push' || (g.kind === 'gumball' && g.grip === 'scale')) && Math.hypot(e.clientX - g.x, e.clientY - g.y) >= 3) g.dragged = true;
    // The designer moves the view by hand: the talk popups fold away to keep the view clear.
    if ((g.kind === 'orbit' || g.kind === 'pan' || g.kind === 'zoom') && !g.told && Math.hypot(e.clientX - g.x, e.clientY - g.y) > 6) {
      g.told = true;
      this.hooks.viewMoved?.();
    }
    if (g.kind === 'orbit') {
      // As in Rhino the model turns with the hand: drag right and its near side comes right,
      // drag down and its top comes toward you (the view rises toward a plan).
      this.setView({ ...g.v, ...orbitBy(g.v, e.clientX - g.x, e.clientY - g.y) });
    } else if (g.kind === 'pan') {
      const p = !g.edge && this.ground(e.clientX, e.clientY, g.v);
      if (p) this.setView({ ...g.v, x: g.v.x - (p.x - g.g0.x), y: g.v.y - (p.y - g.g0.y) });
      else if (g.edge) this.setView(panBy(g.v, e.clientX - g.x, e.clientY - g.y, this.root.clientHeight));
      if (Math.hypot(e.clientX - g.x, e.clientY - g.y) > 3) g.moved = true;
    } else if (g.kind === 'gumball') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      let delta = {};
      let up = 0; // metres up, for the z arrow
      const ground = ['free', 'rotate', 'scale'].includes(g.grip);
      const p = ground && g.g0 && this.ground(e.clientX, e.clientY);
      if (ground && !p) return;
      if (g.grip === 'free') {
        delta = frameDelta(this.site?.plan?.frame, p.x - g.g0.x, p.y - g.g0.y);
      } else if (!ground) {
        const m = axisDrag(g.axes[{ w: 'u', d: 'v' }[g.grip] || g.grip], e.clientX - g.x, e.clientY - g.y);
        // A size square widens on both sides, about each block's middle.
        delta = { u: { du: m }, v: { dv: m }, w: { dw: 2 * m }, d: { dd: 2 * m } }[g.grip] || {};
        if (g.grip === 'z') up = m;
      }
      const c = g.center;
      // Rotate: the angle swept about the middle, in 5° steps (Shift: 1°). Scale: how much further
      // from the middle the pointer is than where it started.
      const sweep = g.grip === 'rotate' && snapAngle((Math.atan2(p.y - c.y, p.x - c.x) - Math.atan2(g.g0.y - c.y, g.g0.x - c.x)) * 180 / Math.PI, e.shiftKey ? 1 : 5);
      const r0 = g.grip === 'scale' && Math.hypot(g.g0.x - c.x, g.g0.y - c.y);
      if (g.grip === 'scale' && r0 < 0.5) return;
      const k = g.grip === 'scale' && Math.max(0.05, Math.round((Math.hypot(p.x - c.x, p.y - c.y) / r0) * 100) / 100);
      g.moved = true;
      g.copies = new Map();
      for (const q of this.papers) {
        const from = g.from.get(q.id);
        if (!from) continue;
        if (g.copy) {
          const done = copyBlocks(from.blocks, from.indices, delta.du, delta.dv);
          if (done.blocks.length > MAX_BLOCKS) continue; // too many to copy here: left as it was
          q.blocks = done.blocks;
          g.copies.set(q.id, done.indices);
        } else if (g.grip === 'rotate') q.blocks = turnBlocks(from.blocks, from.indices, g.centerUV, sweep);
        else if (g.grip === 'scale') q.blocks = scaleBlocks(from.blocks, from.indices, g.centerUV, k);
        else q.blocks = editBlocks(from.blocks, from.indices, { ...delta, df: up / (q.floor_height || 4.2) });
      }
      if (g.grip === 'rotate') this.say(`회전 ${sweep}°`);
      if (g.grip === 'scale') this.say(`크기 ${k}배`);
      this.drawMasses();
    } else if (g.kind === 'push') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      g.moved = true;
      const p = this.papers.find((q) => q.id === g.id);
      const m = axisDrag(g.axis, e.clientX - g.x, e.clientY - g.y);
      p.blocks = g.before.map((b, i) => (i === g.index ? pushBlock(b, g.face, m, p.floor_height || 4.2) : b));
      const b = p.blocks[g.index];
      this.say(g.face === 'top' ? `${b.floors}층` : `${fmt(g.face[0] === 'w' ? b.w : b.d, 1)} m`);
      this.drawMasses();
    } else if (g.kind === 'rect' || g.kind === 'tape') {
      const p = g.kind === 'tape' ? this.tapePoint(e) : this.ground(e.clientX, e.clientY);
      if (!p) return;
      g.moved = true;
      const frame = this.site?.plan?.frame;
      if (g.kind === 'tape') {
        this.drawDraft([[g.g0.x, g.g0.y, g.g0.z || 0], [p.x, p.y, p.z || 0]], false);
        this.say(`거리 ${fmt(Math.hypot(p.x - g.g0.x, p.y - g.g0.y, (p.z || 0) - (g.g0.z || 0)), 2)} m${this.snapEl.hidden ? '' : ' · 스냅'}`);
        return;
      }
      g.block = rectBlock(frame, g.g0, p);
      const a = toFrame(frame, g.g0.x, g.g0.y);
      const b = toFrame(frame, p.x, p.y);
      this.drawDraft(blockCorners(frame, { u: (a.u + b.u) / 2, v: (a.v + b.v) / 2, w: Math.abs(b.u - a.u), d: Math.abs(b.v - a.v) }), true);
      this.say(`${fmt(Math.abs(b.u - a.u), 1)} × ${fmt(Math.abs(b.v - a.v), 1)} m`);
    } else if (g.kind === 'erase') {
      const key = this.blockAt(e.clientX, e.clientY);
      if (key && !g.keys.has(key)) { g.keys.add(key); this.pickBlocks([...g.keys]); }
    } else if (g.kind === 'box') {
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 4) return;
      g.moved = true;
      g.to = { x: e.clientX, y: e.clientY };
      const r = this.root.getBoundingClientRect();
      const el = this.boxEl;
      el.hidden = false;
      el.classList.toggle('is-crossing', boxMode(g, g.to) === 'crossing');
      Object.assign(el.style, {
        left: `${Math.min(g.x, g.to.x) - r.left}px`, top: `${Math.min(g.y, g.to.y) - r.top}px`,
        width: `${Math.abs(g.to.x - g.x)}px`, height: `${Math.abs(g.to.y - g.y)}px`,
      });
    } else if (g.kind === 'zoom') {
      // Drag up to zoom in, down to zoom out, around the point first pressed.
      this.setView(zoomAround(g.v, g.g0.x, g.g0.y, Math.exp((e.clientY - g.y) * 0.005)));
    } else if (g.kind === 'resize') {
      this.resizeMove(g, e);
    } else if (g.kind === 'move') {
      const p = this.ground(e.clientX, e.clientY);
      if (!g.moved && Math.hypot(e.clientX - g.x, e.clientY - g.y) < 3) return;
      // A paper on the move turns into a small circle under the pointer, which can be dropped
      // into the idea board (2026-11-07 지훈); the screen draws the circle and says when it is over the board.
      g.cx = e.clientX;
      g.cy = e.clientY;
      this.carry(g, this.hooks.carry?.({ x: e.clientX, y: e.clientY, ids: [...g.ids] }));
      if (!p) return;
      g.moved = true;
      const dx = p.x - g.g0.x;
      const dy = p.y - g.g0.y;
      for (const q of this.papers) {
        if (!g.ids.has(q.id)) continue;
        const f = g.from.get(q.id);
        q.x = f.x + dx;
        q.y = f.y + dy;
        if (q.kind === 'tracing' && g.ids.size === 1 && Math.hypot(q.x - this.home.x, q.y - this.home.y) < SNAP) { q.x = this.home.x; q.y = this.home.y; }
        this.gl?.objects.get(q.id)?.position.set(q.x, q.y, q.kind === 'tracing' ? 0.3 : 0.1);
      }
      this.invalidate();
    } else if (g.kind === 'draw') {
      const p = this.ground(e.clientX, e.clientY);
      if (!p) return;
      const pt = [cm(p.x - g.off.x), cm(p.y - g.off.y)];
      const last = g.points[g.points.length - 1];
      if (Math.hypot(pt[0] - last[0], pt[1] - last[1]) < this.view.span / 500) return;
      g.points.push(pt);
      const draft = this.slot(g.id).querySelector('.draft');
      if (draft) draft.setAttribute('d', strokePath(g.points));
      this.invalidate();
    }
  },
  // The moved papers fade while their circle is carried ('carry'); over the idea board ('over')
  // they vanish. The screen answers '' when nothing it can take is moving (the site alone).
  carry(g, answer) {
    const state = g && answer === 'over' ? 'over' : g && answer === 'carry' ? 'on' : '';
    if (g) g.over = state === 'over';
    if (this.carrying === state) return;
    this.carrying = state;
    for (const [id, el] of this.slots) el.classList.toggle('is-carried', Boolean(g?.ids.has(id)) && Boolean(state));
    this.root.classList.toggle('carrying', state === 'on');
    this.root.classList.toggle('carrying-over', state === 'over');
  },
  onUp(cancelled = false) {
    const g = this.gesture;
    this.gesture = null;
    if (g?.kind === 'move') {
      this.carry(null);
      this.hooks.carry?.(null);
      // Dropped on the idea board: the papers go in there and stay where they were on the table
      // until the board comes back without them.
      const ids = [...g.ids].filter((id) => this.papers.some((q) => q.id === id && q.kind !== 'site'));
      if (!cancelled && g.over && ids.length) {
        for (const q of this.papers) {
          const f = g.ids.has(q.id) && g.from.get(q.id);
          if (f) { q.x = f.x; q.y = f.y; this.gl?.objects.get(q.id)?.position.set(q.x, q.y, q.kind === 'tracing' ? 0.3 : 0.1); }
        }
        this.syncPapers();
        this.invalidate();
        if (this.selected.some((id) => ids.includes(id))) this.select(this.selected.filter((id) => !ids.includes(id)));
        this.hooks.stow?.(ids);
        if (!this.gesture && this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
        return;
      }
    }
    if (g?.kind === 'resize') {
      if (cancelled) {
        const p = this.papers.find((x) => x.id === g.id);
        if (p) { Object.assign(p, g.from); this.syncPapers(); }
      } else this.resizeEnd(g);
      if (this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
      return;
    }
    if (cancelled && (g?.kind === 'push' || g?.kind === 'gumball')) {
      const before = g.kind === 'push' ? new Map([[g.id, g.before]]) : new Map([...g.from].map(([id, from]) => [id, from.blocks]));
      for (const paper of this.papers) if (before.has(paper.id)) paper.blocks = before.get(paper.id);
      this.drawMasses();
      if (this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
      return;
    }
    if (g?.kind === 'draw' && g.points.length > 1) {
      const p = this.papers.find((q) => q.id === g.id);
      if (p) {
        this.record([{ op: 'update', id: p.id, before: { strokes: p.strokes || [] }, after: { strokes: [...(p.strokes || []), g.points] } }]);
        p.strokes = [...(p.strokes || []), g.points];
        this.syncPapers();
        this.save(p.id, { strokes: p.strokes });
      }
    } else if (g?.kind === 'gumball' && g.moved) {
      this.saveBlocks(new Map([...g.from].map(([id, f]) => [id, f.blocks])));
      // A copy leaves the copies picked, as in SketchUp.
      if (g.copies?.size) this.pickBlocks([...g.copies].flatMap(([id, indices]) => indices.map((i) => blockKey(id, i))));
    } else if (g?.kind === 'push' && g.moved) {
      this.saveBlocks(new Map([[g.id, g.before]]));
    } else if (numericToolClick(g, cancelled)) {
      this.openToolNumber(g);
    } else if (g?.kind === 'rect') {
      this.gl.draft.clear();
      this.invalidate();
      if (g.block) this.addBlocks([g.block]);
      else if (g.moved) this.say('가로·세로가 1m 이상이 되게 그려 주세요.');
    } else if (g?.kind === 'erase') {
      if (g.keys.size) this.removeBlocks([...g.keys]);
    } else if (g?.kind === 'box') {
      this.boxEl.hidden = true;
      // A box picks the papers and the buildings it holds (or touches); a plain click on empty
      // table picks nothing.
      if (g.moved) {
        const boxes = this.screenBoxes();
        this.pickBlocks(boxPick(this.picked, g, g.to, boxes.blocks, { ...g, limit: Infinity }));
        this.select(boxPick(this.selected, g, g.to, boxes.papers, g));
      } else if (!g.add && !g.remove) {
        if (this.selected.length) this.select([]);
        if (this.picked.length) this.pickBlocks([]);
        if (this.detailId) this.closeDetail();
      }
    } else if (g?.kind === 'move' && g.moved) {
      const edits = [];
      for (const q of this.papers) {
        if (!g.ids.has(q.id)) continue;
        const was = g.from.get(q.id);
        const changes = { x: q.x, y: q.y };
        const before = { x: was.x, y: was.y };
        if (q.kind === 'tracing') { q.overlaid = isOverlaid(q, this.home); changes.overlaid = q.overlaid; before.overlaid = Boolean(was.overlaid); }
        edits.push({ op: 'update', id: q.id, before, after: changes });
        this.save(q.id, changes);
      }
      this.record(edits);
      this.syncPapers();
      if (g.ids.size === 1) {
        const p = this.papers.find((q) => g.ids.has(q.id));
        if (p?.kind === 'tracing') this.say(isOverlaid(p, this.home) ? `${paperName(p)}을(를) 대지 위에 다시 덮었습니다.` : `${paperName(p)}을(를) 떼어냈습니다. 옆에 두고 보거나, 다시 대지 위로 끌어 덮으세요.`);
      }
    }
    // A pin dragged: the click that ends the drag must not open its card.
    if (g?.kind === 'move' && g.pin && g.moved) this.skipClickUntil = performance.now() + 400;
    if (g?.kind === 'move' && !g.moved && !g.shift && !g.pin) {
      // A click on a paper: it alone is picked, and opens at reading size (a note is written in place).
      const p = this.papers.find((q) => q.id === g.id);
      if (p && this.selected.length > 1) this.select([p.id]);
      if (p && p.kind !== 'note') this.inspect(p.id);
    }
    if (g?.kind === 'draw') {
      const draft = this.slot(g.id).querySelector('.draft');
      if (draft) draft.setAttribute('d', '');
    }
    if (!this.gesture && this.pending) { const view = this.pending; this.pending = null; this.setBoard(view); }
  },
  onDouble(e) {
    const id = e.target.closest('[data-paper]')?.dataset.paper;
    const p = this.papers.find((x) => x.id === id);
    if (p?.kind === 'note') { this.editing = id; this.drawPaper(p); }
  },
  onKey(e) {
    if (typing(e.target) || e.target.closest?.('dialog')) return;
    const k = e.key.toLowerCase();
    if ((e.metaKey || e.ctrlKey) && (k === 'z' || k === 'y')) {
      e.preventDefault();
      this.travel(k === 'y' || e.shiftKey ? 'redo' : 'undo');
      return;
    }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && k === 'g') { // group, as in Rhino; with Shift, ungroup
      e.preventDefault();
      const problem = this.groupSelection(!e.shiftKey);
      if (problem) this.say(problem);
      return;
    }
    if ((e.metaKey || e.ctrlKey) && !e.altKey && ['c', 'v', 'a'].includes(k)) {
      // Copy, paste and pick-all work on the blocks, as in SketchUp.
      if (k === 'c' && this.picked.length) { e.preventDefault(); this.copyPicked(); }
      if (k === 'v' && this.clip?.length) { e.preventDefault(); this.pasteClip(); }
      if (k === 'a') { e.preventDefault(); this.pickAll(); }
      return;
    }
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    // No letter or number shortcuts (2026-11-02 지훈): a word typed on the table goes to the
    // command line (app.js). Only Delete and Esc act here.
    if (k === 'delete' || k === 'backspace') { e.preventDefault(); if (this.picked.length) this.removePicked(); else this.removeSelected(); }
    else if (k === 'escape') {
      if (this.detailId) { this.closeDetail(); return; }
      if (this.peekId) { this.peekId = ''; this.drawPins(); this.drawPeek(); return; }
      this.select([]);
      if (this.picked.length) this.pickBlocks([]);
      this.setTool('select');
    }
  }
};
