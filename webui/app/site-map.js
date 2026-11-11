// The map on the site page's "찾기" tab: the VWorld background and 지적 lines (the browser fetches
// them from the URLs GET /api/site/map gives), the parcels found, picked and saved, and a click
// that asks the server which parcel lies there. Like the drafting table it lives outside the
// redrawn page: render() moves its element into #site-map-slot, so panning survives redraws.
// The 반경 button (top right) measures on the map as in Naver Map (2026-11-10 지훈): while it is
// on, a click sets a centre and a second click the radius (no drag), so the circle shows what
// lies within it on VWorld's map, station and school names and all. With a site saved, 250 m,
// 500 m and 1 km circles about it are one click. Circles are only shown, never saved; Esc drops
// the one being drawn, then the rest, and turning the button off clears them.
import * as L from './vendor/leaflet.js';
import { shapesBounds, distanceLabel } from './model.js';

const QUICK_RADII = [250, 500, 1000];
const MAX_MAP_CIRCLES = 10;

const KOREA = { center: [36.4, 127.8], zoom: 7 };
const STYLES = {
  saved: { color: '#c0392b', weight: 2, dashArray: '6 4', fill: false },
  candidate: { color: '#36536b', weight: 1.5, fillOpacity: 0.06 },
  picked: { color: '#1f3a52', weight: 3, fillColor: '#36536b', fillOpacity: 0.35 },
};

export class SiteMap {
  constructor(layers, onClick) {
    this.el = document.createElement('div');
    this.el.className = 'site-map';
    this.el.setAttribute('aria-label', '대지 지도');
    this.map = L.map(this.el, { minZoom: 6, maxZoom: 19 }).setView(KOREA.center, KOREA.zoom);
    L.tileLayer(layers.base.url, { attribution: layers.base.attribution, maxZoom: 19 }).addTo(this.map);
    const c = layers.cadastral;
    // Below min_zoom VWorld sends blank 지적 tiles, so the layer stays off there.
    L.tileLayer.wms(c.url, { ...c.params, minZoom: c.min_zoom, maxZoom: 19, opacity: c.opacity }).addTo(this.map);
    this.parcels = L.layerGroup().addTo(this.map);
    this.key = '';
    this.ruler = { on: false, start: null, circles: [], centre: null };
    this.rulerLayer = L.layerGroup().addTo(this.map);
    this.liveLayer = L.layerGroup().addTo(this.map);
    this.addRulerControl();
    this.map.on('click', (e) => {
      if (this.ruler.on) this.rulerClick(e.latlng);
      else onClick(e.latlng.lng, e.latlng.lat, this.map.getZoom());
    });
    this.map.on('mousemove', (e) => { if (this.ruler.on && this.ruler.start) this.drawLive(e.latlng); });
    // Esc anywhere but a text field, while the 반경 button is on (the map need not have the focus).
    this.onKey = (e) => {
      const t = e.target;
      if (e.key !== 'Escape' || !this.ruler.on || !this.el.isConnected || t?.closest?.('input, textarea, select, dialog')) return;
      if (this.rulerEscape()) e.preventDefault();
    };
    window.addEventListener('keydown', this.onKey);
  }

  // ------------------------------------------------------------------ 반경 재기

  addRulerControl() {
    const control = L.control({ position: 'topright' });
    control.onAdd = () => {
      const box = L.DomUtil.create('div', 'leaflet-bar map-ruler');
      L.DomEvent.disableClickPropagation(box);
      L.DomEvent.disableScrollPropagation(box);
      box.addEventListener('click', (e) => {
        // The buttons are drawn again on a click, and Leaflet cannot tell a click on a button no
        // longer in the page from one on the map: the click stops here.
        e.stopPropagation();
        const t = e.target.closest('button');
        if (!t) return;
        if (t.dataset.ruler === 'toggle') this.setRuler(!this.ruler.on);
        else if (t.dataset.radius) this.circlesAtSite([Number(t.dataset.radius)]);
      });
      this.rulerBox = box;
      this.drawRulerControl();
      return box;
    };
    control.addTo(this.map);
  }

  drawRulerControl() {
    const box = this.rulerBox;
    if (!box) return;
    const { on, centre, start } = this.ruler;
    const quick = on && centre
      ? `<span class="map-ruler-quick" role="group" aria-label="대지 가운데에서 반경">${QUICK_RADII.map((r) => `<button type="button" data-radius="${r}" title="대지 가운데에서 반경 ${distanceLabel(r)} 원">${distanceLabel(r)}</button>`).join('')}</span>` : '';
    const tip = on ? `<p class="map-ruler-tip" role="status">${start ? '끝점을 찍으세요. Esc는 취소.' : '중심을 찍고 끝점을 찍으면 원이 남습니다.'}</p>` : '';
    box.innerHTML = `<button type="button" data-ruler="toggle" aria-pressed="${on}" title="반경 재기 — 중심과 끝점을 찍어 원 그리기 (켜져 있는 동안은 필지를 고르지 않음)">반경</button>${quick}${tip}`;
  }

