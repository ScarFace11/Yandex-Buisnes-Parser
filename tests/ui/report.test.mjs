// UI unit tests for the «Сообщить о проблеме» window (static/js, offline Node).
//
// Covered here:
//   • composeReportBody joins the description with the checked context parts
//     and survives a missing/empty description;
//   • _serverSection picks the right «## …» block out of the server context;
//   • buildIssueUrl encodes title/labels/body into a GitHub new-issue URL and
//     reports the trimmed body when the context is too long for a URI.
//
// The window's DOM mechanics and clipboard screenshot live in the browser and
// are covered by tests/test_a11y_keyboard.py; here we only need the pure
// text/URL builders, which is what could actually break silently.
//
// Run with: node --test tests/ui/
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import { readFileSync } from 'node:fs';
import { readAppSrc } from './_src.mjs';

const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const src = readAppSrc(root);

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
function grabConst(name) {
  // Защищаем границу слова: иначе поиск 'const REPORT_' находит и REPORT_REPO,
  // и REPORT_REPO…REPORT_CTX_PARTS, и grabConst('REPORT_REPO') возвращает
  // кусок, где повторно объявлены соседние константы — eval падает на
  // «Identifier already declared».
  const startRe = new RegExp('const\\s+' + name + '\\s*=');
  const m = startRe.exec(src);
  assert.ok(m, 'const not found in app.js: ' + name);
  const i = m.index;
  // Тип литерала определяем по первому значимому символу после «=».
  // Строка кончается первой «';» на своей строке. Массив — «];», объект —
  // «};»: у REPORT_LABELS/REPORT_CTX_PARTS это «];», и искать «};» — значит
  // схватить чужой код дальше по файлу (eval падает на «Unexpected end of
  // input»). Брать «';» у массива тоже нельзя: внутри есть строки lbl: '…'.
  const eq = src.indexOf('=', i) + 1;
  let j = eq;
  while (j < src.length && /\s/.test(src[j])) j++;
  let end;
  if (src[j] === '\'' || src[j] === '"') {
    end = src.indexOf("';", i) + 2;
  } else {
    const arrEnd = src.indexOf('];', i);
    const objEnd = src.indexOf('};', i);
    const both = [arrEnd, objEnd].filter(x => x >= 0);
    assert.ok(both.length, 'конец литерала не найден: ' + name);
    end = Math.min(...both) + 2;
  }
  assert.ok(end > i + 2, 'const looks empty: ' + name);
  return src.slice(i, end);
}

(0, eval)([
  grabConst('REPORT_REPO'),
  grabConst('REPORT_LABELS'),
  grabConst('REPORT_CTX_PARTS'),
  grab('composeReportBody'),
  grab('_serverSection'),
  grab('_issueUrl'),
  grab('buildIssueUrl'),
  grab('collectBrowserSettings'),
  grab('applyImportedBrowserSettings'),
  grab('_shotPngBlob'),
].join('\n'));

// Контрольное значение репозитория. В eval объявлен const — он лежит в
// global-лексическом окружении, а не в globalThis, поэтому читать его отсюда
// как свойства нельзя; строка держится здесь рядом с источником.
const REPO = 'ScarFace11/Yandex-Buisnes-Parser';

// ── composeReportBody ────────────────────────────────────────
test('composeReportBody joins description and context parts', () => {
  const body = globalThis.composeReportBody(
    'Парсёр падает на Уфе',
    ['## Версия, система и браузер\n✔ 3.2.1', '## Прогоны и кэш\n⚠ давно']);
  assert.equal(body,
    'Парсёр падает на Уфе\n\n---\n\n## Версия, система и браузер\n✔ 3.2.1\n\n## Прогоны и кэш\n⚠ давно');
});

test('composeReportBody works without a description and without parts', () => {
  assert.equal(globalThis.composeReportBody('', ['## A']), '(описание не заполнено)\n\n---\n\n## A');
  assert.equal(globalThis.composeReportBody('только текст', []), 'только текст');
  assert.equal(globalThis.composeReportBody(null, null), '(описание не заполнено)');
});

// ── _serverSection ───────────────────────────────────────────
test('_serverSection extracts the matching section and ignores others', () => {
  const ctx = '## Версия, система и браузер\n✔ 3.2.1\n\n## Прогоны и кэш\n⚠ давно\n\n## Сохранённые пресеты\n- Уфа';
  assert.equal(globalThis._serverSection(ctx, 'Прогоны и кэш'), '## Прогоны и кэш\n⚠ давно');
  assert.equal(globalThis._serverSection(ctx, 'Нет такого'), '', 'нет раздела — пустая строка');
  assert.equal(globalThis._serverSection('', 'Версия'), '', 'пустой контекст не роняет');
});

