// UI unit tests for the preset engine in static/js/app.js (offline, Node).
//
// Covered here (task «Пресеты применяют ВСЁ»):
//   • getCurrentSettings captures queries, cities, source, socials incl.
//     required-social tiles, depth params, filters and output formats;
//   • applySettings restores all of the above (full preset round-trip);
//   • applySettings({cities:null}) (localStorage path) does NOT touch cities;
//   • resetToDefaults returns the form to the HTML defaults and clears the
//     applied-preset highlight;
//   • loadPreset applies settings + marks the applied name.
//
// Run with: node --test tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readFileSync(join(root, 'static', 'js', 'app.js'), 'utf8');

function grab(name) {
  const i = src.indexOf('function ' + name + '(');
  assert.ok(i >= 0, 'function not found in app.js: ' + name);
  let depth = 0;
  const body = src.indexOf('{', i);
  for (let k = body; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced braces while slicing: ' + name);
}
// Slice the FORM_DEFAULTS const (single expression, ends with };)
function grabConst(name) {
  const i = src.indexOf('const ' + name + ' = {');
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  const end = src.indexOf('};', i);
  return src.slice(i, end + 2);
}

// ── DOM stub ─────────────────────────────────────────────────
function mkEl(id) {
  const classes = new Set();
  const attrs = {};
  const el = {
    id, value: '', textContent: '', innerHTML: '', placeholder: '',
    hidden: true, disabled: false, title: '', checked: false, dataset: {},
    style: { setProperty: () => {}, display: '' },
    set className(v) { classes.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => classes.add(c)); },
    get className() { return [...classes].join(' '); },
    classList: {
      add: (...c) => c.forEach(x => classes.add(x)),
      remove: (...c) => c.forEach(x => classes.delete(x)),
      toggle: (c, on) => { const want = on === undefined ? !classes.has(c) : !!on; want ? classes.add(c) : classes.delete(c); },
      contains: c => classes.has(c),
    },
    _classes: classes,
    attrs,
    querySelector: () => null,
    querySelectorAll: () => [],
    setAttribute(k, v) { attrs[k] = v; },
    getAttribute(k) { return attrs[k]; },
    appendChild() {},
    closest: () => null,
  };
  return el;
}
const els = {};
for (const id of ['f-queries', 'f-city-input', 'city-tags-row', 'city-dropdown',
  'f-excel', 'f-json', 'f-csv', 'f-map', 'f-pages', 'f-workers', 'f-query-workers',
  'f-max-candidates', 'f-grad', 'f-gstep',
  'f-collapse-chains', 'f-chain-key', 'f-raw-mode', 'f-continue', 'f-continue-limit',
  'grid-mode-row', 'grid-opts', 'grid-lbl', 'grid-hint',
  'grid-radius-out', 'grid-step-out', 'grid-step-scale',
  'queries-count', 'city-count', 'clear-all-btn', 'acc-basic-summary',
  'preset-dd-wrap', 'preset-dd-list', 'preset-dd-btn', 'preset-dd-current',
  'preset-block-hint', 'preset-reset-btn', 'btn-run', 'btn-txt', 'btn-icon',
  'status-badge', 'pages-cap-note',
  // VK activity + lead score controls (accordion «Фильтрация результата»)
  'f-vk-check', 'f-vk-max-days', 'f-vk-min-followers', 'f-sort-score',
  'f-min-score', 'vk-filter-block', 'score-value', 'score-hint', 'vk-check-hint',
  'score-presets']) {
  els[id] = mkEl(id);
}
// checkbox-ish elements expose .checked via the closest('.chk') toggle
for (const id of ['f-excel', 'f-json', 'f-csv', 'f-map',
  'f-collapse-chains', 'f-continue']) {
  els[id].closest = () => mkEl('chk-' + id);
}
els['grid-mode-row'].querySelectorAll = () => [];

