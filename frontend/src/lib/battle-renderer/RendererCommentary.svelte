<script lang="ts">
  import type { BattlePresentationState, RendererConfig, SpectatorLogEntry } from '../presentation/types';
  import type { Side } from '../types';

  export let presentation: BattlePresentationState;
  export let config: RendererConfig;
  export let sideOrder: readonly Side[] = ['p2', 'p1'];
  export let variant: 'dialogue' | 'feed' = 'dialogue';

  function currentIntent(side: Side) {
    if (config.commentaryMode === 'hidden') return null;
    const player = presentation.players[side];
    return player.commentaryPhase === 'resolved' || player.commentaryPhase === 'waiting' ? null : player;
  }
  function groupedFeed(log: SpectatorLogEntry[]) {
    const groups: Array<{ turn: number; lines: SpectatorLogEntry[] }> = [];
    for (const entry of log.slice(-9)) {
      if (entry.kind === 'turn_started') continue;
      const last = groups.at(-1);
      if (last?.turn === entry.turn) last.lines.push(entry);
      else groups.push({ turn: entry.turn, lines: [entry] });
    }
    return groups.slice(-3).map((group) => ({ ...group, lines: group.lines.slice(-3) }));
  }
  // Keep the dependency visible to Svelte's legacy reactive compiler. Calling a
  // zero-argument helper left the feed frozen at its initial empty array.
  $: feed = groupedFeed(presentation.log);
</script>

{#if variant === 'dialogue'}
  {#if currentIntent('p1') || currentIntent('p2')}
    <div class="dialogue-box" role="region" aria-label="Battle Dialogue & Thinking" aria-live="polite">
      {#each sideOrder as side (side)}
        {@const player = currentIntent(side)}
        {#if player}
          <div class="dialogue-item" data-side={side}>
            <header class="dialogue-header"><b class="dialogue-name">{presentation.players[side].displayName}</b><small class="dialogue-phase">{player.commentaryPhase === 'thinking' ? 'THINKING' : player.currentCommentary?.banter ? 'BANTER' : 'COMMENTARY'}</small></header>
            {#if player.commentaryPhase === 'thinking'}
              {#if player.streamPreview}<p class="thinking live-response">{player.streamPreview}<span aria-hidden="true">▌</span></p>{:else}<p class="thinking">Thinking…</p>{/if}
              {#if player.contextMetrics}<small class="context-meter">Context · {player.contextMetrics.estimatedTokens.toLocaleString()} tokens</small>{/if}
            {:else}
              <div class="dialogue-copy">
                {#if player.currentCommentary?.banter}<span class="banter-quote">“{player.currentCommentary.banter}”</span>{/if}
                <span class="commentary-copy">{player.currentCommentary?.commentary || `${player.currentCommentary?.actionName || player.currentCommentary?.action || 'Action'} selected.`}</span>
              </div>
            {/if}
          </div>
        {/if}
      {/each}
    </div>
  {/if}
{:else if config.showBattleLog}
  <aside class="battle-feed" aria-label="Spectator battle feed" aria-live="polite">
    {#each feed as group (group.turn)}
      <div class="feed-turn"><span class="feed-label">Turn {group.turn}</span>{#each group.lines as entry (entry.sequence)}<p data-emphasis={entry.emphasis}>{entry.text}</p>{/each}</div>
    {/each}
    {#if !feed.length}<div class="feed-turn"><span class="feed-label">Ready</span><p>Waiting for the first turn.</p></div>{/if}
  </aside>
{/if}

<style>
  /* The clearest band across the arena's vertical middle-right: below the far combatant,
     above the near combatant and its HP plate. A box centered at the very bottom used to
     cover a third of the near (foreground) combatant. Two simultaneous speakers can still
     grow past this band on a short/cramped viewport, so z-index sits below the combatants
     (not just the HP plates) and the background stays translucent: on the rare overlap, the
     sprite reads through rather than getting hidden. */
  .dialogue-box{position:absolute;z-index:9;top:46%;right:3%;left:auto;bottom:auto;transform:none;width:clamp(240px,30cqw,360px);max-height:20%;display:grid;gap:.35rem;padding:.55rem .85rem;border-radius:8px;background:rgba(8,16,14,.85);border:1.5px solid var(--r-line);box-shadow:0 10px 30px rgba(0,0,0,.7);backdrop-filter:blur(10px)}
  .dialogue-item{display:grid;gap:.15rem;min-height:3.4em;padding-left:.5rem}.dialogue-item[data-side='p1']{--side-color:var(--r-p1);border-left:3px solid var(--side-color)}.dialogue-item[data-side='p2']{--side-color:var(--r-p2);border-left:3px solid var(--side-color)}
  .dialogue-header{display:flex;align-items:center;justify-content:space-between;gap:.4rem}.dialogue-name{font:800 calc(var(--hud-scale,1) * clamp(.66rem,.82cqw,.84rem)) var(--display);color:#fff;letter-spacing:.02em;text-transform:uppercase}.dialogue-phase{color:var(--side-color);font:900 calc(var(--hud-scale,1) * clamp(.52rem,.66cqw,.68rem)) var(--mono);letter-spacing:.12em}
  .dialogue-copy{display:grid;grid-template-rows:auto auto;gap:.15rem;min-height:3.1em;overflow:hidden;color:#dfeae3;font-size:calc(var(--hud-scale,1) * clamp(.74rem,.92cqw,.92rem));line-height:1.4}.commentary-copy{display:-webkit-box;overflow:hidden;line-clamp:2;-webkit-box-orient:vertical;-webkit-line-clamp:2}.banter-quote{display:block;overflow:hidden;color:#ffd679;font-style:italic;font-weight:700;white-space:nowrap;text-overflow:ellipsis}.thinking{margin:.2rem 0;color:var(--r-dim);font-style:italic}.live-response{color:#f3fff6;font-style:normal}.live-response span{color:var(--side-color);animation:cursor-blink 1s steps(2,end) infinite}.context-meter{color:var(--r-dim);font:600 calc(var(--hud-scale,1) * clamp(.44rem,.55cqw,.55rem)) var(--mono)}
  .battle-feed{display:grid;grid-auto-flow:column;grid-auto-columns:1fr;gap:1px;min-height:clamp(54px,8cqh,82px);overflow:hidden;border-top:1px solid var(--r-line);background:rgba(5,10,8,.96)}.feed-turn{display:grid;align-content:center;gap:.18rem;padding:.45rem .75rem;border-left:1px solid var(--r-line)}.feed-label{color:var(--r-accent);font:800 clamp(.48rem,.58cqw,.6rem) var(--mono);letter-spacing:.1em;text-transform:uppercase}.feed-turn p{overflow:hidden;margin:0;color:var(--r-dim);font:600 clamp(.54rem,.66cqw,.68rem)/1.25 var(--display);text-overflow:ellipsis;white-space:nowrap}.feed-turn p[data-emphasis='high']{color:#fff}
  :global(.battle-renderer[data-layout='standard-vertical']) .battle-feed{grid-auto-flow:row;height:clamp(72px,11%,132px)}
  :global(.battle-renderer[data-layout='standard-vertical']) .feed-turn:not(:last-child){display:none}
  @media(max-width:560px){.battle-feed .feed-turn:not(:last-child){display:none}}
  @keyframes cursor-blink{50%{opacity:0}}
</style>
