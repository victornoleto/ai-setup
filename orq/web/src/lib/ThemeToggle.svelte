<script lang="ts">
  import Icon from "./Icon.svelte";
  import type { Theme } from "./theme";

  let { theme = $bindable() }: { theme: Theme } = $props();
</script>

<span class="sp theme" role="group" aria-label="Tema">
  <button aria-pressed={theme === "light"} onclick={() => (theme = "light")}><Icon name="sun" />Claro</button>
  <button aria-pressed={theme === "dark"} onclick={() => (theme = "dark")}><Icon name="moon" />Escuro</button>
</span>
