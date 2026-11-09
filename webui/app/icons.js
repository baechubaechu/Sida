// Line icons for the screen, drawn alike (20-unit box, 1.5 stroke in the text colour) so they sit
// on the text line at one weight. Decorative: the text next to an icon says what it is.

const PATHS = {
  projects: '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="11" y="3" width="6" height="6" rx="1"/><rect x="3" y="11" width="6" height="6" rx="1"/><rect x="11" y="11" width="6" height="6" rx="1"/>',
  sample: '<path d="M10 5.5C8.5 4.3 6.3 4 3.5 4.2v11c2.8-.2 5 .1 6.5 1.3 1.5-1.2 3.7-1.5 6.5-1.3v-11c-2.8-.2-5 .1-6.5 1.3z"/><path d="M10 5.5v11"/>',
  search: '<circle cx="8.5" cy="8.5" r="5"/><path d="M12.2 12.2 17 17"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  open: '<path d="M7 13 13 7M8 7h5v5"/>',
  // A cog with rounded teeth (drawn on a 24 grid, scaled to 20; the stroke is raised to match).
  settings: '<g transform="scale(.8333)" stroke-width="1.8"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></g>',
  // The drafting table's tools.
  undo: '<path d="M8 5 4 9l4 4"/><path d="M4 9h8a4 4 0 0 1 0 8H9"/>',
  redo: '<path d="m12 5 4 4-4 4"/><path d="M16 9H8a4 4 0 0 0 0 8h3"/>',
  select: '<path d="M5 3.5 15 9l-4.5 1.5L8.5 15z"/>',
  rect: '<rect x="3.5" y="5" width="13" height="10" rx="1"/>',
  push: '<path d="M4 11.5h12v4.5H4z"/><path d="M10 9V3M7.5 5.5 10 3l2.5 2.5"/>',
  move: '<path d="M10 2.5v15M2.5 10h15M10 2.5 8 4.5M10 2.5l2 2M10 17.5l-2-2M10 17.5l2-2M2.5 10l2-2M2.5 10l2 2M17.5 10l-2-2M17.5 10l-2 2"/>',
  rotate: '<path d="M15.5 10A5.5 5.5 0 1 1 13.9 6"/><path d="M15.5 3.5V7H12"/>',
  scale: '<path d="M3.5 9V3.5H9M16.5 11v5.5H11M3.5 3.5l13 13"/>',
  erase: '<path d="m8 16.5 8.5-8.5-4-4-9 9 3.5 3.5z"/><path d="M8 16.5h8.5M6 10.5l4 4"/>',
  tape: '<rect x="2.5" y="6.5" width="15" height="7" rx="1"/><path d="M6 6.5v3M9 6.5v2M12 6.5v3M15 6.5v2"/>',
  note: '<path d="M4 3.5h12v9l-4 4H4z"/><path d="M12 16.5v-4h4M7 7.5h6M7 10.5h4"/>',
  pen: '<path d="m13.5 3.5 3 3L7 16H4v-3z"/><path d="m11.5 5.5 3 3"/>',
  mass: '<path d="m10 2.5 6.5 3.5v8L10 17.5 3.5 14V6z"/><path d="M10 9.5V17.5M10 9.5l6.5-3.5M10 9.5 3.5 6"/>',
  trace: '<path d="m10 3 7.5 4L10 11 2.5 7z"/><path d="m2.5 10.5 7.5 4 7.5-4"/><path d="m2.5 14 7.5 4 7.5-4" stroke-dasharray="2 2"/>',
  photo: '<rect x="2.5" y="4" width="15" height="12" rx="1.5"/><circle cx="7" cy="8.5" r="1.5"/><path d="m2.5 14 4.5-4 3.5 3 2.5-2 4.5 3.5"/>',
  trash: '<path d="M3.5 5.5h13M8 5.5V3.5h4v2M5.5 5.5l1 11h7l1-11"/>',
  around: '<path d="M2.5 16.5h15M3.5 16.5l4-7 3 4.5 2-3 4 5.5"/><path d="M12.5 6.5h3v4"/>',
  tray: '<path d="M10 3v3M10 14v3M3 10h3M14 10h3M5 5l2 2M13 13l2 2M15 5l-2 2M7 13l-2 2"/>',
  // An empty parcel: a dashed lot outline, for a project whose site is not chosen yet.
  parcel: '<path d="M4 6.5 13.5 3l3 9.5-6 4.5L3.5 14z" stroke-dasharray="2.2 2"/><path d="M10 8v4M8 10h4"/>',
};

export function icon(name, className = 'icon') {
  return `<svg class="${className}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${PATHS[name] || ''}</svg>`;
}