// requiredSocials tiles: two fake tiles, vk + tg
const socTiles = {
  vk: mkEl('tile-vk'), tg: mkEl('tile-tg'),
};
socTiles.vk.querySelector = sel => sel.includes('checkbox') ? mkEl('cb-vk') : null;
socTiles.tg.querySelector = sel => sel.includes('checkbox') ? mkEl('cb-tg') : null;
socTiles.vk.dataset = { socKey: 'vk' };
socTiles.tg.dataset = { socKey: 'tg' };

globalThis.document = {
  getElementById: id => els[id] ?? null,
  // applySettings resets/restores social tiles via #social-net-chk-grid lookups;
  // data-soc-key lives on the input inside the tile, closest('.soc-tile') — the label
  querySelector: sel => {
    if (typeof sel === 'string' && sel.includes('input[data-soc-key=')) {
      const m = /data-soc-key="([^"]+)"/.exec(sel);
      if (m) {
        const tile = socTiles[m[1]];
        return tile ? {closest: () => tile} : null;
      }
    }
    return null;
  },
  querySelectorAll: () => [],
  addEventListener: () => {},
  body: mkEl('body'),
};

const pendingTimers = [];
globalThis.setTimeout = (fn, _ms) => { pendingTimers.push(fn); return pendingTimers.length; };

// Globals the sliced functions reference
globalThis.selectedCities = [];
globalThis.citySearchText = '';
globalThis.dataSource = 'yandex';
globalThis._gridMode = 'whole';
globalThis.socialMode = 'all';
globalThis.requiredSocials = new Set();
globalThis.SLABELS = {vk:'VK',instagram:'IG',telegram:'TG',whatsapp:'WA'};
globalThis.SNAMES = {vk:'ВКонтакте',instagram:'Instagram',telegram:'Telegram',whatsapp:'WhatsApp'};
globalThis.parseMode = 'without_website';
globalThis.allResults = [];
globalThis.showToast = msg => { globalThis.__lastToast = msg; };
globalThis.renderCityTags = () => { globalThis.__citiesRendered = true; };
globalThis.updateQueriesCounter = () => {};
globalThis.updateClearAllBtn = () => {};
globalThis.updateBasicSummary = () => {};
globalThis.updateRunBtnState = () => {};
globalThis.updatePagesCapNote = () => {};
globalThis.onContinueToggle = () => {};
globalThis.onGridSlider = () => {};
globalThis.setGridMode = mode => { globalThis._gridMode = mode; };
globalThis.setDataSource = src => { globalThis.dataSource = src; };
globalThis.setSocialMode = mode => {
  globalThis.socialMode = mode;
  // Mirror the real setSocialMode: leaving «С соцсетями» clears the tile set
  if (mode !== 'with_socials') globalThis.requiredSocials.clear();
};
globalThis.setParseMode = mode => { globalThis.parseMode = mode; };
globalThis.vkMode = 'all';
globalThis.updateVkCheckHint = () => {};
globalThis.toggleRequiredSocial = key => { globalThis.requiredSocials.has(key) ? globalThis.requiredSocials.delete(key) : globalThis.requiredSocials.add(key); };
globalThis.refreshSourceKeyState = () => {};
globalThis.SETTINGS_KEY = 'yp_settings_v1';
globalThis.localStorage = {
  _s: {},
  getItem(k) { return this._s[k] ?? null; },
  setItem(k, v) { this._s[k] = String(v); },
  removeItem(k) { delete this._s[k]; },
};
globalThis.markAppliedPreset = name => { globalThis.__appliedPreset = name; };
globalThis.getPresets = () => globalThis.__presets || [];
globalThis.savePresets = p => { globalThis.__presets = p; };
globalThis.__presets = [];

