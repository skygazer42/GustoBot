<template>
  <svg class="ui-icon" :viewBox="name === 'bot' ? '0 0 32 32' : '0 0 24 24'" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">
    <path :d="paths[name]" />
  </svg>
</template>

<script setup lang="ts">
defineProps<{ name: keyof typeof paths }>();

const paths = {
  bot: "M16 5V3m-3 0h6M8 10h16a3 3 0 0 1 3 3v10a3 3 0 0 1-3 3H8a3 3 0 0 1-3-3V13a3 3 0 0 1 3-3ZM2 15v6m28-6v6M10 26v3m12-3v3M11 16v2m10-2v2m-9 4c2.3 1.5 5.7 1.5 8 0",
  clock: "M20 12a8 8 0 1 1-16 0 8 8 0 0 1 16 0ZM12 7v5l3 2",
  people: "M12 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM3 20v-2a6 6 0 0 1 12 0v2m1-15a3 3 0 0 1 0 6m2 3a5 5 0 0 1 3 4v2",
  arrow: "M5 12h14m-5-5 5 5-5 5",
  back: "M19 12H5m5-5-5 5 5 5",
  down: "m6 9 6 6 6-6",
  chevron: "m9 6 6 6-6 6",
  expand: "M14 4h6v6m-6 0 6-6M10 20H4v-6m6 0-6 6",
  up: "M12 19V5m-6 6 6-6 6 6",
  check: "m5 12 4 4L19 6",
  close: "m6 6 12 12M6 18 18 6",
  ask: "M7 18H4l1-4a8 8 0 1 1 4 5M10 9a2 2 0 1 1 3 1.7c-1 .5-1 1.3-1 1.3m0 3h.01",
  leaf: "M19 4c-9-1-15 3-14 9a6 6 0 0 0 10 4c3-3 3-7 4-13ZM5 21l8-10",
  attachment: "m8 13 7-7a3 3 0 0 1 4 4l-9 9a5 5 0 0 1-7-7l9-9m-3 12 7-7",
  new: "M12 5v14M5 12h14",
  home: "m3 10 9-7 9 7v10H15v-7H9v7H3Z",
  file: "M14 3H5v18h14V8ZM14 3v5h5M8 12h8M8 16h5",
  book: "M3 4h6a4 4 0 0 1 3 1 4 4 0 0 1 3-1h6v16h-6a4 4 0 0 0-3 1 4 4 0 0 0-3-1H3ZM12 5v16",
  graph: "M9 5a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM21 8a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM15 19a3 3 0 1 1-6 0 3 3 0 0 1 6 0ZM9 6l6 1M7 8l4 8M17 11l-4 5",
  test: "m9 4 2 2-4 4-2-2ZM13 4h7M13 9h7m-11 5 2 2-4 4-2-2Zm4 0h7M13 19h7",
  search: "M17 10a7 7 0 1 1-14 0 7 7 0 0 1 14 0Zm-2 5 6 6",
  refresh: "M20 7v5h-5M4 17v-5h5m-4 0a7 7 0 0 1 12-5l3 5M4 12l3 5a7 7 0 0 0 12-5",
  link: "m10 13 4-4m-7 5-2 2a3 3 0 0 0 4 4l4-4m-2-8 4-4a3 3 0 0 1 4 4l-2 2"
} as const;
</script>
