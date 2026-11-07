// Inside vworld3d.html: VWorld's own WebGL 3D map (vw.Map on Cesium) with the board's masses on it.
// The board (vworld-view.js) drives it through window.sidaVWorld (same origin). Only VWorld's
// official API is used; none of its tiles or models are read out or kept. What the board keeps
// (PUT .../board/hidden) is the list of VWorld buildings the designer hid, by model id (MODEL_NAME).
//
// A click picks a building (tinted yellow); the board asks before hiding it, and keeps the hiding
// steps for Ctrl+Z. Keys pressed while the map has the focus go to the board too.
/* global vw, ws3d, Cesium */
(function () {
  'use strict';
  const MASS = '#f08a24'; // orange: stands out from VWorld's glass and concrete
  const WHITE = '#e9e9e6'; // buildings as a white model: VWorld's photo textures replaced by one colour
  const PICKED = '#ffd23f'; // the building picked for hiding
  const GROUND = '#cfd3cf'; // the ground without the aerial photo
  const NAMES = 'POI_GROUP'; // VWorld's layer of place and building names (명칭)
  const state = {
    hidden: new Set(), picked: '', masses: [], version: 0, ready: false, failed: '',
    look: { white: false, plain: false, noNames: false }, onPick: null, onKey: null,
  };
  // where the map starts: the site's middle, from the board (after #), seen from the south
  const start = new URLSearchParams(location.hash.slice(1));
  const site = { lon: Number(start.get('lon')) || 126.978, lat: Number(start.get('lat')) || 37.566 };
  const VIEW = { height: 190, pitch: -32 };
  const south = (height, pitch) => (height / Math.tan((-pitch * Math.PI) / 180)) / 110540; // degrees of latitude
  let map = null;
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });

  if (typeof vw === 'undefined') {
    state.failed = '브이월드 3D 지도를 불러오지 못했습니다. 인터넷 연결과 브이월드 키를 확인하세요.';
    resolveReady(false);
  } else {
    map = new vw.Map();
    map.setOption({
      mapId: 'map',
      initPosition: new vw.CameraPosition(new vw.CoordZ(site.lon, site.lat - south(VIEW.height, VIEW.pitch), VIEW.height),
        new vw.Direction(0, VIEW.pitch, 0)),
      logo: true, navigation: true,
    });
    map.start();
    vw.ws3dInitCallBack = function () {
      const viewer = ws3d.viewer;
      viewer.screenSpaceEventHandler.setInputAction((movement) => {
        pick(modelId(viewer.scene.pick(movement.position))); // empty ground or a mass: nothing picked
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      watchTilesets(viewer);
      state.ready = true;
      resolveReady(true);
    };
  }

  // Keys pressed while the map has the focus: the board decides (Esc, Delete, Ctrl+Z ...).
  document.addEventListener('keydown', (e) => {
    if (state.onKey && state.onKey({ key: e.key, ctrl: e.ctrlKey, meta: e.metaKey, shift: e.shiftKey })) {
      e.preventDefault();
      e.stopPropagation();
    }
  }, true);

  function modelId(picked) {
    if (!(picked instanceof Cesium.Cesium3DTileFeature)) return '';
    const id = picked.getProperty('MODEL_NAME') || picked.getProperty('TD_ID');
    return id ? String(id) : '';
  }

  function redraw() {
    state.version += 1; // the tiles in view are gone over again
    ws3d.viewer.scene.requestRender();
  }

  function pick(id) {
    if (id === state.picked) return;
    state.picked = id;
    redraw();
    if (state.onPick) state.onPick(id);
  }

  // Each building tileset, as its tiles come into view: hide the buildings on the hidden list,
  // tint the picked one, and colour them all white in the white-model look. VWorld's tiles come
  // and go, so this runs per visible tile (a tileset style would show hidden buildings again).
  function watchTilesets(viewer) {
    const seen = new Set();
    const attach = () => {
      for (const p of viewer.scene.primitives._primitives || []) {
        if (!(p instanceof Cesium.Cesium3DTileset) || seen.has(p)) continue;
        seen.add(p);
        p.colorBlendMode = blendMode();
        p.tileVisible.addEventListener((tile) => {
          const c = tile.content;
          if (!c || c._sidaVersion === state.version || !c.featuresLength) return;
          c._sidaVersion = state.version;
          const base = state.look.white ? Cesium.Color.fromCssColorString(WHITE) : Cesium.Color.WHITE;
          const picked = Cesium.Color.fromCssColorString(PICKED);
          for (let i = 0; i < c.featuresLength; i += 1) {
            const f = c.getFeature(i);
            const id = modelId(f);
            f.show = !(id && state.hidden.has(id));
            f.color = id && id === state.picked ? picked : base;
          }
        });
      }
    };
    attach();
    setInterval(attach, 1500); // tilesets VWorld adds later (more detail as the camera comes closer)
  }

  function blendMode() {
    return state.look.white ? Cesium.Cesium3DTileColorBlendMode.REPLACE : Cesium.Cesium3DTileColorBlendMode.HIGHLIGHT;
  }

  // How VWorld's map looks: buildings as a white model (photo textures replaced), the ground without
  // the aerial photo, VWorld's name labels off. Only the drawing changes; VWorld's data is not
  // changed or kept. Names painted into the building photos stay unless the white model is on.
  function setLook(look) {
    const viewer = ws3d.viewer;
    state.look = { white: Boolean(look.white), plain: Boolean(look.plain), noNames: Boolean(look.noNames) };
    for (const t of viewer.scene.primitives._primitives || []) {
      if (t instanceof Cesium.Cesium3DTileset) t.colorBlendMode = blendMode();
    }
    for (let i = 0; i < viewer.imageryLayers.length; i += 1) viewer.imageryLayers.get(i).show = !state.look.plain;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString(GROUND);
    const names = map && map.getElementById ? map.getElementById(NAMES) : null;
    if (names) { if (state.look.noNames) names.hide(); else names.show(); }
    redraw();
  }

  function drawMasses(polygons) {
    const viewer = ws3d.viewer;
    for (const e of state.masses) viewer.entities.remove(e);
    state.masses = polygons.map((p) => viewer.entities.add({
      name: 'sida mass',
      polygon: {
        hierarchy: Cesium.Cartesian3.fromDegreesArray(p.ring.flat()),
        height: 0, heightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        extrudedHeight: p.height, extrudedHeightReference: Cesium.HeightReference.RELATIVE_TO_GROUND,
        material: Cesium.Color.fromCssColorString(MASS).withAlpha(0.72),
        outline: true, outlineColor: Cesium.Color.WHITE,
      },
    }));
  }

  function aim(center, height, pitch) {
    const c = Cesium.Cartesian3.fromDegrees(center.lon, center.lat - south(height, pitch), height);
    ws3d.viewer.camera.setView({ destination: c, orientation: { heading: 0, pitch: Cesium.Math.toRadians(pitch), roll: 0 } });
  }

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  function tilesLoaded() {
    return (ws3d.viewer.scene.primitives._primitives || []).filter((p) => p instanceof Cesium.Cesium3DTileset).every((t) => t.tilesLoaded);
  }

  function inside([x, y], ring) {
    let hit = false;
    for (let i = 0, j = ring.length - 1; i < ring.length; j = i, i += 1) {
      const [xi, yi] = ring[i], [xj, yj] = ring[j];
      if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) hit = !hit;
    }
    return hit;
  }

  // The VWorld buildings standing on the site: seen from straight above, the building under each
  // point of a 3 m grid inside the parcels (VWorld's buildings carry no parcel number, so this goes
  // by where they stand). The masses are taken away while looking.
  async function buildingsOn(rings, center) {
    const viewer = ws3d.viewer;
    const before = viewer.camera.position.clone(), heading = viewer.camera.heading, pitch = viewer.camera.pitch;
    for (const e of state.masses) e.show = false;
    viewer.camera.setView({ destination: Cesium.Cartesian3.fromDegrees(center.lon, center.lat, 450),
      orientation: { heading: 0, pitch: Cesium.Math.toRadians(-90), roll: 0 } });
    for (let i = 0; i < 40 && !tilesLoaded(); i += 1) await wait(250);
    await wait(600);
    const found = new Set();
    const step = 3 / 110540;
    for (const ring of rings) {
      const xs = ring.map((p) => p[0]), ys = ring.map((p) => p[1]);
      const kx = step / Math.cos(center.lat * Math.PI / 180);
      for (let x = Math.min(...xs) + kx / 2; x < Math.max(...xs); x += kx) {
        for (let y = Math.min(...ys) + step / 2; y < Math.max(...ys); y += step) {
          if (!inside([x, y], ring)) continue;
          const at = Cesium.SceneTransforms.wgs84ToWindowCoordinates(viewer.scene, Cesium.Cartesian3.fromDegrees(x, y, 0));
          const id = at && modelId(viewer.scene.pick(at));
          if (id && !state.hidden.has(id)) found.add(id);
        }
      }
    }
    for (const e of state.masses) e.show = true;
    viewer.camera.setView({ destination: before, orientation: { heading, pitch, roll: 0 } });
    return [...found];
  }

  window.sidaVWorld = {
    ready,
    failed: () => state.failed,
    // the site, its masses and the buildings hidden so far; the camera looks at the site from the south
    async show({ center, polygons, hidden, appearance, onPick, onKey }) {
      if (!(await ready)) return false;
      state.onPick = onPick || null;
      state.onKey = onKey || null;
      state.hidden = new Set(hidden || []);
      state.picked = '';
      if (appearance) setLook(appearance); else redraw();
      drawMasses(polygons || []);
      await wait(1500); // VWorld's own opening move ends first, or it takes the camera back
      aim(center, VIEW.height, VIEW.pitch);
      return true;
    },
    setMasses(polygons) { if (state.ready) drawMasses(polygons || []); },
    // the hidden list as the board has it now (after a hide, an undo or a redo)
    setHidden(ids) {
      if (!state.ready) return;
      state.hidden = new Set(ids || []);
      if (state.hidden.has(state.picked)) state.picked = '';
      redraw();
    },
    unpick() { if (state.ready) pick(''); },
    picked: () => state.picked,
    // the buildings standing on the site (not hidden yet); the board hides them
    async findSite(rings, center) { return state.ready ? buildingsOn(rings, center) : []; },
    hidden: () => [...state.hidden],
    setLook(look) { if (state.ready) setLook(look); },
  };
})();
