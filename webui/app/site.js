// Site page actions: region lists, finding parcels (typed or on the map), saving the site,
// ordinance options and planned uses.

import { sitePath, chosenDong, lotQuery, lookupBody, briefSite, togglePicked, shapesToFetch, MAP_PICK_ZOOM } from './model.js';
import { api, projectApi } from './api.js';
import { loadBoard } from './board.js';
import { runExpert } from './experts.js';
import { render } from './render.js';
import { REGION_LEVELS, app, freshFind, freshUseFind, toast, ui } from './state.js';

let siteMap = null; // the map on the site page's "찾기" tab (site-map.js, loaded on first use)
let siteMapLoading = false;

// ------------------------------------------------------------------ site page actions

function findFailed(error) {
  ui.find.error = error.message;
  ui.find.errorStatus = error.status;
}

async function loadRegions(level, parent) {
  const f = ui.find;
  f.loading = level;
  render(false);
  try {
    const { regions } = await api(parent ? `/api/site/regions?parent=${encodeURIComponent(parent)}` : '/api/site/regions');
    if (ui.find !== f) return; // another project opened meanwhile
    f.lists[level] = regions;
  } catch (error) {
    findFailed(error);
  }
  f.loading = '';
  render(false);
}

// Opening the "find" tab: the 시·도 list, and the brief's address ready for the text search.
export async function prepareFind(name) {
  const f = ui.find;
  if (!f.lists.sido && !f.loading) loadRegions('sido', '');
  if (!ui.mapLayers && !ui.mapError) loadMapLayers();
  if (f.briefTried) return;
  f.briefTried = true;
  try {
    const { brief } = await api(projectApi(name));
    const address = briefSite(brief);
    if (ui.find === f && address && !f.query) {
      f.query = address;
      if (!f.chosen.sido) f.mode = 'text';
      render(false);
    }
  } catch { /* the brief is only a convenience here */ }
}

// ---- the map (site-map.js): background and 지적 line URLs once, parcel boundaries as they are needed

async function loadMapLayers() {
  try {
    ui.mapLayers = await api('/api/site/map');
  } catch (error) {
    ui.mapError = error.message;
    ui.mapErrorStatus = error.status;
  }
  render(false);
}

// The map element is moved into the redrawn page's slot (created once, on first need).
export function placeSiteMap() {
  const slot = app.querySelector('#site-map-slot');
  if (!slot || !ui.mapLayers) return;
  if (!siteMap) { openSiteMap(); return; }
  siteMap.attach(slot);
  siteMap.show(mapGroups());
}


async function openSiteMap() {
  if (siteMapLoading) return;
  siteMapLoading = true;
  try {
    const { SiteMap } = await import('./site-map.js');
    siteMap = new SiteMap(ui.mapLayers, pickOnMap);
  } catch (error) {
    ui.mapError = error.message;
  }
  siteMapLoading = false;
  render(false);
}

// What the map draws: the saved site, the parcels found (not yet picked) and the picked ones.
function mapGroups() {
  const f = ui.find;
  const withShape = (p) => ({ pnu: p.pnu, shape: p.shape ?? f.shapes.get(p.pnu) ?? null });
  const picked = new Set(f.picked.map((p) => p.pnu));
  return {
    saved: ui.site?.available ? ui.site.parcels.map((p) => ({ pnu: p.pnu, shape: p.shape || null })) : [],
    candidate: (f.candidates || []).filter((c) => !picked.has(c.pnu)).map(withShape),
    picked: f.picked.map(withShape),
  };
}

async function fetchShapes() {
  const f = ui.find;
  if (!ui.mapLayers) return;
  const pnus = shapesToFetch([...(f.candidates || []), ...f.picked], f.shapes);
  if (!pnus.length) return;
  for (const pnu of pnus) f.shapes.set(pnu, null); // asked once, whatever comes back
  try {
    const { shapes } = await api(`/api/site/shapes?${pnus.map((p) => `pnu=${encodeURIComponent(p)}`).join('&')}`);
    for (const s of shapes) f.shapes.set(s.pnu, s.shape);
  } catch { /* the map just leaves those parcels out */ }
  if (ui.find === f) render(false);
}

// A click on the map: the parcel there goes into the picked list, or out if it was in.
async function pickOnMap(lon, lat, zoom) {
  const f = ui.find;
  if (f.busy || f.mapBusy) return;
  f.errorStatus = 0;
  if (zoom < MAP_PICK_ZOOM) { f.error = '필지를 고르려면 지도를 더 확대해 주세요.'; render(false); return; }
  f.error = '';
  f.mapBusy = true;
  render(false);
  try {
    const { candidates } = await api(`/api/site/parcel-at?lon=${lon.toFixed(7)}&lat=${lat.toFixed(7)}`);
    if (ui.find !== f) return;
    const [parcel] = candidates;
    if (!parcel) f.error = '누른 곳에 필지가 없습니다(도로·하천 등). 다른 곳을 눌러 주세요.';
    else {
      f.shapes.set(parcel.pnu, parcel.shape || null);
      f.picked = togglePicked(f.picked, parcel);
    }
  } catch (err) {
    findFailed(err);
  }
  f.mapBusy = false;
  render(false);
}

