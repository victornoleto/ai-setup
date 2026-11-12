<script lang="ts">
  const PATHS: Record<string, string> = {
    check: "M5 12.5l4.5 4.5L19 7.5",
    alert: "M12 7v6M12 16.5v.5M12 2.5a9.5 9.5 0 1 0 0 19 9.5 9.5 0 0 0 0-19z",
    sun: "M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8zM12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M19 5l-1.5 1.5M6.5 17.5L5 19",
    moon: "M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z",
    back: "M15 6l-6 6 6 6",
    x: "M6 6l12 12M18 6L6 18",
  };
  let { name }: { name: keyof typeof PATHS } = $props();
</script>

<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d={PATHS[name]} /></svg>
