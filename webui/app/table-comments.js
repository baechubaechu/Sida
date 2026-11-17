// Comments from a share (공유) standing on the table as numbered pins where the viewer put them
// (share.js gives them; a comment without a spot has no pin). A pin opens the share window at its
// comment (hook `comment`). The pins only show; nothing here changes the table.
import * as THREE from './vendor/three.js';
import { escapeHtml as escape } from './model.js';
import { riseFor } from './board-model.js';

export const commentsMethods = {
  // pins: [{id, number, at {x, y, z}, resolved, unread, author, text}]
  setComments(pins) {
    this.comments = pins || [];
    this.commentsDrawn = '';
    this.invalidate?.();
  },
  commentLayer() {
    if (!this.commentEl) {
      const layer = document.createElement('div');
      layer.className = 'comment-pins';
      layer.addEventListener('pointerdown', (e) => { if (e.target.closest('.comment-pin')) e.stopPropagation(); });
      layer.addEventListener('click', (e) => {
        const pin = e.target.closest('.comment-pin');
        if (pin) { e.stopPropagation(); this.hooks.comment?.(pin.dataset.comment); }
      });
      this.root.insertBefore(layer, this.snapEl);
      this.commentEl = layer;
    }
    return this.commentEl;
  },
  // Placed on every frame, where the camera sees each comment's spot.
  placeComments() {
    if (!this.gl || (!this.comments?.length && !this.commentEl)) return;
    const layer = this.commentLayer();
    const rise = this.eye ? 1 : riseFor(this.view.tilt);
    const w = this.size?.w || this.root.clientWidth;
    const h = this.size?.h || this.root.clientHeight;
    const html = [];
    for (const c of this.comments || []) {
      const v = new THREE.Vector3(c.at.x, c.at.y, (c.at.z || 0) * rise).project(this.gl.camera);
      if (v.z > 1 || v.z < -1) continue;
      const x = ((v.x + 1) / 2) * w;
      const y = ((1 - v.y) / 2) * h;
      if (x < -40 || x > w + 40 || y < -40 || y > h + 40) continue;
      const state = c.resolved ? ' resolved' : c.unread ? ' unread' : '';
      const label = `댓글 ${c.number}: ${c.author}${c.unread ? ', 새로 옴' : ''}${c.resolved ? ', 해결됨' : ''}`;
      html.push(`<button type="button" class="comment-pin${state}" data-comment="${escape(c.id)}" style="transform: translate(${x.toFixed(1)}px, ${y.toFixed(1)}px)" aria-label="${escape(label)}" title="${escape(`${c.author}: ${c.text}`.slice(0, 120))}">${c.number}</button>`);
    }
    const out = html.join('');
    if (this.commentsDrawn !== out) { layer.innerHTML = out; this.commentsDrawn = out; }
  },
  // "제도판에서 보기": the view turns to the comment's spot, and its pin flashes.
  showComment(id) {
    const c = (this.comments || []).find((p) => p.id === id);
    if (!c) return;
    this.animateTo({ x: c.at.x, y: c.at.y, z: 0 });
    setTimeout(() => this.commentEl?.querySelector(`[data-comment="${CSS.escape(id)}"]`)?.classList.add('flash'), 500);
  },
};