(0, eval)([
  grabConst('FORM_DEFAULTS'),
  grab('getCurrentSettings'),
  grab('applySettings'),
  grab('resetToDefaults'),
  grab('loadPreset'),
  grab('saveSettings'),
  grab('updateSocialFilterHint'),
  grab('setVkMode'),
  grab('onVkCheckChange'),
  grab('onMinScoreInput'),
].join('\n'));

// ── 1. getCurrentSettings captures the full form ─────────────
test('getCurrentSettings captures cities, source, socials, depth and formats', () => {
  globalThis.selectedCities = ['Уфа', 'Москва'];
  globalThis.dataSource = '2gis';
  globalThis._gridMode = 'manual';
  globalThis.socialMode = 'with_socials';
  globalThis.requiredSocials = new Set(['vk', 'tg']);
  els['f-queries'].value = 'кафе\nбар';
  els['f-grad'].value = '30';
  els['f-gstep'].value = '8';
  els['f-excel'].checked = true;
  els['f-json'].checked = false;
  els['f-pages'].value = '10';

  const s = globalThis.getCurrentSettings();
  assert.deepEqual(s.cities, ['Уфа', 'Москва'], 'cities are saved in presets');
  assert.equal(s.source, '2gis', 'data source is saved');
  assert.equal(s.grid, true, 'grid mode saved');
  assert.equal(s.grad, '30');
  assert.equal(s.gstep, '8');
  assert.deepEqual(s.requiredSocials, ['vk', 'tg'], 'required socials saved in with_socials mode');
  assert.equal(s.pages, '10');
  assert.equal(s.excel, true);
  assert.equal(s.json, false);
  assert.equal(s.parseMode, 'without_website');
  assert.ok('collapseChains' in s && 'rawMode' in s, 'filters saved');
  // VK activity + lead score controls ride along in the preset
  assert.ok('vkCheck' in s && 'vkMode' in s && 'minScore' in s && 'sortScore' in s,
            'VK activity and lead-score settings are saved');
  // API keys never saved
  assert.ok(!('apikeys' in s) && !('yandex_key' in s));
});

// ── 1b. VK activity / lead score round-trip ──────────────────
test('VK activity and lead-score controls survive a preset round-trip', () => {
  globalThis.resetToDefaults();
  els['f-vk-check'].checked = true;
  els['f-vk-max-days'].value = '30';
  els['f-vk-min-followers'].value = '150';
  els['f-min-score'].value = '70';
  els['f-sort-score'].checked = true;
  globalThis.setVkMode('active_semi');

  const saved = globalThis.getCurrentSettings();
  assert.equal(saved.vkCheck, true);
  assert.equal(saved.vkMode, 'active_semi');
  assert.equal(saved.minScore, '70');

  globalThis.resetToDefaults();
  assert.equal(globalThis.vkMode, 'all', 'VK mode back to default');
  assert.equal(els['f-vk-check'].checked, false, 'activity check off by default');
  assert.equal(els['f-min-score'].value, 0, 'score threshold back to 0');

  globalThis.applySettings(saved);
  assert.equal(globalThis.vkMode, 'active_semi', 'VK mode restored');
  assert.equal(els['f-vk-max-days'].value, '30', 'post-age limit restored');
  assert.equal(els['f-vk-min-followers'].value, '150', 'followers floor restored');
  assert.equal(els['f-min-score'].value, '70', 'score threshold restored');
});

// ── 1c. Score slider feedback ────────────────────────────────
test('onMinScoreInput prints the threshold and how many rows still pass', () => {
  globalThis.allResults = [
    {lead_score: 85}, {lead_score: 60}, {lead_score: ''}, {lead_score: 30},
  ];
  els['f-min-score'].value = '60';
  globalThis.onMinScoreInput();
  assert.match(els['score-hint'].textContent, /Порог 60/);
  assert.match(els['score-hint'].textContent, /подходят 2 из 3/
    , 'unscored rows are not counted');
  // The active preset button mirrors the stored threshold.
  els['score-presets'] = els['score-presets'] || { querySelectorAll: () => [] };
  els['f-min-score'].value = '0';
  globalThis.onMinScoreInput();
  assert.match(els['score-hint'].textContent, /подходят 3 из 3/);
  globalThis.allResults = [];
});

