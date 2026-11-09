// The panels beside the drafting table, docked as the designer likes (2026-11-09 지훈): each side
// holds groups stacked top to bottom, each group shows one of its tabs. A tab can be dragged into
// another group, above or below one (splitting the side), or onto an empty side. Dropped over the
// drafting table it floats there in its own window (`float`: groups with a place and size in px
// from the workspace's top left, as Rhino's floating panels), which moves by its head, resizes by
// its corner and takes more tabs like a docked group. Pure functions: panels.js and dock.js do the
// screen, the server keeps the layout on this PC.

export const DOCK_PANELS = { conductor: '대화', props: '속성', layers: '레이어', experts: '전문가' };
export const DOCK_SIDES = ['left', 'right'];
export const GROUP_MIN_HEIGHT = 120; // px: a group keeps its tabs and a few lines
export const FLOAT_MIN = { w: 240, h: 160 }; // px: the smallest floating window
export const FLOAT_SIZE = { w: 320, h: 420 }; // px: a new floating window
// The sides' first widths, as shares of the workspace (2026-11-09 지훈: both 18%, 360px on a
// 2000px screen); a site or expert page on the right takes `detail`.
export const DEFAULT_PANEL_RATIOS = Object.freeze({ left: .18, right: .18, detail: .38 });

export function defaultDock() {
  return {
    left: { open: true, groups: [{ tabs: ['conductor'], active: 'conductor', size: 1 }] },
    right: { open: true, groups: [{ tabs: ['props', 'layers', 'experts'], active: 'layers', size: 1 }] },
    float: [],
  };
}

const copy = (layout) => ({
  left: { open: layout.left.open, groups: layout.left.groups.map((g) => ({ ...g, tabs: [...g.tabs] })) },
  right: { open: layout.right.open, groups: layout.right.groups.map((g) => ({ ...g, tabs: [...g.tabs] })) },
  float: (layout.float || []).map((g) => ({ ...g, tabs: [...g.tabs] })),
});

// The groups of a side, or the floating windows (`side` 'float').
const groupsOf = (layout, side) => (side === 'float' ? layout.float || [] : layout[side].groups);

// Each side's group sizes add up to 1.
function evenOut(side) {
  const total = side.groups.reduce((sum, g) => sum + g.size, 0);
  for (const g of side.groups) g.size = total > 0 ? g.size / total : 1 / side.groups.length;
}

// A layout read back from the server (or anything else): unknown panels dropped, each panel in one
// place only, an active tab in every group, no empty groups; a panel it lacks (a new one, or a
// broken file) joins the right side, so nothing can be lost off the screen.
export function normalizeDock(raw) {
  if (!raw || typeof raw !== 'object') return defaultDock();
  const seen = new Set();
  const layout = { left: { open: true, groups: [] }, right: { open: true, groups: [] }, float: [] };
  const tabsOf = (g) => {
    const tabs = [];
    for (const id of Array.isArray(g?.tabs) ? g.tabs : []) {
      if (typeof id !== 'string' || !Object.hasOwn(DOCK_PANELS, id) || seen.has(id)) continue;
      seen.add(id);
      tabs.push(id);
    }
    return tabs;
  };
  const px = (value, low, fallback) => (value !== null && value !== '' && Number.isFinite(Number(value)) ? Math.max(low, Math.round(Number(value))) : fallback);
  for (const name of DOCK_SIDES) {
    const side = raw[name] && typeof raw[name] === 'object' ? raw[name] : {};
    layout[name].open = side.open !== false;
    for (const g of Array.isArray(side.groups) ? side.groups : []) {
      const tabs = tabsOf(g);
      if (!tabs.length) continue;
      const size = Number(g.size);
      layout[name].groups.push({ tabs, active: tabs.includes(g.active) ? g.active : tabs[0], size: Number.isFinite(size) && size > 0 ? size : 1 });
    }
  }
  for (const g of Array.isArray(raw.float) ? raw.float : []) {
    const tabs = tabsOf(g);
    if (!tabs.length) continue;
    layout.float.push({ tabs, active: tabs.includes(g.active) ? g.active : tabs[0],
      x: px(g.x, 0, 24), y: px(g.y, 0, 24), w: px(g.w, FLOAT_MIN.w, FLOAT_SIZE.w), h: px(g.h, FLOAT_MIN.h, FLOAT_SIZE.h) });
  }
  const missing = Object.keys(DOCK_PANELS).filter((id) => !seen.has(id));
  if (missing.length) {
    const groups = layout.right.groups;
    if (groups.length) groups.at(-1).tabs.push(...missing);
    else groups.push({ tabs: missing, active: missing[0], size: 1 });
  }
  for (const name of DOCK_SIDES) evenOut(layout[name]);
  return layout;
}

