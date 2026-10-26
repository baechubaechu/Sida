# three.js for the drafting table

The screen (`webui/app/`) has no build step, so the parts of three.js the drafting table uses are
bundled once into `webui/app/vendor/three.js` and committed. `entry.js` lists them.

To update three.js or add a name to `entry.js`:

```bash
cd scripts/three-vendor
npm install --no-save three@0.186.1 esbuild@0.28.2
npx esbuild entry.js --bundle --format=esm --minify --legal-comments=inline --outfile=../../webui/app/vendor/three.js
rm -rf node_modules
```

three.js is MIT licensed (`webui/app/vendor/LICENSE-three.txt`).
