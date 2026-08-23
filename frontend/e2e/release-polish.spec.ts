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
      difficulty: 'normal',
      opponent_team_mode: 'original',
      draft_rules: { roster_size: 6, rerolls: 3, type_rerolls: 1, generation_rerolls: 1, choice_count: 3, species_clause: true, draft_pool_mode: 'base-forms-only' }
    },
    timeout: 45_000
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return response.json() as Promise<{ run: { id: string } }>;
}

test('Draft Quick Start skips setup with Fast Auto, Normal and Fast Watch', async ({ page, request }) => {
  await page.goto('/challenges');

  const quickStart = page.getByRole('button', { name: 'Quick Start: Fast Auto, Normal difficulty, Fast Watch, base forms only, original teams' });
  await expect(quickStart).toBeVisible();
  await expect(quickStart).toContainText('Fast Auto · Normal · Fast Watch');
  await expect(quickStart).toContainText('Base forms · Original teams');
  await quickStart.click();
  await expect(page).toHaveURL(/\/challenges\/[0-9a-f-]+$/);

  const runId = page.url().split('/').at(-1);
  expect(runId).toBeTruthy();
  const response = await request.get(`${apiBase}/api/challenges/${runId}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const view = await response.json() as {
    unseen_candidate_count: number;
    run: {
      battle_controller: { agent_type: string };
      opponent_controller: { agent_type: string };
      battle_experience: string;
      difficulty: string;
      opponent_team_mode: string;
      draft_pool: { candidates: Array<{ evolution_stage: number }> };
      definition: { draft_rules: { choice_count: number; roster_size: number; draft_pool_mode: string } };
    };
  };
  expect(view.run.battle_controller.agent_type).toBe('tactical-auto');
  expect(view.run.opponent_controller.agent_type).toBe('tactical-auto');
  expect(view.run.battle_experience).toBe('fast-watch');
  expect(view.run.difficulty).toBe('normal');
  expect(view.run.opponent_team_mode).toBe('original');
  expect(view.run.definition.draft_rules).toMatchObject({ choice_count: 3, roster_size: 6, draft_pool_mode: 'base-forms-only' });
  expect(view.unseen_candidate_count).toBeGreaterThan(100);
  expect(view.run.draft_pool.candidates.length).toBeGreaterThan(0);
  expect(view.run.draft_pool.candidates.every((candidate) => candidate.evolution_stage === 0)).toBeTruthy();
});

test('Custom Draft persists normal pool and filled opponent team choices', async ({ page, request }) => {
  await page.goto('/challenges/new');

  const baseOnly = page.getByRole('button', { name: /Base forms only/ });
  const allForms = page.getByRole('button', { name: /All forms/ });
  const originalTeams = page.getByRole('button', { name: /Original teams/ });
  const filledTeams = page.getByRole('button', { name: /Filled teams/ });
  await expect(baseOnly).toHaveAttribute('aria-pressed', 'true');
  await expect(originalTeams).toHaveAttribute('aria-pressed', 'true');
  await allForms.click();
  await filledTeams.click();
  await page.getByRole('button', { name: 'Start drafting' }).click();
  await expect(page).toHaveURL(/\/challenges\/[0-9a-f-]+$/);

  const runId = page.url().split('/').at(-1);
  const response = await request.get(`${apiBase}/api/challenges/${runId}`);
  expect(response.ok(), await response.text()).toBeTruthy();
  const view = await response.json() as {
    run: {
      opponent_team_mode: string;
      definition: { draft_rules: { draft_pool_mode: string } };
    };
  };
  expect(view.run.opponent_team_mode).toBe('filled');
  expect(view.run.definition.draft_rules.draft_pool_mode).toBe('all-forms');
});

test('Custom Draft exposes every regional route and the shared multi-generation run', async ({ page }) => {
  await page.goto('/challenges/new?definition=all-generations-gauntlet');

  await expect(page.getByRole('heading', { name: 'All Generations Gauntlet' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'All regions' })).toBeVisible();
  await expect(page.getByText('One draft · every region')).toBeVisible();
  await expect(page.getByRole('button', { name: /Johto Gym Gauntlet/ })).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByRole('button', { name: /All Generations Gauntlet/ })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByText('110 stages · Gen I–IX')).toBeVisible();
});

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
  const pageErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
  const created = await createDraft(request, 1);
  await page.goto(`/challenges/${created.run.id}`);

  const reroll = page.getByRole('button', { name: /Reroll Pokémon/ });
  await expect(reroll).toHaveAttribute('aria-disabled', 'true');
  await expect(reroll).toHaveAttribute('title', /remaining pool cannot fill another offer/i);
  await expect(page.locator('.reroll-control').first()).toHaveAttribute('data-tooltip', /remaining pool cannot fill another offer/i);
  await expect(page.getByRole('button', { name: 'How Draft rarity and evolution weighting work' })).toBeVisible();
  expect(await page.locator('body').innerText()).not.toContain('Higher-rated Pokémon appear less often.');

  for (const viewport of [
    { width: 1440, height: 900 },
    { width: 1366, height: 768 },
    { width: 1024, height: 768 },
    { width: 390, height: 844 }
  ]) {
    await page.setViewportSize(viewport);
    await expect(page.locator('.draft')).toBeVisible();
    const geometry = await page.evaluate(() => {
      const box = (selector: string) => {
        const element = document.querySelector(selector);
        if (!(element instanceof HTMLElement)) throw new Error(`Missing ${selector}`);
        return element.getBoundingClientRect().toJSON();
      };
      const buttons = [...document.querySelectorAll<HTMLElement>('.reroll-actions button')]
        .map((button) => ({
          ...button.getBoundingClientRect().toJSON(),
          clippedText: button.scrollWidth > button.clientWidth || button.scrollHeight > button.clientHeight
        }));
      return {
        header: box('.app-header'),
        pageHead: box('.page-head'),
        roll: box('.roll-result'),
        footer: box('.draft-choice-area > footer'),
        buttons,
        viewportWidth: innerWidth,
        viewportHeight: innerHeight,
        documentWidth: document.documentElement.scrollWidth
      };
    });
    expect(Math.round(geometry.header.height)).toBe(56);
    expect(geometry.pageHead.top).toBeGreaterThanOrEqual(geometry.header.bottom);
    expect(geometry.roll.width).toBeLessThan(430);
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
    for (const button of geometry.buttons) {
      expect(button.left).toBeGreaterThanOrEqual(0);
      expect(button.right).toBeLessThanOrEqual(geometry.viewportWidth);
      expect(button.clippedText).toBeFalsy();
    }
    if (viewport.width >= 1366) expect(geometry.footer.bottom).toBeLessThanOrEqual(geometry.viewportHeight);

    const draftInfo = page.getByRole('button', { name: 'How Draft rarity and evolution weighting work' });
    await draftInfo.focus();
    await expect.poll(() => page.locator('.draft-info').evaluate(
      (info) => getComputedStyle(info, '::after').opacity
    )).toBe('1');
    const layers = await page.evaluate(() => {
      const roll = document.querySelector<HTMLElement>('.roll-result');
      const workspace = document.querySelector<HTMLElement>('.draft-workspace');
      const info = document.querySelector<HTMLElement>('.draft-info');
      const cards = document.querySelector<HTMLElement>('.offer-grid');
      if (!roll || !workspace || !info || !cards) throw new Error('Missing Draft layer');
      const tooltip = getComputedStyle(info, '::after');
      return {
        roll: Number.parseInt(getComputedStyle(roll).zIndex, 10),
        workspace: Number.parseInt(getComputedStyle(workspace).zIndex, 10),
        tooltipBottom: info.getBoundingClientRect().bottom + Number.parseFloat(tooltip.height),
        cardsTop: cards.getBoundingClientRect().top
      };
    });
    expect(layers.tooltipBottom).toBeGreaterThan(layers.cardsTop);
    expect(layers.roll).toBeGreaterThan(layers.workspace);

    await reroll.focus();
    await expect.poll(() => page.locator('.reroll-control').first().evaluate(
      (control) => getComputedStyle(control, '::after').opacity
    )).toBe('1');
    const tooltip = await page.locator('.reroll-control').first().evaluate((control) => {
      const rect = control.getBoundingClientRect();
      const style = getComputedStyle(control, '::after');
      const width = Number.parseFloat(style.width);
      return { left: rect.left, right: rect.left + width, opacity: style.opacity, viewportWidth: innerWidth };
    });
    expect(tooltip.opacity).toBe('1');
    expect(tooltip.left).toBeGreaterThanOrEqual(0);
    expect(tooltip.right).toBeLessThanOrEqual(tooltip.viewportWidth);
  }
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test('Battle and Replay use the renderer while private audit stays collapsed', async ({ page, request }) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('pageerror', (error) => pageErrors.push(error.message));
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
  await expect(page.locator('.battle-action-feed')).toBeVisible();
  await expect(page.locator('.dialogue-box')).toHaveCount(0);
  const audit = page.locator('details.audit-drawer');
  await expect(audit).not.toHaveAttribute('open', '');

  await expect.poll(async () => {
    const archive = await request.get(`${apiBase}/api/matches/${match.id}/presentation`);
    return (await archive.json() as { status: string }).status;
  }, { timeout: 120_000 }).toBe('completed');

  await page.goto(`/replay/${match.id}`);
  await expect(page.locator('.battle-renderer')).toBeVisible();
  const slider = page.getByRole('slider', { name: 'Timeline' });
  await expect(page.locator('.battle-action-feed')).toContainText('Battle ready');
  await slider.evaluate((input: HTMLInputElement) => {
    input.value = input.max;
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(page.locator('.battle-action-feed article:not(.waiting)').last()).toBeVisible();
  const finalFeed = (await page.locator('.battle-action-feed').innerText()).replace(/\s+/g, ' ').trim();

  await slider.evaluate((input: HTMLInputElement) => {
    input.value = '0';
    input.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await expect(page.locator('.battle-action-feed')).toContainText('Battle ready');
  expect((await page.locator('.battle-action-feed').innerText()).replace(/\s+/g, ' ').trim()).not.toBe(finalFeed);

  await page.getByLabel('Speed').selectOption('instant');
  await page.getByRole('button', { name: 'Play', exact: true }).click();
  await expect.poll(() => slider.inputValue()).toBe(await slider.getAttribute('max'));
  await expect.poll(async () => (
    await page.locator('.battle-action-feed').innerText()
  ).replace(/\s+/g, ' ').trim()).toBe(finalFeed);

  for (const viewport of [{ width: 1440, height: 900 }, { width: 390, height: 844 }]) {
    await page.setViewportSize(viewport);
    const geometry = await page.evaluate(() => {
      const rect = (selector: string) => {
        const element = document.querySelector<HTMLElement>(selector);
        if (!element) throw new Error(`Missing ${selector}`);
        return element.getBoundingClientRect().toJSON();
      };
      const overlap = (a: DOMRect, b: DOMRect) => Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left))
        * Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
      const feed = rect('.battle-action-feed');
      const stage = rect('.stage');
      const farSprite = document.querySelector<HTMLElement>('.combatant-far .sprite img')?.getBoundingClientRect().toJSON() || null;
      const plates = [...document.querySelectorAll<HTMLElement>('.hp-plate')].map((element) => element.getBoundingClientRect().toJSON());
      const visibleTurns = [...document.querySelectorAll<HTMLElement>('.action-feed-turn')].filter((element) => {
        const turn = element.getBoundingClientRect();
        return turn.top < feed.bottom && turn.bottom > feed.top && getComputedStyle(element).display !== 'none';
      }).length;
      return {
        feed,
        stage,
        visibleTurns,
        farSpriteOverlap: farSprite ? overlap(feed as DOMRect, farSprite as DOMRect) : 0,
        plateOverlap: plates.reduce((sum, plate) => sum + overlap(feed as DOMRect, plate as DOMRect), 0),
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: innerWidth
      };
    });
    expect(geometry.feed.left).toBeGreaterThanOrEqual(geometry.stage.left);
    expect(geometry.feed.right).toBeLessThanOrEqual(geometry.stage.right);
    expect(geometry.farSpriteOverlap).toBe(0);
    expect(geometry.plateOverlap).toBe(0);
    expect(geometry.visibleTurns).toBeGreaterThanOrEqual(viewport.width >= 1000 ? 2 : 1);
    expect(geometry.documentWidth).toBeLessThanOrEqual(geometry.viewportWidth);
  }
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
