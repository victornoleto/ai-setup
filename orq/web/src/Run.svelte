<script lang="ts">
  import { api, type Decision, type Entry, type Op, type RunView, type TaskRow, type TaskView } from "./lib/api";
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

  // --- ações: tudo vira comando do orq; o motor responde com um ack, que a tela mostra --------------------------
  let say = $state("");
  let target = $state<"task" | "queue">("task");
  let feedback = $state<{ ok: boolean; text: string } | null>(null);
  let confirming = $state<string | null>(null); // a ação que espera o segundo clique
  let editing = $state(false);
  let draft = $state("");
  let closed = $state<string[]>(readClosed());
  const watch = new Set<string>();

  function readClosed(): string[] {
    try {
      return JSON.parse(localStorage.getItem(`orq:ops:${id}`) ?? "[]");
    } catch {
      return [];
    }
  }
  function closeOp(op: string) {
    closed = [...closed, op].slice(-50);
    try {
      localStorage.setItem(`orq:ops:${id}`, JSON.stringify(closed));
    } catch {
      /* navegação privada: a proposta volta ao recarregar */
    }
  }

  async function act(text: string, op?: string): Promise<boolean> {
    confirming = null;
    try {
      const r = await api.send(id, text, op);
      if (r.alive) {
        watch.add(r.id);
        feedback = { ok: true, text: "Enviado. Aguardando o motor." };
      } else {
        feedback = { ok: true, text: "Motor parado: o comando fica guardado e vale no próximo `orq resume`." };
      }
      return true;
    } catch (e) {
      feedback = { ok: false, text: (e as Error).message };
      return false;
    }
  }

  async function sendSay() {
    const text = say.trim();
    if (!text) return;
    const about = target === "task" && selRow ? `Sobre a tarefa \`${selRow.id}\` (${selRow.status}): ` : "";
    if (await act(`/ask ${about}${text}`)) say = "";
  }

  async function applyOp(op: Op) {
    for (const c of op.commands) if (!(await act(c, op.id))) return;
  }

  async function saveText() {
    if (!sel) return;
    try {
      await api.setText(id, sel, draft);
      editing = false;
      feedback = { ok: true, text: "Texto da tarefa salvo." };
      await loadTask();
    } catch (e) {
      feedback = { ok: false, text: (e as Error).message };
    }
  }

  const files = (n: number) => `${n} ${n === 1 ? "arquivo" : "arquivos"}`;
  // O título costuma repetir o número da tarefa ("01 · Servidor"): na fila o número já vem na frente.
  const bare = (title: string) => title.replace(/^\d+\s*[·.:–—-]\s*/, "");
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
      for (const a of r.acks) {
        if (watch.delete(a.id)) feedback = { ok: a.ok, text: a.result };
      }
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
    editing = false;
    confirming = null;
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
  const proposals = $derived(run ? run.ops.filter((o) => !o.applied && !closed.includes(o.id)) : []);

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
  // O resumo final é um texto longo em markdown: fica no Histórico e no journal, não na linha do tempo.
  const timeline = $derived(run ? run.timeline.filter((e) => e.type !== "run_summary").reverse().slice(0, 120) : []);
  $effect(() => {
    if (sel && run) queueMicrotask(() => document.querySelector(".q[aria-current]")?.scrollIntoView({ block: "nearest" }));
  });
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

