// 사람 배치 (2026-11-10 지훈 "사람 배치해보는 기능", 2026-11-11 "제도판 3D부터"): scale figures
// stood about the site, to feel how large a scheme is. The 사람 tool (command people) stands one
// where the ground or a roof of the scheme is clicked; its options beside it in the tool bar pick
// what kind, scatter a dozen around the site, turn or take away the picked one, and clear them all. In plan a person
// is a 0.5 m circle with a notch toward where they look; as the table leans they stand up as low-poly
// figures (1.7 m, a child 1.1 m), on the ground of the surroundings when shown, or on the roof of the
// scheme's building under them (they follow its floors). Saved as one list (hooks.savePeople, PUT
// .../board/people), kept for undo; the screen only, never sent to the AI.
// Methods of DraftingTable (table.js adds them to its prototype). The rules are board-model.js's.

import * as THREE from './vendor/three.js';
import { PERSON_KINDS, MAX_PEOPLE, personId, blockUnder, nearestBlock, personNote, scatterSpots, blockCorners } from './board-model.js';

const rad = (d) => (d * Math.PI) / 180;
const wrap = (deg) => ((deg % 360) + 360) % 360;

// The shapes every figure shares (made once): limbs along z, about 1.7 m tall in all.
let kit = null;
function figureKit() {
  if (kit) return kit;
  const mark = new THREE.Shape();
  mark.absarc(0, 0, 0.25, 0, Math.PI * 2, false);
  const notch = new THREE.Shape([new THREE.Vector2(0, 0.48), new THREE.Vector2(-0.13, 0.27), new THREE.Vector2(0.13, 0.27)]);
  kit = {
    leg: new THREE.CylinderGeometry(0.07, 0.055, 0.85, 7).rotateX(Math.PI / 2),
    torso: new THREE.CylinderGeometry(0.175, 0.14, 0.62, 9).rotateX(Math.PI / 2),
    arm: new THREE.CylinderGeometry(0.045, 0.038, 0.6, 6).rotateX(Math.PI / 2),
    head: new THREE.IcosahedronGeometry(0.105, 1),
    mark: new THREE.ShapeGeometry([mark, notch]),
  };
  return kit;
}

// A limb hanging from its joint at (x, 0, z), swung forward by `swing` radians.
function limb(geometry, material, x, z, length, swing) {
  const joint = new THREE.Group();
  joint.position.set(x, 0, z);
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.z = -length / 2;
  mesh.castShadow = true;
  joint.add(mesh);
  joint.rotation.x = swing;
  return joint;
}

// A figure facing +y (north) with its feet at the origin.
function figure(kind, material) {
  const k = figureKit();
  const g = new THREE.Group();
  const swing = kind === 'walk' ? 0.38 : 0;
  g.add(limb(k.leg, material, 0.09, 0.85, 0.85, swing), limb(k.leg, material, -0.09, 0.85, 0.85, -swing));
  const torso = new THREE.Mesh(k.torso, material);
  torso.position.z = 1.16;
  torso.scale.y = 0.62; // flatter front to back
  torso.castShadow = true;
  g.add(torso);
  g.add(limb(k.arm, material, 0.215, 1.44, 0.6, -swing * 0.8), limb(k.arm, material, -0.215, 1.44, 0.6, swing * 0.8));
  const head = new THREE.Mesh(k.head, material);
  head.position.z = 1.6;
  head.castShadow = true;
  if (kind === 'child') { head.scale.setScalar(1.22); head.position.z = 1.62; } // a child's head is larger for their height
  g.add(head);
  g.scale.setScalar((PERSON_KINDS[kind] || PERSON_KINDS.stand).height / 1.7);
  return g;
}

