// Line icons for the screen, drawn alike (20-unit box, 1.5 stroke in the text colour) so they sit
// on the text line at one weight. Decorative: the text next to an icon says what it is.

const PATHS = {
  projects: '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="11" y="3" width="6" height="6" rx="1"/><rect x="3" y="11" width="6" height="6" rx="1"/><rect x="11" y="11" width="6" height="6" rx="1"/>',
  sample: '<path d="M10 5.5C8.5 4.3 6.3 4 3.5 4.2v11c2.8-.2 5 .1 6.5 1.3 1.5-1.2 3.7-1.5 6.5-1.3v-11c-2.8-.2-5 .1-6.5 1.3z"/><path d="M10 5.5v11"/>',
  search: '<circle cx="8.5" cy="8.5" r="5"/><path d="M12.2 12.2 17 17"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  send: '<path d="M10 16V4M5 9l5-5 5 5"/>',
  open: '<path d="M7 13 13 7M8 7h5v5"/>',
  // A cog with rounded teeth (drawn on a 24 grid, scaled to 20; the stroke is raised to match).
  settings: '<g transform="scale(.8333)" stroke-width="1.8"><path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/></g>',
  // An empty parcel: a dashed lot outline, for a project whose site is not chosen yet.
  parcel: '<path d="M4 6.5 13.5 3l3 9.5-6 4.5L3.5 14z" stroke-dasharray="2.2 2"/><path d="M10 8v4M8 10h4"/>',
};

export function icon(name, className = 'icon') {
  return `<svg class="${className}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${PATHS[name] || ''}</svg>`;
}