export function chooseRegion(level, code) {
  const f = ui.find;
  const index = REGION_LEVELS.indexOf(level);
  f.chosen[level] = (f.lists[level] || []).find((r) => r.code === code) || null;
  for (const lower of REGION_LEVELS.slice(index + 1)) {
    f.chosen[lower] = null;
    f.lists[lower] = null;
  }
  f.candidates = null;
  f.error = '';
  const region = f.chosen[level];
  const next = REGION_LEVELS[index + 1];
  if (region && next && (level !== 'emd' || region.has_ri)) loadRegions(next, region.code);
  else render(false);
}

export async function findLot() {
  const f = ui.find;
  const { query, error } = lotQuery(chosenDong(f.chosen), f.main, f.sub, f.mountain);
  f.error = error || '';
  f.errorStatus = 0;
  if (error) { render(false); return; }
  f.busy = 'lots';
  render(false);
  try {
    const { candidates, lot } = await api(`/api/site/lots?${query}`);
    f.candidates = candidates;
    f.search = null;
    if (!candidates.length) f.error = `${lot} 필지가 없습니다. 지번을 다시 확인해 주세요.`;
  } catch (err) {
    findFailed(err);
  }
  f.busy = '';
  render(false);
  fetchShapes();
}

export async function searchAddress(name) {
  const f = ui.find;
  const text = f.query.trim();
  f.errorStatus = 0;
  if (!text) { f.error = '주소를 적어 주세요.'; render(false); return; }
  f.error = '';
  f.busy = 'search';
  render(false);
  try {
    const { query, candidates } = await api(`${projectApi(name)}/site/parcels`, { method: 'POST', body: { query: text } });
    f.candidates = candidates;
    f.search = { query, pnus: candidates.map((c) => c.pnu) };
    if (!candidates.length) f.error = '찾은 필지가 없습니다. 번지까지 적었는지, 오타가 없는지 확인해 주세요.';
  } catch (err) {
    findFailed(err);
  }
  f.busy = '';
  render(false);
  fetchShapes();
}

export function togglePick(pnu, on) {
  const f = ui.find;
  const found = (f.candidates || []).find((c) => c.pnu === pnu);
  f.picked = f.picked.filter((p) => p.pnu !== pnu);
  if (on && found) f.picked.push(found);
  render(false);
}

// The Conductor wanted the site reader before a site was saved: the find tab searches the address
// it passed (the brief's otherwise), and saving the site runs the site reader.
export function askForSite(name, address) {
  ui.siteFirst = true;
  const f = ui.find;
  const text = String(address || '').trim();
  if (!text || f.busy) return;
  f.query = text;
  f.mode = 'text';
  f.briefTried = true;
  searchAddress(name);
}

export async function setOrdinanceOption(name, id, change) {
  if (ui.ordinanceBusy) return;
  ui.ordinanceBusy = id;
  render(false);
  try {
    const ordinance = await api(`${projectApi(name)}/site/ordinance/options/${encodeURIComponent(id)}`, { method: 'PUT', body: change });
    if (ui.project === name) ui.ordinance = ordinance;
  } catch (err) {
    toast(err.message, 'error');
  }
  ui.ordinanceBusy = '';
  render(false);
}

function useFailed(error) {
  ui.useFind.error = error.message;
  ui.useFind.errorStatus = error.status;
}

export async function searchUses() {
  const u = ui.useFind;
  const text = u.query.trim();
  u.errorStatus = 0;
  if (!text) { u.error = '용도 이름을 적어 주세요.'; render(false); return; }
  u.error = '';
  u.busy = 'search';
  render(false);
  try {
    const { uses } = await api(`/api/site/uses?q=${encodeURIComponent(text)}`);
    u.candidates = uses;
    if (!uses.length) u.error = `"${text}"이(가) 들어간 용도 이름이 없습니다. 더 짧게 적어 보세요.`;
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

export async function checkUse(name, use) {
  const u = ui.useFind;
  if (u.busy) return;
  u.busy = `check:${use}`;
  u.error = '';
  u.errorStatus = 0;
  render(false);
  try {
    const site = await api(`${projectApi(name)}/site/uses`, { method: 'POST', body: { name: use } });
    if (ui.project === name) { ui.site = site; u.candidates = null; u.query = ''; }
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

export async function removeUse(name, use) {
  const u = ui.useFind;
  if (u.busy) return;
  u.busy = `remove:${use}`;
  render(false);
  try {
    const site = await api(`${projectApi(name)}/site/uses/${encodeURIComponent(use)}`, { method: 'DELETE' });
    if (ui.project === name) ui.site = site;
  } catch (err) {
    useFailed(err);
  }
  u.busy = '';
  render(false);
}

export async function saveSite(name) {
  const f = ui.find;
  if (!f.picked.length || f.busy) return;
  f.busy = 'save';
  f.error = '';
  f.errorStatus = 0;
  render(false);
  try {
    ui.site = await api(`${projectApi(name)}/site`, { method: 'PUT', body: lookupBody(f.picked, f.search) });
    ui.find = freshFind();
    ui.ordinance = null; // the new site may fall under another ordinance
    ui.useFind = freshUseFind();
    loadBoard(name); // the site paper on the table draws the new parcels and facts
    location.hash = sitePath(name);
    if (ui.siteFirst) {
      toast('대지 사실을 저장해 제도판의 대지 종이에 그렸습니다. 대지 분석가를 실행합니다.', 'success');
      runExpert(name, 'site_reader');
    } else {
      toast('대지 사실을 저장해 제도판의 대지 종이에 그렸습니다. 대지 분석가와 법규 검토자를 다시 실행하면 반영됩니다.', 'success');
    }
  } catch (err) {
    findFailed(err);
    f.busy = '';
  }
  render(false);
}