{#snippet decision(d: Decision, finished: boolean)}
  <div class="dec">
    <p><b>{d.question}</b></p>
    <div class="opts">
      {#each d.options as o}
        {#if o.id === d.choice}
          <span class="btn outline on" aria-current="true"><Icon name="check" /> {o.label} ({d.by_user ? "escolha sua" : "escolhida"})</span>
        {:else if confirming === `${d.qid}:${o.id}`}
          <span class="confirm">
            Trocar para "{o.label}"? {finished ? "A tarefa já terminou: cria uma tarefa de ajuste." : "Entra no próximo prompt da tarefa."}
            <span class="row">
              <button class="btn primary sm" onclick={() => act(`/decision ${d.qid} ${o.id}`)}>Confirmar</button>
              <button class="btn outline sm" onclick={() => (confirming = null)}>Cancelar</button>
            </span>
          </span>
        {:else}
          <button class="btn outline" onclick={() => (confirming = `${d.qid}:${o.id}`)}>{o.label}</button>
        {/if}
      {/each}
    </div>
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
  {#if run?.alive}
    <span class="sp ctl">
      {#if confirming === "stop"}
        <span>Parar no próximo ponto seguro?</span>
        <button class="btn primary sm" onclick={() => act("/stop")}>Parar</button>
        <button class="btn outline sm" onclick={() => (confirming = null)}>Cancelar</button>
      {:else}
        <button class="btn outline sm" onclick={() => act(run?.paused ? "/resume" : "/pause")}>{run.paused ? "Retomar" : "Pausar"}</button>
        <button class="btn outline sm" onclick={() => (confirming = "stop")}>Parar</button>
      {/if}
    </span>
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
                <span><b>{t.id.split("-")[0]}</b> {bare(t.title)}<small>{t.status}</small></span>
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
              {#if task.skipped}
                <button class="btn outline sm" onclick={() => act(`/unskip ${task?.id}`)}>Devolver à fila</button>
              {:else if task.editable && !editing}
                <button class="btn outline sm" onclick={() => { draft = task?.text ?? ""; editing = true; }}>Editar texto</button>
                <button class="btn outline sm" onclick={() => act(`/skip ${task?.id}`)}>Pular</button>
              {/if}
            </div>
            <div class="md" style="margin-top:14px">
              {#if editing}
                <textarea class="edit" bind:value={draft} aria-label="Texto da tarefa"></textarea>
                <div class="row">
                  <button class="btn primary sm" onclick={saveText}>Salvar</button>
                  <button class="btn outline sm" onclick={() => (editing = false)}>Cancelar</button>
                </div>
              {:else if task.plan_md}
                {@html md(task.plan_md)}
              {:else}
                <p class="empty">{task.report_md ? "Esta tarefa não tem plano gravado." : "O plano desta tarefa ainda não foi escrito."} O texto da tarefa:</p>
                {@html md(task.text)}
              {/if}
              {#if task.decisions_md}
                <h2>Decisões</h2>
                {@html md(task.decisions_md)}
              {/if}
              {#if task.decisions.length}
                <h2>Trocar uma decisão</h2>
                {#each task.decisions as d (d.qid)}{@render decision(d, !!selRow?.result)}{/each}
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

      <form class="say" onsubmit={(e) => { e.preventDefault(); sendSay(); }}>
        {#if feedback}
          <p class="fb" role="status">
            <Icon name={feedback.ok ? "check" : "alert"} /> <span><b>{feedback.ok ? "ok" : "recusado"}:</b> {feedback.text}</span>
            <button type="button" class="linkbtn" onclick={() => (feedback = null)}>fechar</button>
          </p>
        {/if}
        <button type="button" class="to" title="Trocar o alvo da instrução" disabled={!selRow}
          onclick={() => (target = target === "task" ? "queue" : "task")}>
          {target === "task" && selRow ? `Tarefa ${selRow.id.split("-")[0]}` : "Fila inteira"} <Icon name="swap" />
        </button>
        <textarea rows="1" bind:value={say} aria-label="Instrução para o operador"
          placeholder={target === "task" && selRow ? "Diga o que mudar nesta tarefa" : "Diga o que mudar na fila"}
          onkeydown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); sendSay(); } }}></textarea>
        <button class="go" aria-label="Enviar ao operador" disabled={!say.trim()}><Icon name="up" /></button>
      </form>
    </div>

    <div class="stack">
      {#if run.ask}
        <section class="card ask">
          <div class="in">
            <strong><Icon name="alert" /> Tarefa {run.ask.task.split("-")[0]} espera você: {run.ask.question}</strong>
            {#if run.ask.diagnosis}<p>{run.ask.diagnosis}</p>{/if}
            <div class="opts">
              {#each run.ask.options as o, i}
                <button class="btn" class:primary={o.id === run.ask.recommended} class:outline={o.id !== run.ask.recommended}
                  onclick={() => act(`/answer ${run?.ask?.id} ${i + 1}`)}>
                  {o.label}{o.id === run.ask.recommended ? " (recomendada)" : ""}
                </button>
              {/each}
            </div>
            {#if run.ask.deadline}<p class="hint">Segue sozinha com a recomendada às {clock(run.ask.deadline)}.</p>{/if}
          </div>
        </section>
      {/if}
      {#each run.pending_ops as p (p.id)}
        <section class="card op"><div class="in"><strong>Operador analisando</strong><p>{p.text}</p></div></section>
      {/each}
      {#each proposals as op (op.id)}
        <section class="card op">
          <div class="in">
            <strong>Proposta do operador</strong>
            <p>{op.reply}</p>
            {#if op.commands.length}
              <ul class="cmds">{#each op.commands as c}<li>{c}</li>{/each}</ul>
              <div class="row">
                <button class="btn primary sm" onclick={() => applyOp(op)}>Aplicar {op.commands.length === 1 ? "o comando" : `os ${op.commands.length} comandos`}</button>
                <button class="btn outline sm" onclick={() => closeOp(op.id)}>Descartar</button>
              </div>
            {:else}
              <div class="row"><button class="btn outline sm" onclick={() => closeOp(op.id)}>Fechar</button></div>
            {/if}
          </div>
        </section>
      {/each}
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
