<script lang="ts">
  import Run from "./Run.svelte";
  import Runs from "./Runs.svelte";
  import { applyTheme, initialTheme, type Theme } from "./lib/theme";

  let path = $state(location.pathname);
  let theme = $state<Theme>(initialTheme());
  $effect(() => applyTheme(theme));

  function go(to: string) {
    history.pushState(null, "", to);
    path = to;
  }
  const runId = $derived(path.match(/^\/run\/([0-9a-f]{12})/)?.[1] ?? null);
</script>

<svelte:window onpopstate={() => (path = location.pathname)} />

{#if runId}
  {#key runId}
    <Run id={runId} {go} bind:theme />
  {/key}
{:else}
  <Runs {go} bind:theme />
{/if}
