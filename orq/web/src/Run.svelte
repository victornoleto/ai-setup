<script lang="ts">
  import { api, type Entry, type RunView, type TaskRow, type TaskView } from "./lib/api";
  import { ago, clock, dur, hms } from "./lib/fmt";
  import Icon from "./lib/Icon.svelte";
  import { md } from "./lib/md";
  import { readSeen, writeSeen } from "./lib/seen";
  import ThemeToggle from "./lib/ThemeToggle.svelte";
  import type { Theme } from "./lib/theme";

  let { id, go, theme = $bindable() }: { id: string; go: (to: string) => void; theme: Theme } = $props();

  type Tab = "plano" | "entrega" | "historico" | "aovivo";
  let run = $state<RunView | null>(null);
  let task = $state<TaskView | null>(null);
  let sel = $state<string | null>(new URLSearchParams(location.search).get("t"));
  let tab = $state<Tab>("plano");
  let err = $state("");
  let now = $state(Date.now() / 1000);
  let wide = $state(matchMedia("(min-width: 1700px)").matches);
  let activity = $state<string[]>([]);
  let since = $state<Entry[] | null>(null); // null: primeira visita ou já marcado como visto
  // svelte-ignore state_referenced_locally (o componente é recriado a cada execução: {#key} no App)
  const seen = readSeen(id);
  let lastN = -1;

  const files = (n: number) => `${n} ${n === 1 ? "arquivo" : "arquivos"}`;
  const OK = ["ok", "ok_takeover", "ok_usuario", "skipped"];
  function rowClass(t: TaskRow): string {
    if (t.status === "esperando você") return "wait";
    if (t.result && OK.includes(t.result)) return "done";
    if (t.result) return "bad";
    return t.phase && t.phase !== "done" ? "run" : "";
  }

  async function loadTask() {
    if (!sel) return;
    try {
      task = await api.task(id, sel);
    } catch (e) {
      err = (e as Error).message;
    }
  }

  async function load() {
    try {
      const r = await api.run(id);
      run = r;
      err = "";
      if (!sel || !r.tasks.some((t) => t.id === sel)) {
        sel = r.ask?.task ?? r.current?.task ?? r.tasks.find((t) => !t.result)?.id ?? r.tasks.at(-1)?.id ?? null;
      }
      if (since === null && seen && lastN === -1 && r.n_events > seen.n) since = await api.events(id, seen.n);
      lastN = r.n_events;
      await loadTask();
    } catch (e) {
      err = (e as Error).message;
    }
  }

  function pick(tid: string) {
    sel = tid;
    task = null;
    activity = [];
    history.replaceState(null, "", `/run/${id}?t=${encodeURIComponent(tid)}`);
    loadTask();
  }

  function markSeen() {
    if (run) writeSeen(id, run.n_events);
    since = null;
  }

  // Avisos do servidor: evento novo ou estado mudou → busca de novo; linhas ao vivo da tarefa selecionada.
  $effect(() => {
    const es = new EventSource(`/api/runs/${id}/stream${sel ? `?task=${encodeURIComponent(sel)}` : ""}`);
    es.onmessage = (m) => {
      const d = JSON.parse(m.data);
      if (d.activity) activity = [...activity, ...d.activity].slice(-400);
      else load();
    };
    return () => es.close();
  });

  $effect(() => {
    const tick = setInterval(() => (now = Date.now() / 1000), 1000);
    const mq = matchMedia("(min-width: 1700px)");
    const onMq = () => (wide = mq.matches);
    mq.addEventListener("change", onMq);
    // Ao sair da aba, o que estava na tela passa a contar como visto.
    const onHide = () => document.visibilityState === "hidden" && run && writeSeen(id, run.n_events);
    document.addEventListener("visibilitychange", onHide);
    return () => {
      clearInterval(tick);
      mq.removeEventListener("change", onMq);
      document.removeEventListener("visibilitychange", onHide);
      if (run) writeSeen(id, run.n_events);
    };
  });

  $effect(() => {
    if (wide && tab === "entrega") tab = "plano";
  });

  const done = $derived(run ? run.tasks.filter((t) => t.result && OK.includes(t.result)).length : 0);
  const elapsed = $derived.by(() => {
    if (!run?.started) return null;
    const end = run.ended ? Date.parse(run.ended) / 1000 : now;
    return end - Date.parse(run.started) / 1000;
  });
  const stageIndex = $derived(run?.current ? run.stages.indexOf(run.current.stage) : -1);
  const selRow = $derived(run?.tasks.find((t) => t.id === sel) ?? null);

  const digest = $derived.by(() => {
    if (!since) return null;
    const ends = since.filter((e) => e.type === "task_end");
    const ok = ends.filter((e) => e.result && OK.includes(e.result));
    const bad = ends.filter((e) => e.result && !OK.includes(e.result));
    const split = since.filter((e) => e.type === "decision" && e.points != null && e.points < 3);
    const attention = since.filter((e) => e.attention);
    const ids = (xs: Entry[]) => [...new Set(xs.map((e) => e.task.split("-")[0]))].join(", ");
    const lines: { strong: string; rest: string }[] = [];
    if (ok.length) lines.push({ strong: `${ok.length} ${ok.length === 1 ? "tarefa concluída" : "tarefas concluídas"}`, rest: ` (${ids(ok)})` });
    if (bad.length) lines.push({ strong: `${bad.length} com problema`, rest: ` (${ids(bad)})` });
    if (split.length) lines.push({ strong: `${split.length} ${split.length === 1 ? "decisão" : "decisões"} sem unanimidade`, rest: ` (${ids(split)})` });
    if (attention.length) lines.push({ strong: `${attention.length} ${attention.length === 1 ? "aviso" : "avisos"} para conferir`, rest: "" });
    return lines;
  });
  const timeline = $derived(run ? [...run.timeline].reverse().slice(0, 120) : []);
