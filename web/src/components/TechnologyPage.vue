<template>
  <main class="technology-page" aria-labelledby="technology-title">
    <header class="archive-intro">
      <p class="archive-eyebrow"><span>01</span> Technical archive</p>
      <h1 id="technology-title" tabindex="-1"><span>技术</span><span>路线</span></h1>
      <p class="archive-english" lang="en">Behind the table.</p>
      <p class="archive-deck">一道问题进入陶陶，<br />会走过怎样的工序？<br />这里记录从提问到回答的<br /><span>处理路径与资料来处。</span></p>
    </header>

    <section class="archive-flow" aria-labelledby="flow-title">
      <header class="archive-flow-heading">
        <h2 id="flow-title">从一个问题，到一份回答。</h2>
        <p lang="en">Question → Evidence → Response</p>
      </header>
      <ArchitectureDiagram />
      <dl class="archive-implementation" aria-label="技术与数据补注">
        <div><dt>界面与服务</dt><dd>Vue 3 / TypeScript / Vite<span>FastAPI / LangGraph 负责接收与编排</span></dd></div>
        <div><dt>检索补注</dt><dd>本体约束事实与原文查询<span>Neo4j 管关系，Milvus 查原文，MySQL 保存会话与导入状态。</span></dd></div>
      </dl>
    </section>

    <aside class="archive-source" aria-labelledby="source-note-title">
      <p class="archive-label">Reference / 资料边注</p>
      <h2 id="source-note-title">知道答案，也关心来处。</h2>
      <p>菜谱主数据来自 <span lang="en">OpenKG RecipeGraph</span>。</p>
      <p>资料来源说明内容出处，检索后端说明查找位置。数据许可单独记录。</p>
      <a class="info-text-link archive-source-link" href="https://github.com/skygazer42/GustoBot/blob/main/docs/DATA_SOURCES.md" target="_blank" rel="noopener noreferrer">查看数据来源与许可<UiIcon name="expand" /><span class="sr-only">（在新标签页打开）</span></a>
    </aside>

    <footer class="archive-footer">
      <span lang="en">GustoBot / Notes on technology</span>
      <span>把问题交给合适的处理路径</span>
      <a class="info-text-link" href="?page=about" @click="emit('navigate', $event)">认识陶陶<UiIcon name="arrow" /></a>
    </footer>
  </main>
</template>

<script setup lang="ts">
import ArchitectureDiagram from "./ArchitectureDiagram.vue";
import UiIcon from "./UiIcon.vue";

const emit = defineEmits<{ (event: "navigate", eventObject: MouseEvent): void }>();
</script>

