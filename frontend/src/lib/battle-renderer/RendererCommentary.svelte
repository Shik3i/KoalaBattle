<script lang="ts">
  import type { BattlePresentationState, RendererConfig } from '../presentation/types';
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
  $: feed = presentation.actionFeed.slice(-2);
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
  <aside class="battle-action-feed" data-speed={config.playbackSpeed} aria-label="Battle action feed" aria-live="polite" aria-atomic="true">
    <span class="action-feed-label">TURN {presentation.battle?.turn || feed.at(-1)?.turn || 0} · ACTION</span>
    {#each feed as entry (`${entry.sequence}:${entry.updatedSequence}`)}
      <article data-emphasis={entry.emphasis}>
        <strong>{entry.headline}</strong>
        {#if entry.detailParts.length}<p>{entry.detailParts.join(' · ')}</p>{/if}
      </article>
    {/each}
    {#if !feed.length}<article class="waiting"><strong>Battle ready</strong><p>Waiting for the first action.</p></article>{/if}
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
  .battle-action-feed{position:absolute;z-index:18;top:20%;right:2.5%;display:grid;align-content:start;gap:.26rem;width:clamp(230px,23cqw,330px);max-height:29%;overflow:hidden;padding:.5rem .62rem .58rem;border-left:2px solid color-mix(in srgb,var(--r-accent) 72%,transparent);border-radius:3px 8px 8px 3px;background:linear-gradient(90deg,rgba(6,13,11,.94),rgba(6,13,11,.74));box-shadow:0 8px 24px rgba(0,0,0,.34);pointer-events:none;backdrop-filter:blur(5px)}
  .action-feed-label{color:var(--r-accent);font:850 calc(var(--hud-scale,1) * clamp(.44rem,.55cqw,.56rem)) var(--mono);letter-spacing:.12em}
  .battle-action-feed article{display:grid;gap:.08rem;min-width:0;padding:.28rem .38rem;border-radius:4px;background:rgba(255,255,255,.025);animation:action-feed-in .18s ease-out both}
  .battle-action-feed article:not(:last-of-type){opacity:.62}
  .battle-action-feed strong,.battle-action-feed p{overflow:hidden;margin:0;text-overflow:ellipsis;white-space:nowrap}
  .battle-action-feed strong{color:#f7fff9;font:800 calc(var(--hud-scale,1) * clamp(.64rem,.78cqw,.8rem))/1.2 var(--display)}
  .battle-action-feed p{color:#c1d1c7;font:650 calc(var(--hud-scale,1) * clamp(.54rem,.66cqw,.68rem))/1.28 var(--display)}
  .battle-action-feed article[data-emphasis='critical']{background:linear-gradient(90deg,rgba(255,196,72,.18),rgba(255,196,72,.03));box-shadow:inset 2px 0 #ffd262}
  .battle-action-feed article[data-emphasis='critical'] p{color:#ffe3a0}
  .battle-action-feed article[data-emphasis='negative']{box-shadow:inset 2px 0 rgba(255,111,105,.72)}
  .battle-action-feed article[data-emphasis='positive']{box-shadow:inset 2px 0 rgba(116,245,158,.72)}
  .battle-action-feed article[data-emphasis='field']{box-shadow:inset 2px 0 rgba(116,198,255,.65)}
  .battle-action-feed[data-speed='4'] article{animation-duration:.12s}
  .battle-action-feed[data-speed='instant'] article{animation:none}
  :global(.battle-renderer[data-layout='standard-vertical']) .battle-action-feed{top:44%;right:4%;left:4%;width:auto;max-height:14%}
  :global(.battle-renderer[data-layout='standard-vertical']) .dialogue-box{display:none}
  @container(max-width:760px){.battle-action-feed{top:44%;right:3%;left:3%;width:auto;max-height:18%;padding:.42rem .5rem}.dialogue-box{display:none}.battle-action-feed article:not(:last-of-type){display:none}.battle-action-feed strong{font-size:calc(var(--hud-scale,1) * .72rem)}.battle-action-feed p{font-size:calc(var(--hud-scale,1) * .61rem)}}
  @keyframes action-feed-in{from{opacity:0;transform:translateX(8px)}to{opacity:1;transform:none}}
  :global(.battle-renderer.reduced-motion) .battle-action-feed article{animation:none}
  @media(prefers-reduced-motion:reduce){.battle-action-feed article{animation:none}}
  @keyframes cursor-blink{50%{opacity:0}}
</style>
