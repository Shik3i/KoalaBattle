<script lang="ts">
  import type { ActionFeedEntry, BattlePresentationState, RendererConfig } from '../presentation/types';

  export let presentation: BattlePresentationState;
  export let config: RendererConfig;
  interface ActionFeedTurn {
    turn: number;
    entries: ActionFeedEntry[];
  }

  function groupActionFeed(entries: ActionFeedEntry[], battleTurn = 0): ActionFeedTurn[] {
    const groups: ActionFeedTurn[] = [];
    for (const entry of entries) {
      const current = groups.at(-1);
      if (current?.turn === entry.turn) current.entries.push(entry);
      else groups.push({ turn: entry.turn, entries: [entry] });
    }
    const visibleTurn = Math.max(battleTurn, groups.at(-1)?.turn || 0);
    if (groups.at(-1)?.turn !== visibleTurn) groups.push({ turn: visibleTurn, entries: [] });
    if (!groups.length) groups.push({ turn: visibleTurn, entries: [] });
    return groups.slice(-8).reverse();
  }

  $: feedTurns = groupActionFeed(presentation.actionFeed, presentation.battle?.turn);
</script>

{#if config.showBattleLog}
  <aside class="battle-action-feed" data-speed={config.playbackSpeed} aria-label="Battle action feed" aria-live="polite" aria-atomic="false" aria-relevant="additions text">
    <span class="action-feed-label">BATTLE ACTIONS</span>
    <div class="action-feed-turns">
      {#each feedTurns as group, groupIndex (group.turn)}
        <section class:current={groupIndex === 0} class="action-feed-turn" aria-label={`Turn ${group.turn}${groupIndex === 0 ? ', current' : ''}`}>
          <span class="action-feed-turn-label">TURN {group.turn}{groupIndex === 0 ? ' · CURRENT' : ''}</span>
          {#each group.entries as entry, entryIndex (`${entry.sequence}:${entry.updatedSequence}`)}
            <article class:latest={groupIndex === 0 && entryIndex === group.entries.length - 1} data-emphasis={entry.emphasis}>
              <strong>{entry.headline}</strong>
              {#if entry.detailParts.length}<p>{entry.detailParts.join(' · ')}</p>{/if}
            </article>
          {/each}
          {#if groupIndex === 0 && !group.entries.length}
            <article class="waiting"><strong>{presentation.actionFeed.length ? 'Next action ready' : 'Battle ready'}</strong><p>Waiting for the next action.</p></article>
          {/if}
        </section>
      {/each}
    </div>
  </aside>
{/if}

<style>
  .battle-action-feed{position:absolute;z-index:18;top:16%;right:2.5%;display:grid;align-content:start;gap:.3rem;width:clamp(240px,24cqw,350px);max-height:44%;overflow:hidden;padding:.5rem .62rem .58rem;border-left:2px solid color-mix(in srgb,var(--r-accent) 72%,transparent);border-radius:3px 8px 8px 3px;background:linear-gradient(90deg,rgba(6,13,11,.94),rgba(6,13,11,.74));box-shadow:0 8px 24px rgba(0,0,0,.34);pointer-events:none;backdrop-filter:blur(5px)}
  .action-feed-label{color:var(--r-accent);font:850 calc(var(--hud-scale,1) * clamp(.44rem,.55cqw,.56rem)) var(--mono);letter-spacing:.12em}
  .action-feed-turns,.action-feed-turn{display:grid;min-height:0}.action-feed-turns{gap:.34rem}.action-feed-turn{gap:.16rem}.action-feed-turn:not(.current){opacity:.58}
  .action-feed-turn-label{color:#9ab0a2;font:750 calc(var(--hud-scale,1) * clamp(.39rem,.48cqw,.49rem)) var(--mono);letter-spacing:.1em}
  .action-feed-turn.current .action-feed-turn-label{color:#d2e3d7}
  .battle-action-feed article{display:grid;gap:.08rem;min-width:0;padding:.24rem .34rem;border-radius:4px;background:rgba(255,255,255,.025);animation:action-feed-in .18s ease-out both}
  .battle-action-feed article:not(.latest){opacity:.78}
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
  :global(.battle-renderer[data-layout='standard-vertical']) .battle-action-feed{top:39%;right:4%;left:4%;width:auto;max-height:24%}
  @container(max-width:760px){.battle-action-feed{top:39%;right:3%;left:3%;width:auto;max-height:24%;padding:.42rem .5rem}.battle-action-feed strong{font-size:calc(var(--hud-scale,1) * .72rem)}.battle-action-feed p{font-size:calc(var(--hud-scale,1) * .61rem)}.action-feed-turn:not(.current) article:not(:first-of-type){display:none}}
  @keyframes action-feed-in{from{opacity:0;transform:translateX(8px)}to{opacity:1;transform:none}}
  :global(.battle-renderer.reduced-motion) .battle-action-feed article{animation:none}
  @media(prefers-reduced-motion:reduce){.battle-action-feed article{animation:none}}
</style>
