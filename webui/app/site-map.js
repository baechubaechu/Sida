// The map on the site page's "찾기" tab: the VWorld background and 지적 lines (the browser fetches
// them from the URLs GET /api/site/map gives), the parcels found, picked and saved, and a click
// that asks the server which parcel lies there. Like the drafting table it lives outside the
// redrawn page: render() moves its element into #site-map-slot, so panning survives redraws.
import * as L from './vendor/leaflet.js';
import { shapesBounds } from './model.js';

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
    this.map.on('click', (e) => onClick(e.latlng.lng, e.latlng.lat, this.map.getZoom()));
  }

  attach(slot) {
    if (this.el.parentElement !== slot) slot.replaceChildren(this.el);
    this.map.invalidateSize(false);
  }

  // groups: {saved, candidate, picked}, each [{pnu, shape}] (shape: GeoJSON or null).
  show(groups) {
    const key = JSON.stringify(['saved', 'candidate', 'picked'].map((k) => (groups[k] || []).map((p) => `${p.pnu}${p.shape ? '' : '?'}`)));
    if (key === this.key) return;
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
    this.map.remove();
  }
}
