// Line icons for the screen, drawn alike (20-unit box, 1.5 stroke in the text colour) so they sit
// on the text line at one weight. Decorative: the text next to an icon says what it is.

const PATHS = {
  projects: '<rect x="3" y="3" width="6" height="6" rx="1"/><rect x="11" y="3" width="6" height="6" rx="1"/><rect x="3" y="11" width="6" height="6" rx="1"/><rect x="11" y="11" width="6" height="6" rx="1"/>',
  sample: '<path d="M10 5.5C8.5 4.3 6.3 4 3.5 4.2v11c2.8-.2 5 .1 6.5 1.3 1.5-1.2 3.7-1.5 6.5-1.3v-11c-2.8-.2-5 .1-6.5 1.3z"/><path d="M10 5.5v11"/>',
  search: '<circle cx="8.5" cy="8.5" r="5"/><path d="M12.2 12.2 17 17"/>',
  plus: '<path d="M10 4v12M4 10h12"/>',
  open: '<path d="M7 13 13 7M8 7h5v5"/>',
  settings: '<path d="M8.6 2.5h2.8l.4 2 1.4.7 1.8-.9 2 2-.9 1.8.6 1.4 2 .5v2.8l-2 .4-.6 1.4.9 1.8-2 2-1.8-.9-1.4.6-.4 2H8.6l-.5-2-1.4-.6-1.8.9-2-2 .9-1.8-.6-1.4-2-.4V8.6l2-.5.6-1.4-.9-1.8 2-2 1.8.9 1.4-.7z"/><circle cx="10" cy="10" r="2.5"/>',
  // An empty parcel: a dashed lot outline, for a project whose site is not chosen yet.
  parcel: '<path d="M4 6.5 13.5 3l3 9.5-6 4.5L3.5 14z" stroke-dasharray="2.2 2"/><path d="M10 8v4M8 10h4"/>',
};

export function icon(name, className = 'icon') {
  return `<svg class="${className}" viewBox="0 0 20 20" aria-hidden="true" focusable="false">${PATHS[name] || ''}</svg>`;
}
