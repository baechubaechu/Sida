// Rhino on the screen, without the DOM: what the "라이노 작업" paper shows, and what the panel
// page inside Rhino (rhino.html) shows of the running document. No number is computed here:
// the figures and the limits are Sida's (sida/experts/rhino/snapshot.py) and are shown as sent;
// this file only chooses, orders and words them. tests/webui/rhino-model.test.mjs checks it.

const fmt = (value, digits = 1) => Number(value).toLocaleString('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits });

// ------------------------------------------------------------------ the paper on the table

const VIEW_ORDER = ['persp', 'axo', 'eye', 'plan', 'elevation', 'section'];
const VIEW_WORDS = { persp: '투시', axo: '축측', eye: '눈높이', plan: '평면', elevation: '입면', section: '단면' };

export const rhinoViewUrl = (project, snapshot, file) => `/api/projects/${encodeURIComponent(project)}/rhino/snapshots/${encodeURIComponent(snapshot)}/views/${encodeURIComponent(file)}`;
// A snapshot's diagram as a picture (svg) or as its drawing instruction (json).
export const rhinoDiagramUrl = (project, snapshot, kind, format = 'svg') => `/api/projects/${encodeURIComponent(project)}/rhino/snapshots/${encodeURIComponent(snapshot)}/diagrams/${encodeURIComponent(kind)}?format=${format}`;

// The paper's parts: the figure lines as Sida wrote them, its captures (the perspective first:
// it says most at a glance), the diagrams Sida can draw of it, and where the snapshot came from.
export function rhinoPaperParts(paper) {
  const lines = (paper?.figures?.lines || []).map(String);
  const rank = (view) => { const at = VIEW_ORDER.indexOf(view.kind); return at < 0 ? VIEW_ORDER.length : at; };
  const views = (paper?.views || []).filter((v) => v && v.file)
    .map((v) => ({ kind: v.kind, file: v.file, word: VIEW_WORDS[v.kind] || v.kind }))
    .sort((a, b) => rank(a) - rank(b));
  const when = String(paper?.taken_at || '').replace('T', ' ').slice(0, 16);
  const source = [paper?.file || '저장하지 않은 라이노 문서', when, `개체 ${paper?.objects || 0}개`].filter(Boolean).join(', ');
  const diagrams = (paper?.diagrams || []).filter((d) => d && d.kind).map((d) => ({ kind: String(d.kind), title: String(d.title || d.kind) }));
  return { lines, views, diagrams, source, snapshot: String(paper?.snapshot || ''), limits: limitLines(paper?.figures?.limits) };
}

// A diagram's file as the designer gets it: "<the paper's name> <the diagram's name>.<format>",
// without the characters a file name cannot hold.
export function diagramFileName(paperTitle, diagramTitle, format) {
  const clean = (text) => String(text || '').replace(/[\\/:*?"<>|\u0000-\u001f]/g, ' ').replace(/\s+/g, ' ').trim();
  return `${[clean(paperTitle), clean(diagramTitle)].filter(Boolean).join(' ') || 'diagram'}.${format}`;
}

// The pixels of a diagram's PNG: the SVG's own size times `scale` (2: sharp on a slide), kept
// under `limit` on its longer side so a browser canvas can hold it.
export function diagramPngSize(width, height, scale = 2, limit = 4096) {
  const w = Number(width) > 0 ? Number(width) : 960;
  const h = Number(height) > 0 ? Number(height) : 720;
  const k = Math.min(scale, limit / Math.max(w, h));
  return { width: Math.round(w * k), height: Math.round(h * k) };
}

// The site's limits as lines, as the site facts have them: the legal ceiling of each zone and,
// where the ordinance was read by rule, its value. Nothing is merged across zones.
export function limitLines(limits) {
  return (limits || []).map((x) => {
    const legal = [x.bcr_max != null ? `건폐율 ${x.bcr_max}% 이하` : '', x.far_max != null ? `용적률 ${x.far_max}% 이하` : ''].filter(Boolean).join(', ');
    const ordinance = [x.ordinance_bcr != null ? `건폐율 ${x.ordinance_bcr}%` : '', x.ordinance_far != null ? `용적률 ${x.ordinance_far}%` : ''].filter(Boolean).join(', ');
    return `${x.zone}: 법정 ${legal || '미확인'}${ordinance ? ` (조례 ${ordinance})` : ''}`;
  });
}

// ------------------------------------------------------------------ the panel in Rhino

// Which state the panel is in, and the one sentence that says what to do about it.
//   waiting      no Rhino has reported (the page is open in a browser, or the plugin is starting)
//   lost         a document was shown but its plugin stopped asking (Rhino closed, or busy)
//   no-project   the document is not tied to a Sida project yet
//   bad-project  it names a project this Sida does not have
//   ready        figures can be shown
export function panelStatus(live) {
  const state = live?.state;
  if (!state) return { code: 'waiting', text: '라이노에서 SidaPanel을 열면 여기에 지금 문서가 나옵니다.' };
  if (!live.connected) return { code: 'lost', text: '라이노와 연결이 끊겼습니다. 라이노가 켜져 있는지 확인하세요. 마지막으로 받은 내용을 보여 줍니다.' };
  if (!state.project) return { code: 'no-project', text: '이 문서를 어느 Sida 프로젝트에 붙일지 고르세요.' };
  if (!state.project_known) return { code: 'bad-project', text: `이 문서가 붙어 있던 프로젝트 "${state.project}"가 이 Sida에 없습니다. 프로젝트를 다시 고르세요.` };
  return { code: 'ready', text: '' };
}

// What the plugin is in the middle of ('' | pull | push | draw). The plugin says so itself
// (`state.busy`); until its next report the button the designer just pressed counts (`asked`:
// {what, notice, until}), and stops counting when the plugin answers with a new notice or the
// time runs out.
export function panelBusy(live, asked, now) {
  const state = live?.state;
  if (state?.busy) return state.busy;
  if (!asked?.what || !state) return '';
  if ((state.notice?.n || 0) !== asked.notice || now > asked.until) return '';
  return asked.what;
}

// The diagrams the panel offers to draw in Rhino, each with whether it is picked (all of them
// until the designer leaves one out), and the kinds a press of the button asks for.
export function diagramChoices(kinds, skipped) {
  const out = new Set(skipped || []);
  const rows = (kinds || []).map((d) => ({ kind: d.kind, title: d.title, on: !out.has(d.kind) }));
  return { rows, picked: rows.filter((r) => r.on).map((r) => r.kind) };
}

// One gauge: a ratio against its limit. The limit is the ordinance's value when it was read,
// else the legal ceiling, and only when the site lies in one zone: across zones the limit is a
// weighted figure Sida does not compute here, so the gauge shows the ratio alone.
function gauge(label, value, limits, ordinanceKey, legalKey) {
  const out = { label, value, text: value == null ? '미확인' : `${fmt(value)}%`, limit: null, limitText: '', fill: 0, over: false };
  if (limits.length !== 1) {
    if (limits.length > 1) out.limitText = '용도지역이 여러 개라 한도는 아래 목록을 보세요';
    return out;
  }
  const zone = limits[0];
  const fromOrdinance = zone[ordinanceKey] != null;
  const limit = fromOrdinance ? zone[ordinanceKey] : zone[legalKey];
  if (limit == null || !(limit > 0)) return out;
  out.limit = limit;
  out.limitText = `${fromOrdinance ? '조례' : '법정 상한'} ${limit}%`;
  if (value != null) {
    out.fill = Math.min(value / limit, 1.25);  // the bar runs a quarter past the limit mark at most
    out.over = value > limit;
  }
  return out;
}

// The figures as the panel lays them out: the two gauges, the plain rows, the share of each
// meaning in the floor area, and the notes about what was left out. Null without figures.
export function panelFigures(fig) {
  if (!fig) return null;
  const limits = fig.limits || [];
  const total = fig.floor_area_m2 || 0;
  const rows = [
    { label: '연면적', text: `${fmt(fig.floor_area_m2)}㎡` },
    { label: '건축면적', text: `${fmt(fig.footprint_m2)}㎡` },
    { label: '대지면적', text: fig.site_area_m2 ? `${fmt(fig.site_area_m2)}㎡` : '미확인' },
  ];
  if (fig.height_m != null) rows.push({ label: '최고 높이', text: `${fmt(fig.height_m)}m` });
  const notes = [];
  if (!fig.site_area_m2) notes.push('대지 면적이 없어 건폐율과 용적률을 낼 수 없습니다. Sida에서 대지를 먼저 조회하세요.');
  if (fig.unassigned) notes.push(`의미 없는 레이어의 개체 ${fig.unassigned}개는 수치에서 빠졌습니다.`);
  if ((fig.no_floor_height || []).length) notes.push(`층고를 정하지 않은 레이어의 개체 ${fig.no_floor_height.length}개는 연면적에서 빠졌습니다.`);
  if ((fig.unmeasured || []).length) notes.push(`닫히지 않아 잴 수 없는 개체가 ${fig.unmeasured.length}개 있습니다.`);
  return {
    gauges: [
      gauge('건폐율', fig.coverage_pct, limits, 'ordinance_bcr', 'bcr_max'),
      gauge('용적률', fig.far_pct, limits, 'ordinance_far', 'far_max'),
    ],
    rows,
    shares: (fig.by_meaning || []).filter((p) => p.floor_area_m2 > 0).map((p) => ({
      meaning: p.meaning, word: p.word, text: `${fmt(p.floor_area_m2)}㎡`, share: total > 0 ? p.floor_area_m2 / total : 0,
    })),
    notes,
    limits: limitLines(limits),
    empty: !fig.objects,
  };
}

// The layers as rows of the panel's table. A layer that holds bodies but has no meaning needs
// one (`needs: 'meaning'`), one that means building but has no floor height needs that
// (`needs: 'height'`); those come first, then the rest in Rhino's order. Layers without bodies
// and without a meaning are counted, not listed (`quiet`), unless `all`.
export function layerRows(layers, meanings, { all = false } = {}) {
  const built = new Set((meanings || []).filter((m) => m.built).map((m) => m.code));
  const rows = (layers || []).map((layer, order) => {
    const needs = layer.objects > 0 && !layer.meaning ? 'meaning'
      : layer.objects > 0 && built.has(layer.meaning) && !layer.floor_height ? 'height' : '';
    const parts = String(layer.path || '').split('::');
    return {
      path: layer.path, name: parts[parts.length - 1], under: parts.slice(0, -1).join(' › '),
      meaning: layer.meaning || '', color: layer.color || '', objects: layer.objects || 0,
      floorHeight: layer.floor_height == null ? '' : String(layer.floor_height),
      takesHeight: built.has(layer.meaning), needs, order,
    };
  });
  const shown = all ? rows : rows.filter((r) => r.objects > 0 || r.meaning);
  shown.sort((a, b) => (a.needs ? 0 : 1) - (b.needs ? 0 : 1) || a.order - b.order);
  return { rows: shown, quiet: rows.length - shown.length };
}

// What the designer typed as a floor height, in metres: a number above 0 up to 100, or empty
// for none. {value} or {error}.
export function readFloorHeight(text) {
  const raw = String(text ?? '').trim().replace(',', '.');
  if (!raw) return { value: null };
  const value = Number(raw);
  if (!Number.isFinite(value) || value <= 0 || value > 100) return { error: '층고는 0보다 크고 100 이하인 m 값으로 적으세요. 예: 3.3' };
  return { value: Math.round(value * 1000) / 1000 };
}

// The meanings as the choices of a layer's select: buildings first, then what is left out.
export function meaningChoices(meanings) {
  const list = meanings || [];
  return {
    built: list.filter((m) => m.built).map((m) => ({ code: m.code, word: m.word })),
    other: list.filter((m) => !m.built).map((m) => ({ code: m.code, word: m.word })),
  };
}
