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
  '11-app-init.js',
  '12-setup-summary.js',
  '13-spheres.js',
];

export function readAppSrc(r = root) {
  return JS_MODULES.map(f => readFileSync(join(r, 'static', 'js', f), 'utf8')).join('');
}

// ── Общая часть модальных окон ────────────────────────────────────
// Модалки зовут modalA11y (роль, имя, фокус, ловушка Tab). Он живёт
// в 01-core-state.js и работает с настоящим DOM: getAttribute,
// MutationObserver, document.activeElement, addEventListener. Заглушка
// node-тестов такого DOM не даёт, поэтому здесь подменяется пустышка.
//
// Это осознанно: эти тесты проверяют СОДЕРЖИМОЕ окна (поля, кнопки,
// валидацию, закрытие), а сама механика окна проверяется в настоящем
// браузере — tests/test_a11y_keyboard.py.
export const MODAL_A11Y_STUB = [
  '// modalA11y — заглушка: механика окна проверяется в браузере.',
  'globalThis.MODAL_FOCUSABLE = globalThis.MODAL_FOCUSABLE || \'\';',
  'globalThis.modalA11y = globalThis.modalA11y || (() => null);',
].join('\n');
