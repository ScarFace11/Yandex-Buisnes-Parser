// UI unit tests for the stats-tab quality graphics (вкладка «Статистика»):
// распределение рейтинга, готовность лидов, полнота данных.
//
// Функции чистые (строки данных → HTML/строки), поэтому, как и в
// statsdaily.test.mjs, они вырезаются из продакшн-бандла и гоняются на
// минимальных заглушках — браузер не нужен.
//
// Run with: node --test tests/ui/statscharts.test.mjs
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readAppSrc } from './_src.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readAppSrc(root);

function grabConst(name) {
  const prefix = 'const ' + name + ' = ';
  const i = src.indexOf(prefix);
  assert.ok(i >= 0, 'const not found in app.js: ' + name);
  let k = i + prefix.length;
  const open = src[k];
  let end;
  if (open === '[' || open === '{') {
    const close = open === '[' ? ']' : '}';
    let depth = 0;
    for (; k < src.length; k++) {
      if (src[k] === open) depth++;
      else if (src[k] === close) { depth--; if (!depth) break; }
    }
    end = k + 1;
  } else {
    end = src.indexOf(';', k);
  }
  return 'globalThis.' + name + ' = ' + src.slice(i + prefix.length, end) + ';';
}

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

(0, eval)(['RATING_BUCKETS', 'LEAD_BUCKETS', 'SOCIALS'].map(grabConst).join('\n'));
(0, eval)(['escapeHtml', 'scoreNum', 'scoreRating', 'barRows', 'pctBarRows',
           'ratingBucketRows', 'leadBucketRows', 'coverageRows',
           'ratingSectionHTML', 'leadSectionHTML', 'coverageSectionHTML',
           'statsEmptyArtHTML'].map(grab).join('\n'));

// Как в реальности: набор полей из «Что парсить» — заглушка, потому что
// настоящая механика (parseFields) проверяется в браузере.
let enabled = new Set(['phone', 'aggregator_url', 'socials', 'rating']);
globalThis.parseFieldsEnabled = () => enabled;
globalThis.socialsEnabled = () => enabled.has('socials');

const row = o => Object.assign({
  phone: '', website: '', aggregator_url: '', rating: null, reviews_count: 0,
  lead_score: null, vk: '', telegram: '', instagram: '', whatsapp: '',
}, o);

// ── Распределение рейтинга ─────────────────────────────────────────
test('рейтинг раскладывается по корзинам, включая шкалу 0..50 и запятую', () => {
  const rows = [
    row({ rating: 5 }),        // ровно 5,0
    row({ rating: '4,6' }),    // строка с запятой
    row({ rating: 46 }),       // шкала 0..50 → 4.6
    row({ rating: 3.9 }),      // ниже 4,0
    row({ rating: null }),     // без оценки
  ];
  const buckets = ratingBucketRows(rows);
  // Четыре непустые корзины: 5,0 · 4,5–4,9 · ниже 4,0 · Без оценки.
  assert.equal(buckets.length, 4);
  assert.deepEqual(buckets.map(b => [b.label, b.count]), [
    ['5,0', 1], ['4,5 – 4,9', 2], ['ниже 4,0', 1], ['Без оценки', 1],
  ]);
  // Цвета — токены темы, а не hex: иначе полоса не переключается с темой.
  for (const b of buckets) assert.match(b.color, /^var\(--/);
});

test('рейтинг: без единой оценки корзин нет (секция не рисуется)', () => {
  assert.equal(ratingBucketRows([row({}), row({ rating: null })]), null);
});

test('секция рейтинга пустая строка без данных, с данными — полосы с токенами', () => {
  assert.equal(ratingSectionHTML([row({})]), '');
  const html = ratingSectionHTML([row({ rating: 5 }), row({ rating: 3 })]);
  assert.match(html, /Распределение рейтинга/);
  assert.match(html, /var\(--grn\)/);
  assert.match(html, /var\(--red\)/);
});

// ── Готовность лидов ────────────────────────────────────────────────
test('лиды: горячие/тёплые/холодные по порогам 70/45, «Не оценены» отдельно', () => {
  const rows = [
    row({ lead_score: 72 }), row({ lead_score: 70 }),
    row({ lead_score: 50 }), row({ lead_score: 45 }),
    row({ lead_score: 10 }), row({ lead_score: null }), row({ lead_score: '' }),
  ];
  const info = leadBucketRows(rows);
  assert.deepEqual(info.rows.map(b => [b.label, b.count]), [
    ['Горячие, 70+', 2], ['Тёплые, 45–69', 2], ['Холодные, 0–44', 1], ['Не оценены', 2],
  ]);
  assert.equal(info.hot, 2, 'hot — счётчик для карточки «Горячих лидов»');
});

test('лиды: старые файлы без lead_score не рисуют секцию вовсе', () => {
  assert.equal(leadBucketRows([row({}), row({ lead_score: '' })]), null);
  assert.equal(leadSectionHTML([row({})]), '');
});

// ── Полнота данных ──────────────────────────────────────────────────
test('полнота данных считает от всех записей и уважает «Что парсить»', () => {
  const rows = [
    row({ phone: '+7 999', rating: 4.5, vk: 'https://vk.com/x' }),
    row({ aggregator_url: 'https://site.ru' }),
    row({}),
  ];
  let cov = coverageRows(rows);
  assert.deepEqual(cov.map(r => [r.label, r.count, r.total]), [
    ['Телефон', 1, 3], ['Сайт / Таплинк', 1, 3], ['Соцсети', 1, 3], ['Рейтинг', 1, 3],
  ]);

  // Выключили соцсети и рейтинг — строк не должно быть вовсе, а не «0%».
  enabled = new Set(['phone', 'aggregator_url']);
  cov = coverageRows(rows);
  assert.deepEqual(cov.map(r => r.label), ['Телефон', 'Сайт / Таплинк']);
  enabled = new Set(['phone', 'aggregator_url', 'socials', 'rating']);
});

test('полосы полноты показывают процент, ширина — от всех записей', () => {
  const html = pctBarRows(coverageRows([
    row({ phone: '1' }), row({ phone: '2' }), row({ phone: '' }),
  ]));
  // 2 из 3 = 67%, и это ширина полосы, и подпись, и значение справа.
  assert.match(html, /width:67%/);
  assert.match(html, /<div class="bar-val">67%<\/div>/);
  assert.match(html, /background:var\(--c\)/);
  // Ни одно поле не включено — секция не рисуется вовсе, а не «0%» везде.
  enabled = new Set();
  assert.equal(coverageSectionHTML([row({})]), '');
  enabled = new Set(['phone', 'aggregator_url', 'socials', 'rating']);
});

// ── Иллюстрация пустого состояния ───────────────────────────────────
test('иллюстрация пустой статистики декоративна и без hex-цветов', () => {
  const html = statsEmptyArtHTML();
  assert.match(html, /aria-hidden="true"/);
  assert.doesNotMatch(html, /#[0-9a-fA-F]{3,8}/, 'цвета — через CSS-классы токенов');
});