// Where a panel is: {side, index} of its group ('float' for a floating window), or null.
export function dockOf(layout, id) {
  for (const side of [...DOCK_SIDES, 'float']) {
    const index = groupsOf(layout, side).findIndex((g) => g.tabs.includes(id));
    if (index >= 0) return { side, index };
  }
  return null;
}

// On screen: its side is open (a floating window always is) and its group shows it.
export function panelVisible(layout, id) {
  const at = dockOf(layout, id);
  return Boolean(at && (at.side === 'float' || layout[at.side].open) && groupsOf(layout, at.side)[at.index].active === id);
}

// Has the side anything to show (open and not empty)?
export function sideShown(layout, side) {
  return layout[side].open && layout[side].groups.length > 0;
}

export function activate(layout, id) {
  const at = dockOf(layout, id);
  if (!at) return layout;
  const next = copy(layout);
  groupsOf(next, at.side)[at.index].active = id;
  return next;
}

// Bring a panel on screen: its side opens and its group turns to it.
export function reveal(layout, id) {
  const next = activate(layout, id);
  const at = dockOf(next, id);
  if (at && at.side !== 'float') next[at.side].open = true;
  return next;
}

// Turn a group from one tab to another when it shows the first (selecting a paper turns 레이어 to
// 속성 when they share a group; in different groups both are already on screen).
export function swapActive(layout, from, to) {
  const at = dockOf(layout, to);
  if (!at || groupsOf(layout, at.side)[at.index].active !== from) return layout;
  return activate(layout, to);
}

export function setSideOpen(layout, side, open) {
  const next = copy(layout);
  next[side].open = open;
  return next;
}

// Move a panel. `target`: {side, index, place} where place is 'tab' (into that group), 'above' or
// 'below' it (a new group, splitting that group's height), or 'end' (a new group at the bottom of
// the side, also onto an empty side). With side 'float', place 'tab' joins that floating window and
// place 'new' opens a window of its own at {x, y} (a panel alone in a window just moves there). The
// moved panel shows, and its side opens.
export function movePanel(layout, id, target) {
  const from = dockOf(layout, id);
  if (!from || !target || ![...DOCK_SIDES, 'float'].includes(target.side)) return layout;
  const next = copy(layout);
  const source = groupsOf(next, from.side)[from.index];
  if (target.side === 'float' && target.place === 'new') {
    if (from.side === 'float' && source.tabs.length === 1) return moveFloat(layout, from.index, target.x || 0, target.y || 0);
    leave(next, from, source, id);
    next.float.push({ tabs: [id], active: id, x: Math.max(0, Math.round(target.x || 0)), y: Math.max(0, Math.round(target.y || 0)), ...FLOAT_SIZE });
    return next;
  }
  const goal = target.place === 'end' ? null : groupsOf(next, target.side)[target.index];
  if (target.place !== 'end' && !goal) return layout;
  if (target.side === 'float' && target.place !== 'tab') return layout;
  // Nothing to do: into its own group, or splitting off a group that is only this panel.
  if (goal === source && (target.place === 'tab' || source.tabs.length === 1)) return reveal(layout, id);
  leave(next, from, source, id);
  if (target.side === 'float') {
    goal.tabs.push(id);
    goal.active = id;
    return next;
  }
  const side = next[target.side];
  if (target.place === 'tab') {
    goal.tabs.push(id);
    goal.active = id;
  } else if (target.place === 'end') {
    const size = side.groups.length ? 1 / (side.groups.length + 1) : 1;
    side.groups.push({ tabs: [id], active: id, size: size / (1 - size || 1) });
  } else {
    const half = goal.size / 2;
    goal.size = half;
    const at = side.groups.indexOf(goal) + (target.place === 'below' ? 1 : 0);
    side.groups.splice(at, 0, { tabs: [id], active: id, size: half });
  }
  evenOut(side);
  side.open = true;
  return next;
}

