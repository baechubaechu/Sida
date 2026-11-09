// The panels beside the drafting table, docked as the designer likes (2026-11-09 지훈): each side
// holds groups stacked top to bottom, each group shows one of its tabs. A tab can be dragged into
// another group, above or below one (splitting the side), or onto an empty side. Pure functions:
// panels.js and dock.js do the screen, the server keeps the layout on this PC.

export const DOCK_PANELS = { conductor: '대화', props: '속성', layers: '레이어', experts: '전문가' };
export const DOCK_SIDES = ['left', 'right'];
export const GROUP_MIN_HEIGHT = 120; // px: a group keeps its tabs and a few lines

export function defaultDock() {
  return {
    left: { open: true, groups: [{ tabs: ['conductor'], active: 'conductor', size: 1 }] },
    right: { open: true, groups: [{ tabs: ['props', 'layers', 'experts'], active: 'layers', size: 1 }] },
  };
}

const copy = (layout) => ({
  left: { open: layout.left.open, groups: layout.left.groups.map((g) => ({ ...g, tabs: [...g.tabs] })) },
  right: { open: layout.right.open, groups: layout.right.groups.map((g) => ({ ...g, tabs: [...g.tabs] })) },
});

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
  const layout = { left: { open: true, groups: [] }, right: { open: true, groups: [] } };
  for (const name of DOCK_SIDES) {
    const side = raw[name] && typeof raw[name] === 'object' ? raw[name] : {};
    layout[name].open = side.open !== false;
    for (const g of Array.isArray(side.groups) ? side.groups : []) {
      const tabs = [];
      for (const id of Array.isArray(g?.tabs) ? g.tabs : []) {
        if (typeof id !== 'string' || !Object.hasOwn(DOCK_PANELS, id) || seen.has(id)) continue;
        seen.add(id);
        tabs.push(id);
      }
      if (!tabs.length) continue;
      const size = Number(g.size);
      layout[name].groups.push({ tabs, active: tabs.includes(g.active) ? g.active : tabs[0], size: Number.isFinite(size) && size > 0 ? size : 1 });
    }
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

// Where a panel is: {side, index} of its group, or null.
export function dockOf(layout, id) {
  for (const side of DOCK_SIDES) {
    const index = layout[side].groups.findIndex((g) => g.tabs.includes(id));
    if (index >= 0) return { side, index };
  }
  return null;
}

// On screen: its side is open and its group shows it.
export function panelVisible(layout, id) {
  const at = dockOf(layout, id);
  return Boolean(at && layout[at.side].open && layout[at.side].groups[at.index].active === id);
}

// Has the side anything to show (open and not empty)?
export function sideShown(layout, side) {
  return layout[side].open && layout[side].groups.length > 0;
}

export function activate(layout, id) {
  const at = dockOf(layout, id);
  if (!at) return layout;
  const next = copy(layout);
  next[at.side].groups[at.index].active = id;
  return next;
}

// Bring a panel on screen: its side opens and its group turns to it.
export function reveal(layout, id) {
  const next = activate(layout, id);
  const at = dockOf(next, id);
  if (at) next[at.side].open = true;
  return next;
}

// Turn a group from one tab to another when it shows the first (selecting a paper turns 레이어 to
// 속성 when they share a group; in different groups both are already on screen).
export function swapActive(layout, from, to) {
  const at = dockOf(layout, to);
  if (!at || layout[at.side].groups[at.index].active !== from) return layout;
  return activate(layout, to);
}

export function setSideOpen(layout, side, open) {
  const next = copy(layout);
  next[side].open = open;
  return next;
}

// Move a panel. `target`: {side, index, place} where place is 'tab' (into that group), 'above' or
// 'below' it (a new group, splitting that group's height), or 'end' (a new group at the bottom of
// the side, also onto an empty side). The moved panel shows, and its side opens.
export function movePanel(layout, id, target) {
  const from = dockOf(layout, id);
  if (!from || !target || !DOCK_SIDES.includes(target.side)) return layout;
  const next = copy(layout);
  const side = next[target.side];
  const goal = target.place === 'end' ? null : side.groups[target.index];
  if (target.place !== 'end' && !goal) return layout;
  const source = next[from.side].groups[from.index];
  // Nothing to do: into its own group, or splitting off a group that is only this panel.
  if (goal === source && (target.place === 'tab' || source.tabs.length === 1)) return reveal(layout, id);
  source.tabs = source.tabs.filter((t) => t !== id);
  if (source.active === id) source.active = source.tabs[0];
  if (!source.tabs.length) {
    next[from.side].groups = next[from.side].groups.filter((g) => g !== source);
    evenOut(next[from.side]);
  }
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
// above or below. Anywhere else: null (the drop does nothing).
export function dropTarget(point, groups, zones = []) {
  const inside = (r) => point.x >= r.left && point.x <= r.right && point.y >= r.top && point.y <= r.bottom;
  const group = groups.find(inside);
  if (group) {
    if (point.y <= group.tabsBottom) return { side: group.side, index: group.index, place: 'tab' };
    const share = (point.y - group.tabsBottom) / Math.max(1, group.bottom - group.tabsBottom);
    return { side: group.side, index: group.index, place: share < 1 / 3 ? 'above' : share > 2 / 3 ? 'below' : 'tab' };
  }
  const zone = zones.find(inside);
  return zone ? { side: zone.side, index: 0, place: 'end' } : null;
}

// The layout as the server keeps it (sizes rounded so the file stays small).
export function dockForSaving(layout) {
  const side = (s) => ({ open: s.open, groups: s.groups.map((g) => ({ tabs: g.tabs, active: g.active, size: Math.round(g.size * 1000) / 1000 })) });
  return { left: side(layout.left), right: side(layout.right) };
}
