#!/usr/bin/env node
/**
 * post-export-fix.js — MUST run right after `npx expo export`.
 * =============================================================================
 *
 * WHY
 *   Expo places vendored `.ttf` icon-font assets under
 *     webapp/assets/node_modules/@expo/vector-icons/…/Fonts/*.ttf
 *   The `node_modules` segment in that path triggers electron-builder's
 *   node-modules pruning heuristic. Even when they sit deep inside a
 *   whitelisted directory like `webapp/**\/*`, ANY folder literally named
 *   `node_modules` is stripped before packaging. Net effect: the built
 *   `app.asar` contains ZERO .ttf files → every vector-icon glyph
 *   renders as a ☐ box on the Windows Electron desktop shell.
 *   (Verified with `npx asar list` against a locally-packed build.)
 *
 * WHAT WE DO
 *   1. Rename       webapp/assets/node_modules  →  webapp/assets/_pkg_
 *   2. Rewrite      every reference `assets/node_modules/` in the exported
 *                   .js/.html/.map/.json files → `assets/_pkg_/`
 *   Electron-builder now sees no `node_modules` folder, so it packages
 *   every .ttf into `app.asar` intact, and Chromium resolves the
 *   FontFace URL correctly.
 *
 * WHERE TO CALL FROM
 *   • Automatically from `electron/build-windows.bat` immediately after
 *     `npx expo export …` and before `yarn dist`.
 *   • Manually:  node electron/post-export-fix.js  <webapp-dir>
 */
const fs = require('fs');
const path = require('path');

const WEBAPP = path.resolve(process.argv[2] || path.join(__dirname, 'webapp'));
const FROM   = 'node_modules';   // dir name to hide
const TO     = '_pkg_';          // benign replacement

function rewriteTextFile(filePath) {
  const buf = fs.readFileSync(filePath);
  // Only rewrite text; skip if the file has NUL bytes early on.
  if (buf.length > 4 && buf[0] === 0x00 && buf[1] === 0x01 && buf[2] === 0x00 && buf[3] === 0x00) return false;
  const txt = buf.toString('utf8');
  // Two patterns — the leading slash form and the query-encoded form.
  const patched = txt
    .split('assets/node_modules/').join('assets/' + TO + '/')
    .split('assets%2Fnode_modules%2F').join('assets%2F' + TO + '%2F');
  if (patched !== txt) {
    fs.writeFileSync(filePath, patched, 'utf8');
    return true;
  }
  return false;
}

function walk(dir, cb) {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    const st   = fs.statSync(full);
    if (st.isDirectory()) walk(full, cb);
    else if (st.isFile()) cb(full);
  }
}

function main() {
  if (!fs.existsSync(WEBAPP)) {
    console.error('post-export-fix: WEBAPP not found:', WEBAPP);
    process.exit(1);
  }
  const src = path.join(WEBAPP, 'assets', FROM);
  const dst = path.join(WEBAPP, 'assets', TO);

  if (fs.existsSync(src)) {
    // If a stale destination exists (previous run), remove it first.
    if (fs.existsSync(dst)) fs.rmSync(dst, { recursive: true, force: true });
    fs.renameSync(src, dst);
    console.log(`[post-export-fix] renamed  ${src}\n                    →  ${dst}`);
  } else if (fs.existsSync(dst)) {
    console.log('[post-export-fix] destination already exists — skipping rename');
  } else {
    console.log('[post-export-fix] no node_modules folder found — nothing to rename');
    return;
  }

  // Rewrite every text asset that could reference the old path.
  const targetExts = new Set(['.js', '.mjs', '.html', '.htm', '.css', '.json', '.map', '.txt']);
  let patched = 0, scanned = 0;
  walk(WEBAPP, (file) => {
    if (!targetExts.has(path.extname(file).toLowerCase())) return;
    scanned++;
    if (rewriteTextFile(file)) patched++;
  });
  console.log(`[post-export-fix] rewrote references in ${patched}/${scanned} text files`);
}

main();