// ── buildIssueUrl ────────────────────────────────────────────
test('buildIssueUrl points at the repo issue form with encoded parts', () => {
  const made = globalThis.buildIssueUrl({
    title: 'Баг: падает на Уфе',
    labels: ['bug', 'enhancement'],
    body: 'Шаги:\n1. Уфа\n2. Старт',
  });
  assert.ok(made.url.startsWith('https://github.com/' + REPO + '/issues/new?'),
    'URL ведёт на new issue: ' + made.url);
  assert.ok(made.url.includes('title=' + encodeURIComponent('Баг: падает на Уфе')));
  assert.ok(made.url.includes('labels=' + encodeURIComponent('bug,enhancement')),
    'метки через запятую и кодируются целиком');
  assert.ok(made.url.includes('body=' + encodeURIComponent('Шаги:\n1. Уфа\n2. Старт')),
    'тело кодируется, переводы строк сохраняются');
  assert.equal(made.truncated, false, 'короткое тело не обрезается');
  assert.equal(made.body, 'Шаги:\n1. Уфа\n2. Старт', 'тело возвращается как есть');
});

test('buildIssueUrl fills defaults and omits labels when none chosen', () => {
  const made = globalThis.buildIssueUrl({ title: '  ', labels: [], body: '' });
  assert.ok(made.url.includes('title=' + encodeURIComponent('Сообщение из приложения')),
    'пустой заголовок заменяется заглушкой');
  assert.ok(!made.url.includes('labels='), 'без меток параметра labels нет');
});

test('buildIssueUrl trims context sections when the URI would be too long', () => {
  // Два больших раздела: целиком URL не укладывается в лимит, после сброса
  // последнего — укладывается. Описание пользователя (важнее контекста)
  // остаётся всегда.
  const big = 'x'.repeat(4000);
  const body = 'описание\n\n## Раздел 1\n' + big + '\n\n## Раздел 2\n' + big;
  const made = globalThis.buildIssueUrl({ title: 'Длинный', labels: ['bug'], body });
  assert.ok(made.truncated, 'обрезанное тело помечено как обрезанное');
  assert.ok(made.url.length <= 7000, 'URL в пределах лимита: ' + made.url.length);
  assert.ok(made.body.includes('## Раздел 1'), 'предыдущий раздел остаётся');
  assert.ok(!made.body.includes('## Раздел 2'), 'последний раздел отброшен');
  assert.match(made.body, /опущены из-за длины/, 'обрезка помечена в конце тела');
});

// ── collectBrowserSettings ─────────────────────────────────────
// Снимок localStorage для «Экспорта настроек»: только свои ключи (yp_)
// и только строки — остальное серверу не нужно, а чужое туда ехать не должно.
test('collectBrowserSettings keeps only yp_ string entries', () => {
  const data = {
    yp_theme_v1: 'dark',
    yp_settings_v1: '{"query":"кафе"}',
    foreign_key: 'чужое',
  };
  const keys = Object.keys(data).concat('yp_num');
  const store = {
    get length() { return keys.length; },
    key: i => keys[i],
    getItem: k => (k === 'yp_num' ? 42 : data[k]),
  };
  assert.deepEqual(globalThis.collectBrowserSettings(store), {
    yp_theme_v1: 'dark',
    yp_settings_v1: '{"query":"кафе"}',
  });
});

test('collectBrowserSettings survives a broken store and returns an object', () => {
  const store = {
    get length() { throw new Error('private mode'); },
    key() { return null; },
    getItem() { return null; },
  };
  assert.deepEqual(globalThis.collectBrowserSettings(store), {});
  // Без store и без localStorage (node) — пустой объект, а не исключение.
  assert.deepEqual(globalThis.collectBrowserSettings(null), {});
});

// ── applyImportedBrowserSettings ───────────────────────────────
test('applyImportedBrowserSettings writes only yp_ strings and counts them', () => {
  const put = {};
  const store = { setItem: (k, v) => { put[k] = v; } };
  const n = globalThis.applyImportedBrowserSettings(
    { yp_a: '1', evil: 'x', yp_num: 3, other: 'y' }, store);
  assert.equal(n, 1, 'записан ровно один свой строковый ключ');
  assert.deepEqual(put, { yp_a: '1' });
  assert.equal(globalThis.applyImportedBrowserSettings(null, store), 0);
  assert.equal(globalThis.applyImportedBrowserSettings('мусор', store), 0);
});

// ── _shotPngBlob ───────────────────────────────────────────────
// Кнопка «Скопировать скриншот в буфер» кладёт в буфер image/png.
test('_shotPngBlob decodes a png dataURL into an image/png blob', async () => {
  const b64 = Buffer.from('hello screenshot').toString('base64');
  const blob = await globalThis._shotPngBlob('data:image/png;base64,' + b64);
  assert.ok(blob instanceof Blob, 'возвращается блоб');
  assert.equal(blob.type, 'image/png');
  assert.equal(await blob.text(), 'hello screenshot');
});

test('_shotPngBlob returns null instead of throwing on garbage', async () => {
  assert.equal(await globalThis._shotPngBlob(''), null);
  assert.equal(await globalThis._shotPngBlob(null), null);
});
