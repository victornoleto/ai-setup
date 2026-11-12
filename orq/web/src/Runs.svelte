<script lang="ts">
  import { api, type RunRow } from "./lib/api";
  import ThemeToggle from "./lib/ThemeToggle.svelte";
  import type { Theme } from "./lib/theme";

  let { go, theme = $bindable() }: { go: (to: string) => void; theme: Theme } = $props();
  let runs = $state<RunRow[] | null>(null);
  let err = $state("");

  async function load() {
    try {
      runs = await api.runs();
      err = "";
    } catch (e) {
      err = (e as Error).message;
    }
  }
  $effect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  });
</script>

<header class="bar">
  <span class="brand">orq</span><span>execuções nesta máquina</span>
  <ThemeToggle bind:theme />
</header>
<div></div>
<main class="runs">
  {#if err}<p class="err">Não consegui ler as execuções: {err}</p>{/if}
  <section class="card">
    <header><h2>Execuções</h2><span>{runs ? `${runs.length} registradas` : "carregando"}</span></header>
    {#if runs && runs.length === 0}
      <p class="empty" style="padding:0 16px 16px">Nenhuma execução registrada. Comece uma com <code>orq run &lt;pasta&gt;</code>.</p>
    {/if}
    {#each runs ?? [] as r (r.id)}
      <a class="runrow" href={`/run/${r.id}`} onclick={(e) => { e.preventDefault(); go(`/run/${r.id}`); }}>
        <span><b>{r.queue}</b><small>{r.run}</small></span>
        <span class="num">{r.done} de {r.total} tarefas</span>
        <span class="badge" class:wait={r.state === "esperando você"} class:run={r.state === "rodando"}>{r.state}</span>
      </a>
    {/each}
  </section>
</main>