export const peopleMethods = {
  // The list from the server (GET board), unless a person is being dragged.
  setPeopleList(list) {
    this.people = (list || []).map((p) => ({ ...p }));
    if (this.personPicked && !this.people.some((p) => p.id === this.personPicked)) this.personPicked = '';
    this.drawPeople();
    this.drawPersonBar();
  },
  // The scheme standing on the site: its paper and the site's frame.
  shownScheme() {
    const paper = this.papers.find((p) => p.id === this.active && p.kind === 'mass');
    return { paper, frame: this.site?.plan?.frame || { x: 0, y: 0, angle: 0 } };
  },
  // How high a person's feet are: on the roof of the scheme's building under them, else the ground.
  personBase(p) {
    if (p.roof) {
      const { paper, frame } = this.shownScheme();
      const index = paper ? blockUnder(frame, paper.blocks, p.x, p.y) : -1;
      if (index >= 0) {
        const b = paper.blocks[index];
        return this.blockBase(frame, b) + b.floors * (paper.floor_height || 4.2);
      }
    }
    return this.eyeGround(p.x, p.y);
  },
  drawPeople() {
    if (!this.gl) return;
    const { people, peopleMarks } = this.gl;
    people.clear();
    peopleMarks.clear();
    const m = this.gl.personMaterials || (this.gl.personMaterials = {
      body: new THREE.MeshLambertMaterial({ color: this.colors.person }),
      bodyPick: new THREE.MeshLambertMaterial({ color: this.colors.pick }),
      mark: new THREE.MeshBasicMaterial({ color: this.colors.person, depthTest: false, transparent: true }),
      markPick: new THREE.MeshBasicMaterial({ color: this.colors.pick, depthTest: false, transparent: true }),
    });
    for (const p of this.people) {
      const picked = p.id === this.personPicked;
      const z = this.personBase(p);
      const body = figure(p.kind, picked ? m.bodyPick : m.body);
      body.position.set(p.x, p.y, z);
      body.rotation.z = -rad(p.turn || 0); // turn is clockwise from north
      body.traverse((o) => { o.userData.person = p.id; });
      people.add(body);
      const mark = new THREE.Mesh(figureKit().mark, picked ? m.markPick : m.mark);
      mark.position.set(p.x, p.y, z + 0.1);
      mark.rotation.z = -rad(p.turn || 0);
      mark.renderOrder = 5; // over the ground and the lot in plan
      mark.userData.person = p.id;
      peopleMarks.add(mark);
    }
    this.invalidate();
  },
  // The person under the pointer (as the screen now shows them), or ''.
  personAt(clientX, clientY) {
    if (!this.gl || !this.people.length) return '';
    const { camera, people, peopleMarks, raycaster } = this.gl;
    const group = people.visible ? people : peopleMarks;
    if (!group.visible) return '';
    const r = this.root.getBoundingClientRect();
    group.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    return raycaster.intersectObjects(group.children, true)[0]?.object.userData.person || '';
  },
  // Where a click stands a person: {x, y} on the ground, {x, y, roof} on a roof of the scheme,
  // {wall} on a wall (nobody stands there), or null off the table.
  personSpot(clientX, clientY) {
    if (!this.gl) return null;
    const { camera, around, masses, raycaster } = this.gl;
    const r = this.root.getBoundingClientRect();
    around.updateMatrixWorld(true);
    masses.updateMatrixWorld(true);
    raycaster.setFromCamera(new THREE.Vector2(((clientX - r.left) / r.width) * 2 - 1, -((clientY - r.top) / r.height) * 2 + 1), camera);
    const solid = (o) => o.isMesh && o.visible && (o.userData.part === 'ground' || o.userData.building);
    const targets = [...(around.visible ? around.children.filter(solid) : []), ...(masses.visible ? masses.children.filter((o) => o.isMesh) : [])];
    const hit = raycaster.intersectObjects(targets, false)[0];
    if (hit && hit.object.userData.part === 'ground') return { x: hit.point.x, y: hit.point.y };
    if (hit && hit.object.userData.paper) {
      return (hit.face?.normal.z || 0) > 0.7 ? { x: hit.point.x, y: hit.point.y, roof: true } : { wall: true };
    }
    if (hit) return { wall: true }; // a building around the site
    return this.ground(clientX, clientY);
  },
  // Replace the list, kept for undo and saved.
  changePeople(next) {
    const before = this.people;
    this.people = next;
    if (this.personPicked && !next.some((p) => p.id === this.personPicked)) this.personPicked = '';
    this.record([{ op: 'people', before, after: next }]);
    this.drawPeople();
    this.drawPersonBar();
    this.hooks.savePeople?.(next);
  },
  addPersonAt(spot) {
    if (this.people.length >= MAX_PEOPLE) { this.say(`사람은 ${MAX_PEOPLE}명까지 세울 수 있습니다.`); return; }
    const kind = this.personKind || 'stand';
    // Facing into the view, a little to one side, so the first one is not seen from behind.
    const turn = Math.round(wrap(this.view.turn + 180 + (Math.random() - 0.5) * 60));
    const p = { id: personId(), x: Math.round(spot.x * 100) / 100, y: Math.round(spot.y * 100) / 100, turn, kind, ...(spot.roof ? { roof: true } : {}) };
    this.personPicked = p.id;
    this.changePeople([...this.people, p]);
    this.tellPerson(p);
  },
  pickPerson(id) {
    if (id === this.personPicked) return;
    this.personPicked = id;
    if (id) {
      if (this.selected.length) this.select([]);
      if (this.picked.length) this.pickBlocks([]);
      this.tellPerson(this.people.find((p) => p.id === id));
    }
    this.drawPeople();
    this.drawPersonBar();
  },
  // Say how tall the person is next to the nearest building of the scheme.
  tellPerson(p) {
    if (!p) return;
    const { paper, frame } = this.shownScheme();
    const near = paper && nearestBlock(frame, paper.blocks, p.x, p.y);
    this.say(personNote(p, near && near.gap < 80 ? paper.blocks[near.index] : null, paper?.floor_height || 4.2));
  },
  turnPickedPerson(by) {
    const id = this.personPicked;
    if (!id) return;
    this.changePeople(this.people.map((p) => (p.id === id ? { ...p, turn: Math.round(wrap((p.turn || 0) + by)) } : p)));
  },
  removePickedPerson() {
    const id = this.personPicked;
    if (!id) return false;
    this.personPicked = '';
    this.changePeople(this.people.filter((p) => p.id !== id));
    return true;
  },
  // A dozen people on open ground in and around the site (board-model scatterSpots).
  scatterPeople() {
    const rings = (this.site?.plan?.parcels || []).flatMap((parcel) => parcel.rings || []);
    if (!rings.length) { this.say('대지가 있어야 주변에 사람을 뿌릴 수 있습니다.'); return; }
    const { paper, frame } = this.shownScheme();
    const obstacles = [
      ...(paper?.blocks || []).map((b) => blockCorners(frame, b)),
      ...(this.aroundOn ? (this.around?.buildings || []).map((b) => b.outline) : []),
    ];
    const room = MAX_PEOPLE - this.people.length;
    const spots = scatterSpots({ rings, obstacles, terrain: this.aroundOn ? this.around?.terrain : null, people: this.people, count: Math.min(12, room) });
    if (!spots.length) { this.say(room ? '빈 땅을 찾지 못했습니다. 대지 주변이 건물로 차 있습니다.' : `사람은 ${MAX_PEOPLE}명까지 세울 수 있습니다.`); return; }
    this.changePeople([...this.people, ...spots.map((s) => ({ id: personId(), ...s }))]);
    this.say(`${spots.length}명을 대지 주변 빈 땅에 세웠습니다.${this.aroundOn ? '' : ' 주변 3D를 켜고 뿌리면 차도를 피해 세웁니다.'}`);
  },
  clearPeople() {
    if (!this.people.length) return;
    const n = this.people.length;
    this.changePeople([]);
    this.say(`사람 ${n}명을 치웠습니다. 되돌리기(Ctrl+Z)로 다시 세울 수 있습니다.`);
  },
  // The 사람 tool's options, in the tool bar beside its button (table.js drawControls): what kind
  // to stand next, and what to do at once.
  personOptions() {
    const kind = this.personKind || 'stand';
    const has = Boolean(this.personPicked);
    return `<span class="person-options" role="group" aria-label="사람 배치">
      <div class="seg" role="group" aria-label="세울 사람">
        ${Object.entries(PERSON_KINDS).map(([id, k]) => `<button type="button" data-person-kind="${id}" aria-pressed="${kind === id}" title="${k.label} ${k.height} m">${k.short}</button>`).join('')}
      </div>
      <button type="button" data-person="scatter" title="대지 안과 둘레 15 m의 빈 땅에 12명을 세웁니다">주변에 뿌리기</button>
      <button type="button" data-person="turn" ${has ? '' : 'disabled'} title="고른 사람을 45° 돌립니다">돌리기</button>
      <button type="button" data-person="remove" ${has ? '' : 'disabled'} title="고른 사람을 치웁니다 (Delete)">지우기</button>
      <button type="button" data-person="clear" ${this.people.length ? '' : 'disabled'} title="세운 사람 ${this.people.length}명을 모두 치웁니다 (되돌리기 가능)">모두 치우기</button></span>`;
  },
  // The options follow the picked person and the count.
  drawPersonBar() {
    if (this.tool === 'person' && this.ui) this.drawControls();
  },
  personAction(action) {
    if (action === 'scatter') this.scatterPeople();
    else if (action === 'turn') this.turnPickedPerson(45);
    else if (action === 'remove') this.removePickedPerson();
    else if (action === 'clear') this.clearPeople();
  },
};