  setRuler(on) {
    this.ruler = { ...this.ruler, on, start: null, circles: on ? this.ruler.circles : [] };
    this.liveLayer.clearLayers();
    if (!on) this.rulerLayer.clearLayers();
    this.el.classList.toggle('is-measuring', on);
    this.drawRulerControl();
  }

  rulerClick(latlng) {
    const r = this.ruler;
    if (!r.start) { this.ruler = { ...r, start: latlng }; this.drawRulerControl(); return; }
    const radius = this.map.distance(r.start, latlng);
    if (radius < 0.5) return;
    this.addCircle(r.start, radius, latlng);
    this.ruler = { ...this.ruler, start: null };
    this.liveLayer.clearLayers();
    this.drawRulerControl();
  }

  // The radius's end point straight north of the centre (for circles drawn about the site).
  northOf(centre, radius) {
    return L.latLng(centre.lat + (radius / 6371008.8) * (180 / Math.PI), centre.lng);
  }

  circlesAtSite(radii) {
    const c = this.ruler.centre;
    if (!c) return;
    for (const radius of radii) this.addCircle(c, radius, this.northOf(c, radius));
    const largest = Math.max(...radii);
    this.map.fitBounds(L.latLng(c).toBounds(largest * 2.2), { maxZoom: 18 });
  }

  addCircle(centre, radius, end) {
    this.ruler.circles = [...this.ruler.circles, { centre, radius, end }].slice(-MAX_MAP_CIRCLES);
    this.rulerLayer.clearLayers();
    for (const k of this.ruler.circles) this.drawCircle(this.rulerLayer, k.centre, k.radius, k.end, false);
  }

  drawLive(latlng) {
    const start = this.ruler.start;
    this.liveLayer.clearLayers();
    if (!start) return;
    const radius = this.map.distance(start, latlng);
    this.drawCircle(this.liveLayer, start, radius, latlng, true);
  }

  drawCircle(layer, centre, radius, end, live) {
    const style = { color: '#126b89', weight: live ? 2 : 1.5, interactive: false };
    L.circle(centre, { ...style, radius, fillColor: '#126b89', fillOpacity: 0.07, dashArray: live ? null : '6 4' }).addTo(layer);
    L.polyline([centre, end], style).addTo(layer);
    L.circleMarker(centre, { ...style, radius: 3, fill: true, fillOpacity: 1 }).addTo(layer);
    L.marker(end, { interactive: false, keyboard: false, icon: L.divIcon({ className: 'map-measure-label', html: `<span>반경 ${distanceLabel(radius)}</span>`, iconSize: null }) }).addTo(layer);
  }

  // Esc while measuring: the circle being drawn, else every circle. False when there was none.
  rulerEscape() {
    if (this.ruler.start) { this.ruler = { ...this.ruler, start: null }; this.liveLayer.clearLayers(); this.drawRulerControl(); return true; }
    if (this.ruler.circles.length) { this.ruler.circles = []; this.rulerLayer.clearLayers(); return true; }
    return false;
  }

  attach(slot) {
    if (this.el.parentElement !== slot) slot.replaceChildren(this.el);
    this.map.invalidateSize(false);
  }

  // groups: {saved, candidate, picked}, each [{pnu, shape}] (shape: GeoJSON or null).
  show(groups) {
    const key = JSON.stringify(['saved', 'candidate', 'picked'].map((k) => (groups[k] || []).map((p) => `${p.pnu}${p.shape ? '' : '?'}`)));
    if (key === this.key) return;
    // The middle of the saved site, for the 반경 button's 250 m · 500 m · 1 km circles.
    const site = shapesBounds((groups.saved || []).map((p) => p.shape));
    this.ruler.centre = site ? L.latLngBounds(site).getCenter() : null;
    this.drawRulerControl();
    const first = !this.key;
    this.key = key;
    this.parcels.clearLayers();
    for (const kind of ['candidate', 'picked', 'saved']) { // the saved site's dashed line stays on top
      for (const p of groups[kind] || []) {
        if (p.shape) L.geoJSON(p.shape, { style: STYLES[kind], interactive: false }).addTo(this.parcels);
      }
    }
    // Bring the parcels in view (picked first, else those found, else the saved site) when they
    // are not all on screen already.
    const focus = [groups.picked, groups.candidate, groups.saved].find((list) => list?.some((p) => p.shape)) || [];
    const box = shapesBounds(focus.map((p) => p.shape));
    if (box && (first || !this.map.getBounds().contains(box))) this.map.fitBounds(box, { maxZoom: 18, padding: [24, 24] });
  }

  destroy() {
    window.removeEventListener('keydown', this.onKey);
    this.map.remove();
  }
}
