// Inside vworld3d.html: VWorld's own WebGL 3D map (vw.Map on Cesium) with the board's masses on it.
// The board drives it through window.sidaVWorld (same origin). Only VWorld's official API is used;
// none of its tiles or models are read out or kept. What is kept (by the board, PUT .../board/hidden)
// is the list of VWorld buildings the designer hid, by their model id (MODEL_NAME).
/* global vw, ws3d, Cesium */
(function () {
  'use strict';
  const MASS = '#f08a24'; // orange: stands out from VWorld's glass and concrete
  const state = { hidden: new Set(), masses: [], onHidden: null, version: 0, ready: false, failed: '',
    look: { white: false, plain: false } };
  const WHITE = '#e9e9e6'; // buildings as a white model: VWorld's photo textures replaced by one colour
  const GROUND = '#cfd3cf'; // the ground without the aerial photo
  // where the map starts: the site's middle, from the board (after #), seen from the south
  const start = new URLSearchParams(location.hash.slice(1));
  const site = { lon: Number(start.get('lon')) || 126.978, lat: Number(start.get('lat')) || 37.566 };
  const VIEW = { height: 190, pitch: -32 };
  const south = (height, pitch) => (height / Math.tan((-pitch * Math.PI) / 180)) / 110540; // degrees of latitude
  let resolveReady;
  const ready = new Promise((resolve) => { resolveReady = resolve; });

  if (typeof vw === 'undefined') {
    state.failed = '브이월드 3D 지도를 불러오지 못했습니다. 인터넷 연결과 브이월드 키를 확인하세요.';
    resolveReady(false);
  } else {
    const map = new vw.Map();
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
        const picked = viewer.scene.pick(movement.position);
        const id = modelId(picked);
        if (id) hide([id], true);
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
      watchTilesets(viewer);
      state.ready = true;
      resolveReady(true);
    };
  }

  function modelId(picked) {
    if (!(picked instanceof Cesium.Cesium3DTileFeature)) return '';
    const id = picked.getProperty('MODEL_NAME') || picked.getProperty('TD_ID');
    return id ? String(id) : '';
  }

  // Each building tileset, as its tiles come into view: hide the features on the hidden list (and
  // show them again once taken off it). VWorld's tiles come and go, so this runs per visible tile.
  function watchTilesets(viewer) {
    const seen = new Set();
    const attach = () => {
      for (const p of viewer.scene.primitives._primitives || []) {
        if (!(p instanceof Cesium.Cesium3DTileset) || seen.has(p)) continue;
        seen.add(p);
        if (state.look.white) p.colorBlendMode = Cesium.Cesium3DTileColorBlendMode.REPLACE;
        p.tileVisible.addEventListener((tile) => {
          const c = tile.content;
          if (!c || c._sidaVersion === state.version || !c.featuresLength) return;
          c._sidaVersion = state.version;
          // the colour goes per building, not as a tileset style: a style would show hidden ones again
          const color = state.look.white ? Cesium.Color.fromCssColorString(WHITE) : Cesium.Color.WHITE;
          for (let i = 0; i < c.featuresLength; i += 1) {
            const f = c.getFeature(i);
            const id = modelId(f);
            f.show = !(id && state.hidden.has(id));
            f.color = color;
          }
        });
      }
    };
    attach();
    setInterval(attach, 1500); // tilesets VWorld adds later (more detail as the camera comes closer)
  }

  function hide(ids, byClick) {
    let changed = false;
    for (const id of ids) if (id && !state.hidden.has(id)) { state.hidden.add(id); changed = true; }
    if (!changed) return;
    state.version += 1;
    ws3d.viewer.scene.requestRender();
    if (state.onHidden) state.onHidden([...state.hidden], byClick);
  }

  // How VWorld's map looks: buildings as a white model (photo textures replaced) and the ground
  // without the aerial photo. Only the drawing changes; nothing of VWorld's data is changed or kept.
  function setLook(look) {
    const viewer = ws3d.viewer;
    state.look = { white: Boolean(look.white), plain: Boolean(look.plain) };
    for (const t of viewer.scene.primitives._primitives || []) {
      if (t instanceof Cesium.Cesium3DTileset) {
        t.colorBlendMode = state.look.white ? Cesium.Cesium3DTileColorBlendMode.REPLACE : Cesium.Cesium3DTileColorBlendMode.HIGHLIGHT;
      }
    }
    for (let i = 0; i < viewer.imageryLayers.length; i += 1) viewer.imageryLayers.get(i).show = !state.look.plain;
    viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString(GROUND);
    state.version += 1; // recolour the tiles in view
    viewer.scene.requestRender();
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

  function look(center, height, pitch) {
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
          if (id) found.add(id);
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
    async show({ center, polygons, hidden, onHidden, appearance }) {
      if (!(await ready)) return false;
      if (appearance) setLook(appearance);
      state.onHidden = onHidden || null;
      state.hidden = new Set(hidden || []);
      state.version += 1;
      drawMasses(polygons || []);
      await wait(1500); // VWorld's own opening move ends first, or it takes the camera back
      look(center, VIEW.height, VIEW.pitch);
      return true;
    },
    setMasses(polygons) { if (state.ready) drawMasses(polygons || []); },
    showAll() { if (!state.ready) return; state.hidden = new Set(); state.version += 1; ws3d.viewer.scene.requestRender(); if (state.onHidden) state.onHidden([], false); },
    async hideSite(rings, center) {
      if (!state.ready) return [];
      const ids = await buildingsOn(rings, center);
      hide(ids, false);
      return ids;
    },
    hidden: () => [...state.hidden],
    setLook(look) { if (state.ready) setLook(look); },
  };
})();
