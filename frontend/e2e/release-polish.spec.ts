import { expect, test, type APIRequestContext } from '@playwright/test';

const apiBase = process.env.KOALABATTLE_E2E_API_URL || 'http://localhost:8001';

function configuration() {
  return {
    timeout_seconds: 300,
    max_retries: 1,
    fallback: 'random',
    temperature: null,
    max_output_tokens: 2048,
    reasoning_effort: null,
    base_url: null,
    maximum_cost: null,
    fake_scenario: 'valid'
  };
}

async function createDraft(request: APIRequestContext, seed = 20260822) {
  const response = await request.post(`${apiBase}/api/challenges`, {
    data: {
      name: 'Playwright release regression',
      definition_id: 'kanto-gym-gauntlet',
      seed,
      draft_controller: { kind: 'human', provider: null, model: null, configuration: configuration() },
      battle_controller: { agent_type: 'tactical-auto', provider: null, model: null, configuration: configuration() },
      opponent_controller: { agent_type: 'tactical-auto', provider: null, model: null, configuration: configuration() },
      battle_experience: 'quick-sim',
      difficulty: 'normal'
    },
    timeout: 45_000
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json() as Promise<{ run: { id: string } }>;
}

test('primary IA and Draft remain usable at 390px without overflow', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/challenges/new');

  const primary = page.getByRole('navigation', { name: 'Primary navigation' });
  await expect(primary.getByRole('link')).toHaveCount(3);
  await expect(primary.getByRole('link', { name: 'Home' })).toBeVisible();
  await expect(primary.getByRole('link', { name: 'Battle' })).toBeVisible();
  await expect(primary.getByRole('link', { name: 'Draft' })).toBeVisible();
  await expect(page.getByText('AI drafts for me')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Start drafting' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
});

test('Draft rarity, pick and reload recovery work in a real browser', async ({ page, request }) => {
  const created = await createDraft(request);
  await page.goto(`/challenges/${created.run.id}`);

  const choices = page.getByRole('button', { name: /^Draft / });
  await expect(choices).toHaveCount(3);
  await expect(choices.first()).toHaveAttribute('aria-label', /Smogon Draft Points/);
  await choices.first().click();
  await expect(page.getByRole('heading', { name: '1 / 6' })).toBeVisible();

  await page.reload();
  await expect(page.getByRole('heading', { name: '1 / 6' })).toBeVisible();
  await expect(page.getByRole('button', { name: /^Draft / })).toHaveCount(3);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
});

test('an unavailable reroll explains itself and the active-game shell stays compact', async ({ page, request }) => {
  const consoleErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  const created = await createDraft(request, 1787424372);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/challenges/${created.run.id}`);
  await page.getByRole('button', { name: /^Draft Metagross/ }).click();

  const reroll = page.getByRole('button', { name: /Reroll Pokémon/ });
  await expect(reroll).toHaveAttribute('aria-disabled', 'true');
  await expect(reroll).toHaveAttribute('title', /remaining pool cannot fill another offer/i);
  await reroll.focus();
  await expect(page.locator('.reroll-control').first()).toHaveAttribute('data-tooltip', /remaining pool cannot fill another offer/i);
  expect(await page.locator('.app-header').evaluate((header) => Math.round(header.getBoundingClientRect().height))).toBe(56);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
  expect(consoleErrors).toEqual([]);
});

test('Battle and Replay use the renderer while private audit stays collapsed', async ({ page, request }) => {
  const response = await request.post(`${apiBase}/api/matches`, {
    data: {
      name: 'Playwright renderer regression',
      format: 'gen9randombattle',
      player1: { display_name: 'Alpha', agent_type: 'random', team_source: 'showdown-random' },
      player2: { display_name: 'Beta', agent_type: 'random', team_source: 'showdown-random' },
      random_seed: 20260822,
      team_policy: 'showdown-random',
      limits: { maximum_total_cost: null, maximum_turns: 5 }
    }
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  const match = await response.json() as { id: string };

  await page.goto(`/battle/${match.id}`);
  await expect(page.locator('.battle-renderer')).toBeVisible();
  await expect(page.locator('.gen5-hp-track').first()).toBeVisible();
  const audit = page.locator('details.audit-drawer');
  await expect(audit).not.toHaveAttribute('open', '');

  await expect.poll(async () => {
    const archive = await request.get(`${apiBase}/api/matches/${match.id}/presentation`);
    return (await archive.json() as { status: string }).status;
  }, { timeout: 120_000 }).toBe('completed');

  await page.goto(`/replay/${match.id}`);
  await expect(page.locator('.battle-renderer')).toBeVisible();
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Pause', exact: true })).toBeVisible();
});
