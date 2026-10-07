// Единый источник текста фронтенд-скриптов для node-тестов.
//
// static/js/app.js разделён на последовательные модули (01-…11-…); тесты
// читают их склейку в исходном порядке — текст байт-в-байт совпадает со
// старым единым файлом, поэтому grab()/indexOf работают без изменений.
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';

export const root = join(dirname(fileURLToPath(import.meta.url)), '..', '..');

// Порядок обязан совпадать с порядком подключения в templates/index.html.
export const JS_MODULES = [
  '01-core-state.js',
  '02-app-shell.js',
  '03-log-run.js',
  '04-results-table.js',
  '05-results-bulk.js',
  '06-map-stats.js',
  '07-stats-daily.js',
  '08-presets-notify.js',
  '09-ui-extras.js',
  '10-templates.js',
  '11-bulk-sender-init.js',
];

export function readAppSrc(r = root) {
  return JS_MODULES.map(f => readFileSync(join(r, 'static', 'js', f), 'utf8')).join('');
}