<style scoped lang="scss">
.technology-page {
  display: grid;
  grid-template-areas: 'intro flow' 'source flow' 'footer footer';
  grid-template-columns: 208px minmax(0, 1fr);
  grid-template-rows: auto 1fr auto;
  gap: 28px 40px;
  width: min(var(--container-max), calc(100% - 48px));
  margin: 0 auto;
  padding: 40px 0 20px;
  animation: archive-arrive 220ms var(--ease) both;
}
.archive-intro { grid-area: intro; }
.archive-eyebrow {
  display: flex;
  align-items: baseline;
  gap: 14px;
  margin: 0;
  color: var(--clay);
  font-family: var(--archive-latin);
  font-size: 13px;
  line-height: 1.8;
  letter-spacing: .2px;
}
.archive-eyebrow > span { color: var(--ink); font-size: 18px; letter-spacing: 0; }
.archive-intro h1 {
  margin: 22px 0 18px;
  font-family: var(--serif);
  font-size: 36px;
  font-weight: 600;
  line-height: 1.22;
  letter-spacing: 2px;
}
.archive-intro h1 > span { display: inline; }
.archive-english { margin: 0 0 28px; color: var(--clay); font: 15px / 1.6 var(--sans); }
.archive-deck { margin: 0; font-size: 16px; line-height: 1.8; }
.archive-deck > span { padding-bottom: 4px; border-bottom: 1px solid var(--archive-number); }
.archive-flow { grid-area: flow; min-width: 0; }
.archive-flow-heading {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px 24px;
  margin-bottom: 18px;
  padding-bottom: 15px;
  border-bottom: 1px solid var(--line);
}
.archive-flow-heading h2 { margin: 0; font-family: var(--serif); font-size: 23px; font-weight: 600; line-height: 1.5; }
.archive-flow-heading p { margin: 0; color: var(--clay); font: 13px / 1.5 var(--sans); }
.archive-implementation {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 24px 38px;
  margin: 0;
  padding-top: 16px;
  border-top: 1px solid var(--ink);
}
.archive-implementation dt { margin-bottom: 6px; color: var(--clay); font-family: var(--serif); font-size: 15px; }
.archive-implementation dd { margin: 0; font-size: 14px; line-height: 1.75; }
.archive-implementation dd > span { display: block; margin-top: 4px; color: var(--muted); }
.archive-source { grid-area: source; align-self: end; min-width: 0; padding-top: 16px; border-top: 1px solid var(--ink); }
.archive-source .archive-label {
  margin: 0 0 12px;
  color: var(--clay);
  font-family: var(--archive-latin), var(--sans);
  font-size: 13px;
  letter-spacing: .2px;
}
.archive-source h2 { margin: 0 0 12px; font-family: var(--serif); font-size: 18px; font-weight: 600; line-height: 1.6; }
.archive-source > p:not(.archive-label) { margin: 0 0 12px; color: var(--muted); font-size: 14px; line-height: 1.8; }
.archive-source-link { gap: 24px; font-size: 14px; text-decoration-color: var(--clay); }
.archive-source-link .ui-icon { transition: transform var(--duration) var(--ease); }
.archive-source-link:hover .ui-icon { transform: translate(2px, -2px); }
.archive-source-link:active { transform: translateY(1px); }
.archive-footer {
  grid-area: footer;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px 24px;
  margin-top: 2px;
  padding-top: 8px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 14px;
}
.archive-footer > [lang='en'] { font-family: var(--sans); font-size: 13px; }
@keyframes archive-arrive {
  from { opacity: 0.7; transform: translateY(4px); }
  to { opacity: 1; transform: translateY(0); }
}
@media (max-width: 1100px) {
  .technology-page {
    grid-template-areas: 'intro' 'flow' 'source' 'footer';
    grid-template-columns: minmax(0, 1fr);
    grid-template-rows: auto;
    row-gap: 32px;
  }
  .archive-intro { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); column-gap: 32px; }
  .archive-eyebrow { grid-column: 1 / -1; }
  .archive-intro h1 { margin: 12px 0; font-size: 36px; }
  .archive-intro h1 > span { display: inline; }
  .archive-english { grid-column: 1; margin: 0; }
  .archive-deck { grid-column: 2; grid-row: 2 / span 2; align-self: center; }
  .archive-source { display: grid; grid-template-columns: 1fr 1fr; column-gap: 38px; }
  .archive-source .archive-label { grid-column: 1; }
  .archive-source h2 { grid-column: 1; }
  .archive-source > p:not(.archive-label) { grid-column: 2; }
  .archive-source > p:nth-of-type(2) { grid-row: 1 / span 2; }
  .archive-source > p:nth-of-type(3) { grid-row: 3; }
  .archive-source-link { grid-column: 1; grid-row: 3; justify-self: start; }
}
@media (max-width: 600px) {
  .technology-page { width: calc(100% - 40px); row-gap: 28px; padding-top: 26px; }
  .archive-intro { display: block; }
  .archive-intro h1 { margin: 14px 0 10px; font-size: 32px; }
  .archive-english { margin-bottom: 22px; }
  .archive-deck { font-size: 16px; }
  .archive-deck > br { display: none; }
  .archive-flow-heading { display: block; margin-bottom: 20px; }
  .archive-flow-heading h2 { font-size: 21px; }
  .archive-flow-heading p { margin-top: 8px; }
  .archive-implementation { grid-template-columns: minmax(0, 1fr); gap: 20px; padding-top: 20px; }
  .archive-source { display: block; }
  .archive-source h2 { font-size: 21px; }
  .archive-footer { flex-direction: column; align-items: flex-start; gap: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  .technology-page { animation: none; }
  .archive-source-link .ui-icon { transition: none; }
  .archive-source-link:hover .ui-icon { transform: none; }
}
</style>
