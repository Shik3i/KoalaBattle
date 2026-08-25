import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

/**
 * `phosphor.css` carries a hand-picked subset of the Phosphor font rather than all 1,530
 * glyphs. Nothing enforced that a `<i class="ph ph-…">` in a component actually had an
 * entry, and six did not: `ph-key` and `ph-download-simple` in Settings, `ph-plant` in
 * Draft setup, and three more added the same day. A missing entry has no styling and no
 * error — it renders as a blank box, which is easy to miss in review and in a screenshot.
 */

const here = dirname(fileURLToPath(import.meta.url));
const srcRoot = join(here, '..');

function svelteFiles(directory: string): string[] {
  return readdirSync(directory).flatMap((entry) => {
    const path = join(directory, entry);
    if (statSync(path).isDirectory()) return svelteFiles(path);
    return path.endsWith('.svelte') ? [path] : [];
  });
}

const defined = new Set(
  [...readFileSync(join(srcRoot, 'phosphor.css'), 'utf8').matchAll(/\.ph\.(ph-[a-z0-9-]+)::before/g)]
    .map((match) => match[1])
);

test('the icon subset defines every icon a component asks for', () => {
  const missing = new Map<string, string[]>();
  for (const file of svelteFiles(srcRoot)) {
    for (const match of readFileSync(file, 'utf8').matchAll(/\bph\s+(ph-[a-z0-9-]+)/g)) {
      if (defined.has(match[1])) continue;
      const list = missing.get(match[1]) || [];
      list.push(file.slice(srcRoot.length + 1));
      missing.set(match[1], list);
    }
  }
  const report = [...missing.entries()]
    .map(([icon, files]) => `${icon} (${[...new Set(files)].join(', ')})`)
    .join('\n  ');
  assert.equal(missing.size, 0, `icons used but not in phosphor.css:\n  ${report}`);
});

test('the subset itself is well formed', () => {
  // A typo in a codepoint is invisible too, so require the shape rather than trust it.
  const css = readFileSync(join(srcRoot, 'phosphor.css'), 'utf8');
  const entries = [...css.matchAll(/\.ph\.(ph-[a-z0-9-]+)::before\{content:'\\([0-9a-f]{4})'\}/g)];
  assert.ok(entries.length >= 70, `expected the curated subset, found ${entries.length} entries`);
  assert.equal(entries.length, defined.size, 'every declaration should carry a 4-digit codepoint');

  const seen = new Set<string>();
  const duplicates = entries.map((entry) => entry[1]).filter((icon) => !seen.add(icon));
  assert.deepEqual(duplicates, [], 'an icon is declared twice');
});
