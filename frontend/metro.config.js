// metro.config.js
const { getDefaultConfig } = require("expo/metro-config");
const path = require('path');
const { FileStore } = require('metro-cache');
const exclusionList = require('metro-config/private/defaults/exclusionList').default;

const config = getDefaultConfig(__dirname);

// Use a stable on-disk store (shared across web/android)
const root = process.env.METRO_CACHE_ROOT || path.join(__dirname, '.metro-cache');
config.cacheStores = [
  new FileStore({ root: path.join(root, 'cache') }),
];

// ------------------------------------------------------------------
// Reduce file-watcher pressure so we don't hit `ENOSPC` on Linux
// containers with low `fs.inotify.max_user_instances`.
// Skip walking / watching noisy node_modules subtrees that Metro
// never needs to resolve for a JS/TS bundle.
// ------------------------------------------------------------------
config.resolver.blockList = exclusionList([
  // Deep native / build artifacts inside any nested node_modules.
  // Only match well-known noise dirs at package root, NOT deep vendored
  // sources (e.g. `react-native-web/dist/vendor/*`) that Metro actually
  // needs to resolve.
  /node_modules\/[^/]+\/android(\/.*)?/,
  /node_modules\/[^/]+\/ios(\/.*)?/,
  /node_modules\/[^/]+\/windows(\/.*)?/,
  /node_modules\/[^/]+\/macos(\/.*)?/,
  /node_modules\/.*\/__tests__(\/.*)?/,
  /node_modules\/.*\/__fixtures__(\/.*)?/,
  /node_modules\/[^/]+\/docs(\/.*)?/,
  /node_modules\/[^/]+\/example(\/.*)?/,
  /node_modules\/[^/]+\/examples(\/.*)?/,
  /node_modules\/.*\/\.git(\/.*)?/,
  /node_modules\/.*\/\.bin(\/.*)?/,
  /node_modules\/[^/]+\/man(\/.*)?/,
]);

// Reduce the number of workers to decrease resource usage
config.maxWorkers = 2;

module.exports = config;