// Take a panel out of its group; a group left empty goes (a floating window closes).
function leave(next, from, source, id) {
  source.tabs = source.tabs.filter((t) => t !== id);
  if (source.active === id) source.active = source.tabs[0];
  if (source.tabs.length) return;
  if (from.side === 'float') {
    next.float = next.float.filter((g) => g !== source);
  } else {
    next[from.side].groups = next[from.side].groups.filter((g) => g !== source);
    evenOut(next[from.side]);
  }
}

// Move and size a floating window (px from the workspace's top left); it keeps FLOAT_MIN.
export function moveFloat(layout, index, x, y, w, h) {
  const g = layout.float?.[index];
  if (!g) return layout;
  const next = copy(layout);
  next.float[index] = { ...next.float[index], x: Math.max(0, Math.round(x)), y: Math.max(0, Math.round(y)),
    w: Math.max(FLOAT_MIN.w, Math.round(w ?? g.w)), h: Math.max(FLOAT_MIN.h, Math.round(h ?? g.h)) };
  return next;
}

// Put a floating window back on a side, all its tabs in one group at the bottom.
export function dockFloat(layout, index, side = 'right') {
  if (!layout.float?.[index] || !DOCK_SIDES.includes(side)) return layout;
  const next = copy(layout);
  const [g] = next.float.splice(index, 1);
  const groups = next[side].groups;
  const size = groups.length ? 1 / (groups.length + 1) : 1;
  groups.push({ tabs: g.tabs, active: g.active, size: size / (1 - size || 1) });
  evenOut(next[side]);
  next[side].open = true;
  return next;
}

// Drag the line between groups `index` and `index + 1` of a side by `delta` px. `heights`: each
// group's height on screen now. Both keep GROUP_MIN_HEIGHT (or share the room when there is less).
export function resizeGroups(layout, side, index, delta, heights) {
  const groups = layout[side].groups;
  if (!groups[index + 1] || heights.length !== groups.length) return layout;
  const pair = heights[index] + heights[index + 1];
  const minimum = Math.min(GROUP_MIN_HEIGHT, pair / 2);
  const upper = Math.max(minimum, Math.min(pair - minimum, heights[index] + delta));
  const sizes = [...heights];
  sizes[index] = upper;
  sizes[index + 1] = pair - upper;
  const total = sizes.reduce((sum, h) => sum + h, 0);
  const next = copy(layout);
  next[side].groups.forEach((g, i) => { g.size = total > 0 ? sizes[i] / total : 1 / sizes.length; });
  return next;
}

// Where a dragged tab would land, from what is on screen: `groups` are {side, index, top, bottom,
// left, right, tabsBottom} (the tab row ends at tabsBottom), `zones` are {side, top, bottom, left,
// right} strips along an edge where a side can take a new group (an empty or folded side). Over a
// group's tab row, or its middle, the panel joins the group; over its top or bottom third it goes
// above or below. A floating window (side 'float', listed first: it lies on top) only takes tabs.
// Over the drafting table (`board`, a rect) the panel floats: {side: 'float', place: 'new', x, y}
// with x, y the window's top left from `origin` (the workspace's top left). Anywhere else: null.
export function dropTarget(point, groups, zones = [], board = null, origin = { left: 0, top: 0 }) {
  const inside = (r) => point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom;
  const group = groups.find(inside);
  if (group?.side === 'float') return { side: 'float', index: group.index, place: 'tab' };
  if (group) {
    if (point.y <= group.tabsBottom) return { side: group.side, index: group.index, place: 'tab' };
    const share = (point.y - group.tabsBottom) / Math.max(1, group.bottom - group.tabsBottom);
    return { side: group.side, index: group.index, place: share < 1 / 3 ? 'above' : share > 2 / 3 ? 'below' : 'tab' };
  }
  const zone = zones.find(inside);
  if (zone) return { side: zone.side, index: 0, place: 'end' };
  if (board && inside(board)) return { side: 'float', index: 0, place: 'new', x: Math.round(point.x - origin.left - 40), y: Math.round(point.y - origin.top - 16) };
  return null;
}

// The layout as the server keeps it (sizes rounded so the file stays small).
export function dockForSaving(layout) {
  const side = (s) => ({ open: s.open, groups: s.groups.map((g) => ({ tabs: g.tabs, active: g.active, size: Math.round(g.size * 1000) / 1000 })) });
  const float = (layout.float || []).map((g) => ({ tabs: g.tabs, active: g.active, x: g.x, y: g.y, w: g.w, h: g.h }));
  return { left: side(layout.left), right: side(layout.right), float };
}
