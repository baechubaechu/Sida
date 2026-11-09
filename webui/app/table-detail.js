// One paper at reading size: its plan drawing, its content, its actions, the note editor. Shown
// under the 속성 panel (2026-11-09 지훈: no window coming out beside the table on a click); the
// old window (`drawDetail`) is not opened any more.
// Methods of DraftingTable (table.js adds them to its prototype).

import { escapeHtml as escape } from './model.js';
import { isOverlaid, paperName, resultPreview, originLabel, toggleSelected, fmt, planDrawing, PHOTO_SIZES, isPdfPaper, pdfCanvasSize } from './board-model.js';
import { DETAIL_KINDS } from './table-shared.js';

export const detailMethods = {
  // ------------------------------------------------------------------ the detail panel
  // A click on a paper (or its 상세 보기) opens it at reading size beside the table, whatever the
  // zoom: the site plan with the scheme drawn on it, the figures, a note to write in. The table
  // stays as it is beside it, neither dimmed nor blocked (2026-11-07 지훈): a click on another
  // paper shows that one, a click on empty table, × or Esc closes it.

  // "상세 보기": the paper is selected and the 속성 panel brought on screen, where it shows whole.
  inspect(id) {
    if (!this.find(id)) return;
    if (!this.selected.includes(id) || this.selected.length > 1) this.select([id]);
    this.hooks.showProps?.();
  },
  // The paper's content and actions for the 속성 panel (buttons: data-action="paper-detail",
  // data-detail, data-id; app.js passes them to detailActionFor).
  detailHtml(id) {
    const p = this.find(id);
    if (!p) return '';
    const { why, body, actions } = this.detailParts(p, (action) => `data-action="paper-detail" data-detail="${action}" data-id="${escape(p.id)}"`, { panel: true });
    return `<section class="prop-content kind-${escape(p.kind)}" aria-label="${escape(paperName(p))} 내용">${why}${body}
      <div class="prop-actions">${actions}<button type="button" class="prop-ask" data-action="paper-detail" data-detail="ask" data-id="${escape(p.id)}">이 종이로 질문하기 →</button></div></section>`;
  },
  detailActionFor(id, action) {
    const p = this.find(id);
    if (!p) return;
    switch (action) {
      case 'show': this.showScheme(id); this.showView('3d'); break;
      case 'edit': this.openForm(p); break;
      case 'write': this.setFolded(id, false); this.planAt(p, () => { this.editing = id; this.select([id]); this.drawPaper(p); }); break;
      case 'unfold': this.setFolded(id, false); break;
      case 'focus': this.planAt(p); this.select([id]); break;
      case 'size-small': case 'size-medium': case 'size-large': this.resizePhoto(id, PHOTO_SIZES[action.slice(5)]); break;
      case 'page-prev': case 'page-next': this.turnPage(id, action === 'page-next' ? 1 : -1); break;
      case 'place': this.placeFromTray(id); break;
      case 'open-expert': this.hooks.openExpert(p.agent || ''); break;
      case 'ask': if (!this.selected.includes(id)) this.select(toggleSelected(this.selected, id, true)); this.hooks.ask?.(id); break;
      default: break;
    }
  },
  inspectInWindow(id) {
    if (!this.find(id)) return;
    if (this.detailId && this.detailId !== id) this.saveDetailNote();
    this.detailId = id;
    if (this.peekId) { this.peekId = ''; this.drawPins(); this.drawPeek(); }
    this.drawDetail();
    const dialog = this.ui.detail;
    if (!dialog.open) {
      if (typeof dialog.show === 'function') dialog.show();
      else dialog.setAttribute('open', '');
      // Opening it does not take the keyboard from the table (Delete, Ctrl+Z, a typed command).
      this.root.focus({ preventScroll: true });
    }
  },
  closeDetail() {
    this.saveDetailNote();
    this.detailId = '';
    const dialog = this.ui.detail;
    if (dialog.open) dialog.close();
  },
  planSvg(plan) {
    if (!plan) return '';
    const [x0, top, width] = plan.viewBox.split(' ').map(Number);
    const font = Math.max(1.4, plan.size / 42);
    return `<svg class="plan" viewBox="${plan.viewBox}" role="img" aria-label="배치도" style="font-size:${font.toFixed(2)}px">
      ${plan.lots.map((d) => `<path class="lot" d="${d}"/>`).join('')}
      ${plan.blocks.map((b) => `<path class="footprint" d="${b.d}"/><text class="floors" x="${b.x}" y="${b.y}">${escape(String(b.floors))}F</text>`).join('')}
      <g class="north" transform="translate(${(x0 + width - font * 1.6).toFixed(2)} ${(top + font * 2).toFixed(2)})"><path d="M0 ${-font} L${font * 0.6} ${font * 0.6} L0 ${font * 0.2} L${-font * 0.6} ${font * 0.6} Z"/><text y="${font * 1.9}">N</text></g>
      <g class="scalebar"><path d="M${plan.scale.x} ${plan.scale.y} h${plan.scale.length}"/><text x="${plan.scale.x + plan.scale.length / 2}" y="${plan.scale.y - font * 0.6}">${escape(plan.scale.label)}</text></g>
    </svg>`;
  },
  drawDetail() {
    const dialog = this.ui.detail;
    const p = this.find(this.detailId);
    if (!p) { dialog.innerHTML = ''; return; }
    const onTable = this.papers.some((x) => x.id === p.id);
    const made = originLabel(p, this.hooks.experts());
    const where = [DETAIL_KINDS[p.kind] || p.kind, made, onTable ? '' : 'AI 섹션'].filter(Boolean).join(' · ');
    const { why, body, actions } = this.detailParts(p, (action) => `data-detail="${action}"`);
    dialog.innerHTML = `<header class="detail-head"><div><span class="eyebrow">${escape(where)}</span><h2 id="detail-title">${escape(p.kind === 'site' ? '대지 사실' : paperName(p))}</h2></div>
        <button type="button" class="detail-close" data-detail="close" aria-label="상세 보기 닫기">×</button></header>
      <div class="detail-body kind-${escape(p.kind)}">${why}${body}</div>
      <footer class="detail-actions"><div class="detail-more">${actions}</div>
        <button type="button" class="detail-primary" data-detail="ask">이 종이로 질문하기 →</button></footer>`;
    this.detailPdf(p, dialog);
  },
  // What a paper shows at reading size: why it was made (an AI paper), its body and its actions.
  // `on(action)`: the attributes that make a button do `action` where it is shown.
  // `panel`: in the 속성 panel, where the name has its own field and a note is written on the table.
  detailParts(p, on, { panel = false } = {}) {
    const id = escape(p.id);
    const onTable = this.papers.some((x) => x.id === p.id);
    let body = '';
    if (p.kind === 'site') {
      body = `${this.planSvg(planDrawing(this.site))}${this.paperContent(p, false, null, true).body}`;
    } else if (p.kind === 'mass') {
      body = `${this.planSvg(planDrawing(this.site, p))}${this.paperContent(p, this.active === p.id, this.figures[p.id], true).body}
        <p class="detail-caption">층고 ${escape(fmt(p.floor_height ?? 4.2, 1))}m · 수치는 서버가 대지 사실로 계산한 값입니다</p>`;
    } else if (p.kind === 'expert') {
      body = `<pre class="preview">${escape(resultPreview(p.text))}</pre>
        <button type="button" class="paper-link" ${on('open-expert')}>결과 문서 보기 ↗</button>`;
    } else if (p.kind === 'note') {
      body = panel ? `<p class="note-text">${escape(p.text || '메모')}</p>` : onTable
        ? `<label class="detail-note">메모 내용<textarea data-detail-note="${id}" maxlength="4000">${escape(p.text || '')}</textarea></label>`
        : `<p class="note-text">${escape(p.text || '메모')}</p>`;
    } else if (p.kind === 'tracing') {
      body = `<div class="detail-tracing">${this.traceSvg(p)}</div><p class="detail-caption">그린 선 ${(p.strokes || []).length}개${isOverlaid(p, this.home) ? ' · 대지 위에 덮여 있음' : ''}</p>`;
    } else if (p.kind === 'photo') {
      const longest = Math.max(p.w, p.h);
      const pdf = isPdfPaper(p);
      const url = this.hooks.photoUrl(p.id);
      const sizes = Object.entries({ small: '작게', medium: '보통', large: '크게' }).map(([key, label]) => `<button type="button" ${on(`size-${key}`)} aria-pressed="${Math.round(longest) === PHOTO_SIZES[key]}">${label}</button>`).join('');
      const pages = pdf ? this.pdfPages.get(url) : 0;
      const pager = pages > 1 ? `<div class="detail-sizes detail-pages" role="group" aria-label="PDF 페이지"><span>페이지</span>
          <button type="button" ${on('page-prev')} aria-label="앞 페이지" ${p.page > 1 ? '' : 'disabled'}>‹</button>
          <b>${escape(String(Math.min(p.page || 1, pages)))} / ${escape(String(pages))}</b>
          <button type="button" ${on('page-next')} aria-label="다음 페이지" ${(p.page || 1) < pages ? '' : 'disabled'}>›</button></div>` : '';
      body = `<a class="detail-photo" href="${escape(url)}" target="_blank" rel="noopener" title="원본을 새 탭에서 보기">${pdf
        ? `<div class="pdf-page" role="img" aria-label="${escape(paperName(p))}"></div>` : `<img src="${escape(url)}" alt="${escape(paperName(p))}">`}</a>
        ${pdf ? `<p class="detail-caption">PDF는 보이는 크기에 맞춰 다시 그려서, 카드를 키워도 선이 흐려지지 않습니다. 눌러서 원본 PDF를 새 탭에서 볼 수 있습니다.</p>${pager}` : ''}
        ${panel ? '' : `<label class="detail-title">${pdf ? 'PDF 이름' : '사진 이름'}<input type="text" data-detail-title="${id}" maxlength="120" value="${escape(p.title || '')}" placeholder="예: 북측 도로에서 본 대지"></label>`}
        <div class="detail-sizes" role="group" aria-label="제도판 위 크기"><span>제도판 위 크기</span>${sizes}</div>
        <p class="detail-caption">AI에게는 ${pdf ? 'PDF' : '사진'} 이름만 갑니다. 무엇이 있는지는 질문에 적어 주세요.</p>`;
    }
    const why = [p.based_on ? `${paperName(this.find(p.based_on)) || p.based_on}의 수정안` : '', p.reason || ''].filter(Boolean)
      .map((t) => `<p class="detail-caption">${escape(t)}</p>`).join('');
    const actions = [
      p.kind === 'mass' && onTable && this.active !== p.id ? `<button type="button" ${on('show')}>3D로 세우기</button>` : '',
      p.kind === 'mass' && onTable ? `<button type="button" ${on('edit')}>고치기</button>` : '',
      p.kind === 'note' && onTable && panel ? `<button type="button" ${on('write')}>제도판에서 고치기</button>` : '',
      p.folded ? `<button type="button" ${on('unfold')}>펴기</button>` : '',
      onTable ? `<button type="button" ${on('focus')}>제도판에서 크게 보기</button>` : `<button type="button" ${on('place')}>제도판에 놓기</button>`,
    ].join('');
    return { why, body, actions };
  },
  // A PDF page drawn into a paper shown at reading size (in the window or the 속성 panel).
  detailPdf(p, host) {
    const dialog = host;
    const page = isPdfPaper(p) && dialog.querySelector('.pdf-page');
    if (page) {
      const across = Math.max(240, (dialog.clientWidth || 480) - 50);
      this.showPdf(page, `detail:${p.id}`, p, pdfCanvasSize(p.w, p.h, across / p.w, window.devicePixelRatio))
        .then((pages) => { if (pages > 1 && !dialog.querySelector('.detail-pages')) this.hooks.pdfPages?.(p.id); });
    }
  },
  detailAction(action) {
    const id = this.detailId;
    const p = this.find(id);
    if (action === 'close' || !p) { this.closeDetail(); return; }
    switch (action) {
      case 'show': this.showScheme(id); this.drawDetail(); this.showView('3d'); break;
      case 'edit': this.closeDetail(); this.openForm(p); break;
      case 'unfold': this.setFolded(id, false); this.drawDetail(); break;
      case 'focus': this.closeDetail(); this.planAt(p); this.select([id]); break;
      case 'size-small': case 'size-medium': case 'size-large': this.resizePhoto(id, PHOTO_SIZES[action.slice(5)]); break;
      case 'page-prev': case 'page-next': this.turnPage(id, action === 'page-next' ? 1 : -1); break;
      case 'place': this.closeDetail(); this.placeFromTray(id); break;
      case 'ask': this.closeDetail(); if (!this.selected.includes(id)) this.select(toggleSelected(this.selected, id, true)); this.hooks.ask?.(id); break;
      default: break;
    }
  },
  // A note written in the detail panel is saved when it loses focus or the panel closes.
  saveDetailNote() {
    const area = this.ui.detail.querySelector('[data-detail-note]');
    if (area) this.saveNoteText(area.dataset.detailNote, area.value);
    const title = this.ui.detail.querySelector('[data-detail-title]');
    if (title) this.saveTitle(title.dataset.detailTitle, title.value);
  }
};