</script>

{#snippet entrega(t: TaskView)}
  <div class="md">
    <h3>Como validar</h3>
    {#if t.validation.length}
      <ol>{#each t.validation as v}<li>{@html md(v)}</li>{/each}</ol>
    {:else}
      <p class="empty">O revisor ainda não escreveu os passos de conferência desta tarefa.</p>
    {/if}
    {#if t.pending.length}
      <h3>Pendente</h3>
      <ul>{#each t.pending as p}<li>{@html md(p)}</li>{/each}</ul>
    {/if}
    {#if t.highlights.length}
      <h3>Destaques da revisão</h3>
      <ul>{#each t.highlights as h}<li>{@html md(h)}</li>{/each}</ul>
    {/if}
    <h3>Arquivos</h3>
    {#if t.diff?.files.length}
      <div class="files num">
        {#each t.diff.files as f}<span>+{f.add}</span><span>−{f.rem}</span><span>{f.path}</span>{/each}
      </div>
    {:else if t.diff}
      <p class="num">+{t.diff.add} −{t.diff.rem} em {files(t.diff.nfiles)}</p>
    {:else}
      <p class="empty">Nenhuma alteração registrada ainda.</p>
    {/if}
  </div>
{/snippet}

<header class="bar">
  <a class="brand" href="/" onclick={(e) => { e.preventDefault(); go("/"); }} title="Todas as execuções">orq</a>
  {#if run}
    <span>fila <b>{run.queue}</b></span>
    <span class="num"><b>{done} / {run.tasks.length}</b> tarefas</span>
    {#if elapsed != null}<span class="num">{run.ended ? "durou" : "rodando há"} <b>{hms(elapsed)}</b></span>{/if}
    {#if run.eta}<span class="num">termina <b>~{clock(run.eta)}</b></span>{/if}
    <span class="num">US$ <b>{run.cost.toFixed(2)}</b> {run.cost_partial ? "parcial" : "estimado"}</span>
    <span class="badge" class:wait={run.state === "esperando você"} class:run={run.state === "rodando"}>{run.paused && run.state === "rodando" ? "pausada" : run.state}</span>
  {/if}
  <ThemeToggle bind:theme />
</header>

<div class="rail" aria-label="Etapas da tarefa em curso">
  {#if run?.current}
    {#each run.stages as s, i}
      {#if i}<span class="ln"></span>{/if}
      <span class="st" class:ok={i < stageIndex} class:on={i === stageIndex} aria-current={i === stageIndex ? "step" : undefined}>
        <i class:live={i === stageIndex && run.state === "rodando"}>{#if i < stageIndex}<Icon name="check" />{:else}{i + 1}{/if}</i>{s}
      </span>
    {/each}
    <span class="who num">
      tarefa <b>{run.current.task.split("-")[0]}</b> · <b>{run.current.label}</b>
      {#if run.current.role} · {run.current.role} · <b>{run.current.harness} · {run.current.model}</b>{/if}
      {#if run.current.since} · <b>{hms(now - run.current.since)}</b>{/if}
    </span>
  {:else if run}
    <span>{run.result ? `Execução terminou: ${run.result}.` : run.state === "parada" ? "Motor parado. Continue com `orq resume`." : "Nenhuma tarefa em curso."}</span>
  {/if}
</div>

{#if err && !run}
  <p class="err">Não consegui ler a execução: {err}</p>
{:else if run}
  <main class="cols" class:wide>
    <section class="card">
      <header><h2>Fila</h2><span class="num">{done} de {run.tasks.length}</span></header>
      <div class="scroll" id="queue">
        <ul>
          {#each run.tasks as t (t.id)}
            <li>
              <button class={`q ${rowClass(t)}`} aria-current={t.id === sel ? "true" : undefined} onclick={() => pick(t.id)}>
                <span><b>{t.id.split("-")[0]}</b> {t.title}<small>{t.status}</small></span>
                <span class="t num">{t.extra.split(" · ")[0].slice(0, 5)}</span>
              </button>
            </li>
          {/each}
        </ul>
      </div>
    </section>

    <div class="mid">
      <section class="card">
        <div class="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "plano"} onclick={() => (tab = "plano")}>Plano</button>
          {#if !wide}<button role="tab" aria-selected={tab === "entrega"} onclick={() => (tab = "entrega")}>Entrega e como validar</button>{/if}
          <button role="tab" aria-selected={tab === "historico"} onclick={() => (tab = "historico")}>Histórico</button>
          <button role="tab" aria-selected={tab === "aovivo"} onclick={() => (tab = "aovivo")}>Ao vivo</button>
        </div>
        <div class="scroll task">
          {#if !task}
            <p class="empty">{sel ? "Carregando a tarefa." : "Escolha uma tarefa na fila."}</p>
          {:else if tab === "plano"}
            <h1>{task.title}</h1>
            <div class="meta">
              <span><b>{task.status}</b></span>
              {#if selRow?.extra}<span class="num">{selRow.extra}</span>{/if}
              {#if task.diff}<span class="num"><b>+{task.diff.add} −{task.diff.rem}</b> em {files(task.diff.nfiles)}</span>{/if}
            </div>
            <div class="md" style="margin-top:14px">
              {#if task.plan_md}
                {@html md(task.plan_md)}
              {:else}
                <p class="empty">{task.report_md ? "Esta tarefa não tem plano gravado." : "O plano desta tarefa ainda não foi escrito."} O texto da tarefa:</p>
                {@html md(task.text)}
              {/if}
              {#if task.decisions_md}
                <h2>Decisões</h2>
                {@html md(task.decisions_md)}
              {/if}
            </div>
          {:else if tab === "entrega"}
            {@render entrega(task)}
          {:else if tab === "historico"}
            {#if task.report_md}
              <div class="md">{@html md(task.report_md)}</div>
            {:else}
              <p class="empty">A tarefa ainda não começou.</p>
            {/if}
          {:else}
            {#if task.steps.length}
              <div class="steps num">
                {#each task.steps as s}
                  <span>{s.label}{s.ok === true ? " · aprovada" : s.ok === false ? " · reprovada" : ""}</span>
                  <span>{s.running || s.open ? "em curso" : dur(s.dur)}</span>
                {/each}
              </div>
            {/if}
            {#if activity.length}
              <div class="livelog">{activity.join("\n")}</div>
            {:else}
              <p class="empty">Nenhuma linha nova desde que você abriu esta tarefa. O que já aconteceu está em Histórico.</p>
            {/if}
          {/if}
        </div>
      </section>

      {#if wide}
        <section class="card">
          <header>
            <h2>Entrega e como validar</h2>
            {#if task?.diff}<span class="num">+{task.diff.add} −{task.diff.rem} · {files(task.diff.nfiles)}</span>{/if}
          </header>
          <div class="scroll">
            {#if task}{@render entrega(task)}{:else}<p class="empty">Escolha uma tarefa na fila.</p>{/if}
          </div>
        </section>
      {/if}
    </div>

    <div class="stack" style={run.ask ? "" : "grid-template-rows:minmax(0,1fr)"}>
      {#if run.ask}
        <section class="card ask">
          <div class="in">
            <strong><Icon name="alert" /> Tarefa {run.ask.task.split("-")[0]} espera você: {run.ask.question}</strong>
            {#if run.ask.diagnosis}<p>{run.ask.diagnosis}</p>{/if}
            <ol>
              {#each run.ask.options as o}
                <li>{o.label}{o.id === run.ask.recommended ? " (recomendada)" : ""}</li>
              {/each}
            </ol>
            {#if run.ask.deadline}<p>Segue sozinha com a recomendada às {clock(run.ask.deadline)}.</p>{/if}
            <p class="hint">Responder pela tela chega na próxima entrega. Por enquanto, no terminal:</p>
            <code>orq send {run.run} "/answer {run.ask.id} {Math.max(1, run.ask.options.findIndex((o) => o.id === run?.ask?.recommended) + 1)}"</code>
          </div>
        </section>
      {/if}
      <section class="card">
        <header><h2>Atividade</h2><span>{run.state === "rodando" ? "ao vivo" : run.state}</span></header>
        <div class="scroll">
          {#if digest && seen}
            <h3 class="sub">Desde a sua última visita, {ago((Date.now() - seen.at) / 1000)}</h3>
            <ul class="since">
              {#each digest as l}<li><b>{l.strong}</b>{l.rest}</li>{/each}
              {#if !digest.length}<li>Nada que peça atenção.</li>{/if}
              <li><button class="linkbtn" onclick={markSeen}>Marcar como visto</button></li>
            </ul>
          {/if}
          <h3 class="sub">Linha do tempo</h3>
          <ul class="tl">
            {#each timeline as e (e.i)}
              {@const m = e.line.match(/^\[(.+?)\]\s*(.*)$/s)}
              <li>
                <time class="num">{e.ts.slice(11, 16)}</time>
                <span>{#if m}<span class="tag">{m[1].toLowerCase()}</span> · {m[2]}{:else}{e.line}{/if}</span>
              </li>
            {/each}
          </ul>
        </div>
      </section>
    </div>
  </main>
{/if}
