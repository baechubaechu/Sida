// Presentation state only. Drafts and selected-paper contexts belong to each saved talk.
export function talkMenu(current, action, id = '') {
  return action === 'toggle' && current !== id ? id : '';
}

export function talkPanel(state, action, id = '') {
  switch (action) {
    case 'toggle': return { ...state, open: !state.open };
    case 'close': return { ...state, open: false };
    case 'show': return { ...state, open: true };
    case 'list': return { ...state, open: true, list: !state.list };
    case 'select': return { ...state, open: true, active: id, list: false };
    case 'new': return { ...state, open: true, active: '', list: false };
    case 'remove': return { ...state, active: state.active === id ? '' : state.active, list: true };
    default: return state;
  }
}

export function panelShown(state, pane, narrow) {
  return state.open && (!narrow || pane === 'conductor');
}

// null means the project has just opened; '' means the designer chose a new conversation.
export function initialTalk(talks, active) {
  return active === null ? (talks.at(-1)?.id || '') : active;
}

// Widths include the 12px resize gutters. Keep room for the drafting table. `minimums` overrides
// a side's narrowest width (a docked side holding Conductor needs more than one of lists).
export function panelWidths(total, ratios, { left = true, right = true, detail = false, minimums = {} } = {}) {
  const minimum = { left: left ? minimums.left ?? 280 : 0, right: right ? minimums.right ?? (detail ? 320 : 240) : 0 };
  const budget = Math.max(0, total - 320);
  let l = left ? Math.max(minimum.left, total * ratios.left) : 0;
  let r = right ? Math.max(minimum.right, total * ratios.right) : 0;
  if (l + r > budget) {
    const floor = minimum.left + minimum.right;
    if (floor > budget) {
      l = floor ? budget * minimum.left / floor : 0;
      r = budget - l;
    } else {
      const extra = l + r - floor;
      const room = budget - floor;
      l = minimum.left + (extra ? (l - minimum.left) * room / extra : 0);
      r = budget - l;
    }
  }
  l = Math.round(l); r = Math.round(r);
  return { left: l, right: r, board: Math.max(0, total - l - r) };
}

export function resizePanel(widths, side, delta, minimum = side === 'left' ? 280 : 240) {
  const maximum = widths[side] + widths.board - 320;
  const value = Math.round(Math.max(Math.min(minimum, maximum), Math.min(maximum, widths[side] + delta)));
  return { ...widths, [side]: value, board: widths.board + widths[side] - value };
}
