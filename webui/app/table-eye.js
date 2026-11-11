// 눈높이 보기 (2026-11-09 지훈, made 2026-11-11): stand at a point on the ground, 1.6 m up, and
// see the masses as someone in the street would, the building now on the site hidden. The
// 눈높이 button (or the eye command) asks for the point; then a drag looks about, a click on the
// ground walks there, the arrows walk and turn, the wheel changes the lens, and the bar at the
// top compares the street as it is (지금 건물) with the masses (매스안) and keeps the scene as a
// photo on the table. Esc or a view button goes back to the view it came from.
// Methods of DraftingTable (table.js adds them to its prototype). The numbers are board-model.js's.

import * as THREE from './vendor/three.js';
import { eyeStart, eyeCamera, eyeLook, eyeWalk, eyeZoom, eyeKey, groundAt, freeSpot, PHOTO_SIZES } from './board-model.js';

const wrap = (deg) => ((deg % 360) + 360) % 360;

export const eyeMethods = {
  // The 눈높이 button or the eye command: ask where to stand (again: leave eye level, or stop asking).
  toggleEye() {
    if (this.eye) { this.exitEye(); return; }
    if (this.eyePicking) { this.cancelEyePick(); return; }
    this.eyePicking = true;
    this.root.classList.add('eye-picking');
    this.say(`서서 볼 자리를 누르세요. 그 자리 눈높이(1.6 m)에서 대지를 바라봅니다.${this.aroundOn ? '' : ' 주변 3D를 켜면 주변 건물과 도로가 함께 보입니다.'} Esc는 취소.`);
    this.drawControls();
  },
  cancelEyePick() {
    this.eyePicking = false;
    this.root.classList.remove('eye-picking');
    this.say('');
    this.drawControls();
  },
  // Stand at `point` ({x, y}) facing the middle of the site; the view it came from is kept to go back to.
  enterEye(point) {
    this.eyePicking = false;
    this.root.classList.remove('eye-picking');
    this.tween += 1; // a view still moving stops here
    this.eye = { ...eyeStart(point, { x: 0, y: 0 }, this.view.turn), back: { ...this.view } };
    this.eyeBefore = false; // the masses, the building on the site hidden
    if (this.peekId) { this.peekId = ''; this.drawPeek(); }
    this.root.classList.add('is-eye');
    this.hooks.viewMoved?.();
    this.showAroundParts();
    this.drawEyeBar();
    this.drawControls();
    this.say('끌어서 둘러보고, 땅을 누르면 그리로 갑니다. ↑↓ 걷기 · ←→ 돌기 · 휠 화각 · Esc 나가기');
    this.invalidate();
  },
  // Out of eye level, the view as it is now (setView and the view buttons call this).
  leaveEye() {
    if (!this.eye) return;
    this.eye = null;
    this.root.classList.remove('is-eye');
    this.showAroundParts();
    this.drawEyeBar();
    this.drawControls();
    this.invalidate();
  },
  // Out of eye level, back to the view it came from (Esc, 나가기, the 눈높이 button again).
  exitEye() {
    const back = this.eye?.back;
    this.leaveEye();
    if (back) this.setView(back);
  },
  moveEye(next) {
    if (!this.eye) return;
    this.eye = { ...this.eye, ...next, yaw: wrap(next.yaw ?? this.eye.yaw) };
    const needle = this.ui.tilt.querySelector('.compass span'); // the compass shows which way the eye faces
    if (needle) needle.style.transform = `rotate(${-this.eye.yaw}deg)`;
    this.invalidate();
  },
  // The ground under the eye: the surroundings' ground when shown, else the table.
  eyeGround(x, y) {
    return groundAt(this.aroundOn ? this.around?.terrain : null, x, y);
  },
  aimEye(camera, eye) {
    const c = eyeCamera(eye, this.eyeGround(eye.x, eye.y));
    camera.fov = c.fov;
    camera.near = 0.1;
    camera.far = 6000;
    camera.position.set(...c.position);
    camera.up.set(...c.up);
    camera.lookAt(...c.target);
    camera.updateProjectionMatrix();
    camera.updateMatrixWorld();
  },
  // The ground point under the pointer as the screen now shows it: the surroundings' ground (or
  // the table) and not a building or mass in front of it. null when a building is in the way or
  // the pointer is on the sky.
  eyeHit(clientX, clientY) {
    if (!this.gl) return null;
    const { camera, around, masses, raycaster } = this.gl;
    const r = this.root.getBoundingClientRect();
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    around.updateMatrixWorld(true);
    masses.updateMatrixWorld(true);
    const solid = (o) => o.isMesh && o.visible && (o.userData.part === 'ground' || o.userData.building);
    const targets = [...(around.visible ? around.children.filter(solid) : []), ...(masses.visible ? masses.children : [])];
    const hit = raycaster.intersectObjects(targets, true).find((h) => h.object.isMesh);
    if (hit) return hit.object.userData.part === 'ground' ? { x: hit.point.x, y: hit.point.y } : null;
    const flat = new THREE.Vector3();
    return raycaster.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 0, 1), 0), flat) ? { x: flat.x, y: flat.y } : null;
  },
  // An arrow key ({ahead, turn}, board-model eyeKey).
  stepEye(move) {
    const turned = { ...this.eye, yaw: this.eye.yaw + move.turn };
    this.moveEye(move.ahead ? eyeWalk(turned, move.ahead) : turned);
  },
  lookEye(from, dx, dy) {
    this.moveEye(eyeLook(from, dx, dy));
  },
  zoomEye(factor) {
    this.moveEye(eyeZoom(this.eye, factor));
  },
  // The bar along the top while at eye level.
  drawEyeBar() {
    const bar = this.ui.eye;
    bar.hidden = !this.eye;
    if (!this.eye) { bar.innerHTML = ''; return; }
    const pressed = (before) => String(this.eyeBefore === before);
    bar.innerHTML = `<span class="eye-title">눈높이 1.6 m</span>
      <div class="seg" role="group" aria-label="전후 비교">
        <button type="button" data-eye="before" aria-pressed="${pressed(true)}" title="대지에 지금 있는 건물을 보이고 매스안을 숨깁니다">지금 건물</button>
        <button type="button" data-eye="after" aria-pressed="${pressed(false)}" title="지금 건물을 숨기고 매스안을 세웁니다">매스안</button>
      </div>
      <button type="button" data-eye="save" title="이 장면을 사진으로 제도판에 올립니다">장면 저장</button>
      <button type="button" data-eye="exit" title="들어오기 전 보기로 돌아갑니다 (Esc)">나가기</button>`;
  },
  eyeAction(action) {
    if (action === 'exit') { this.exitEye(); return; }
    if (action === 'save') { this.saveEyeScene(); return; }
    this.eyeBefore = action === 'before';
    this.showAroundParts();
    this.drawEyeBar();
    this.invalidate();
  },
  // The scene as it is on the screen, as a photo beside the site (no pins or controls on it).
  saveEyeScene() {
    if (!this.gl || !this.eye) return;
    this.render();
    const time = new Date().toTimeString().slice(0, 5).replace(':', '');
    const name = `눈높이 ${this.eyeBefore ? '지금' : '매스안'} ${time}.png`;
    // Read in the same task as the frame was drawn, before the browser clears the drawing buffer.
    this.gl.renderer.domElement.toBlob((blob) => {
      if (!blob) { this.say('장면을 저장하지 못했습니다. 다시 눌러 주세요.'); return; }
      const side = PHOTO_SIZES.medium;
      this.addPhotos([new File([blob], name, { type: 'image/png' })], freeSpot(this.papers, this.bounds, side, side));
    }, 'image/png');
  },
};
