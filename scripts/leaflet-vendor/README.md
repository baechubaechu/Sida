# Leaflet for the site map

The site page's map (the "찾기" tab, `webui/app/site-map.js`) uses Leaflet. The screen has no
build step, so Leaflet's ES module build is minified once into `webui/app/vendor/leaflet.js` and
committed with its stylesheet `webui/app/vendor/leaflet.css`. Marker and layer-control images are
not copied: the map uses neither.

To update Leaflet:

```bash
cd scripts/leaflet-vendor
npm pack leaflet@1.9.4 && tar xzf leaflet-1.9.4.tgz
npx esbuild@0.28.2 package/dist/leaflet-src.esm.js --minify --format=esm --legal-comments=inline --outfile=../../webui/app/vendor/leaflet.js
cp package/dist/leaflet.css ../../webui/app/vendor/leaflet.css
cp package/LICENSE ../../webui/app/vendor/LICENSE-leaflet.txt
rm -rf package leaflet-1.9.4.tgz
```

Leaflet is BSD 2-Clause licensed (`webui/app/vendor/LICENSE-leaflet.txt`).