// ── 2. Full round-trip: save → reset → apply restores everything ──
test('applySettings restores the full preset (round-trip)', () => {
  // Self-contained: earlier tests reset the form, so build the state here.
  globalThis.selectedCities = ['Уфа', 'Москва'];
  globalThis.dataSource = '2gis';
  globalThis._gridMode = 'manual';
  globalThis.socialMode = 'with_socials';
  globalThis.requiredSocials = new Set(['vk', 'tg']);
  els['f-grad'].value = '30';
  els['f-pages'].value = '10';

  const saved = globalThis.getCurrentSettings();
  // wipe the form
  globalThis.resetToDefaults();
  assert.equal(globalThis.selectedCities.length, 0);
  assert.equal(globalThis.dataSource, 'yandex');

  globalThis.applySettings(saved);
  assert.deepEqual(globalThis.selectedCities, ['Уфа', 'Москва'], 'cities restored');
  assert.equal(globalThis.dataSource, '2gis', 'source restored');
  assert.equal(globalThis._gridMode, 'manual', 'grid restored');
  assert.deepEqual([...globalThis.requiredSocials].sort(), ['tg', 'vk'], 'social tiles restored');
  assert.equal(els['f-grad'].value, '30');
  assert.equal(els['f-pages'].value, '10');
});

// ── 3. localStorage path keeps the «no cities» contract ─────
test('applySettings with cities:null does not touch selectedCities', () => {
  globalThis.selectedCities = ['Казань'];
  globalThis.applySettings({ queries: 'хинкальная', cities: null, source: 'yandex' });
  assert.deepEqual(globalThis.selectedCities, ['Казань'], 'localStorage reload keeps cities empty-start contract');
  assert.equal(els['f-queries'].value, 'хинкальная');
  globalThis.selectedCities = [];
});

// ── 4. Reset restores defaults everywhere ────────────────────
test('resetToDefaults returns the form to HTML defaults', () => {
  globalThis.applySettings({
    queries: 'кафе', cities: ['Сочи'], source: '2gis', grid: true, grad: 45, gstep: 10,
    socialMode: 'with_socials', requiredSocials: ['vk'], pages: 15, continueMode: true,
  });
  assert.equal(globalThis.dataSource, '2gis');

  globalThis.resetToDefaults();
  assert.equal(els['f-queries'].value, '', 'queries cleared');
  assert.deepEqual(globalThis.selectedCities, [], 'cities cleared');
  assert.equal(globalThis.dataSource, 'yandex', 'source back to Yandex');
  assert.equal(globalThis._gridMode, 'whole', 'grid off');
  assert.equal(els['f-grad'].value, 20, 'radius default');
  assert.equal(els['f-gstep'].value, 5, 'step default');
  assert.equal(globalThis.socialMode, 'all', 'social mode default');
  assert.equal(globalThis.requiredSocials.size, 0, 'social tiles cleared');
  assert.equal(els['f-pages'].value, 1, 'pages default');
  assert.equal(globalThis.parseMode, 'without_website', 'parse mode default');
  assert.equal(globalThis.__appliedPreset, null, 'applied-preset highlight cleared');
});

// ── 5. loadPreset applies + marks ────────────────────────────
test('loadPreset applies settings and shows the applied name', () => {
  globalThis.__presets = [{ name: 'Кафе 2GIS', settings: {
    queries: 'кафе', cities: ['Уфа'], source: '2gis', socialMode: 'all',
  }}];
  globalThis.loadPreset(0);
  assert.deepEqual(globalThis.selectedCities, ['Уфа']);
  assert.equal(globalThis.dataSource, '2gis');
  assert.equal(globalThis.__appliedPreset, 'Кафе 2GIS');
});
