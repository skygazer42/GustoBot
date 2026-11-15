<template>
  <main class="info-page" aria-labelledby="technology-title">
    <header class="info-heading">
      <p class="eyebrow">GustoBot · 工作方式</p>
      <h1 id="technology-title" tabindex="-1">技术路线</h1>
      <p class="info-deck">从一句提问，到有据可查的回答。</p>
    </header>

    <section class="technology-flow" aria-labelledby="flow-title">
      <div class="technology-flow-heading">
        <h2 id="flow-title">一张图，看懂陶陶</h2>
        <span>系统架构 / 主要处理路径</span>
      </div>
      <ArchitectureDiagram />
    </section>

    <div class="technology-detail-layout">
      <section aria-labelledby="stack-title">
        <div class="info-section-heading"><h2 id="stack-title">每一层，各司其职</h2><span>技术组成</span></div>
        <dl class="technology-stack">
          <div><dt>阅读与对话<span>Vue 3 · TypeScript · Vite</span></dt><dd>食谱阅读、伴随浮窗与完整工作台，共用一份对话状态。样式使用 SCSS，请求由 Axios 处理。</dd></div>
          <div><dt>服务与编排<span>FastAPI · LangGraph</span></dt><dd>接收提问与文件，识别意图，分发处理，再汇总结果。</dd></div>
          <div><dt>知识检索<span>pgvector · Milvus</span></dt><dd>默认优先检索 PostgreSQL；没有合格结果时，再查 Milvus。重排与外部检索按配置启用。</dd></div>
          <div><dt>关系与查询<span>Neo4j · MySQL · LightRAG</span></dt><dd>后端提供图谱关系查询、结构化统计与 LightRAG 检索分支，按问题和服务配置选择。</dd></div>
        </dl>
      </section>
      <aside class="technology-source-note" aria-labelledby="source-note-title">
        <UiIcon name="leaf" />
        <p class="eyebrow">资料手记</p>
        <h2 id="source-note-title">答案背后，<br />还有出处。</h2>
        <p>「检索后端」说明在哪里找到内容；「原始资料」说明内容从哪里来。两者各有含义。</p>
        <p>菜谱主数据来自 OpenKG RecipeGraph。数据来源与许可单独记录，便于查阅。</p>
        <a class="info-text-link" href="https://github.com/skygazer42/GustoBot/blob/main/docs/DATA_SOURCES.md" target="_blank" rel="noopener noreferrer">查看数据来源<UiIcon name="expand" /><span class="sr-only">（在新标签页打开）</span></a>
      </aside>
    </div>

    <footer class="info-footer">
      <span>把复杂留给系统，把清楚带回餐桌。</span>
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
.technology-flow {
  padding: 24px 28px 30px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
}

.technology-flow-heading {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
}

.technology-flow-heading h2 {
  margin: 0;
  font-family: var(--serif);
  font-size: 20px;
  font-weight: 600;
}

.technology-flow-heading > span {
  color: var(--muted);
  font-size: 12px;
  white-space: nowrap;
}

.technology-detail-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 248px;
  gap: 48px;
  align-items: start;
  margin-top: 40px;
}

.technology-stack {
  margin: 0;
}

.technology-stack > div {
  padding: 18px 0;
  border-bottom: 1px solid var(--line);
}

.technology-stack > div:first-child {
  padding-top: 0;
}

.technology-stack dt {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 6px 16px;
  font-size: 15px;
  font-weight: 700;
}

.technology-stack dt span {
  color: var(--clay);
  font-size: 12px;
  font-weight: 400;
}

.technology-stack dd {
  margin: 7px 0 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.95;
}

.technology-source-note {
  padding: 24px;
  border-top: 2px solid var(--control-line);
  background: var(--surface);
}

.technology-source-note > .ui-icon {
  margin-bottom: 14px;
  color: var(--clay);
}

.technology-source-note .eyebrow {
  margin-bottom: 10px;
}

.technology-source-note h2 {
  margin: 0 0 20px;
  font-family: var(--serif);
  font-size: 23px;
  font-weight: 600;
  line-height: 1.65;
}

.technology-source-note > p:not(.eyebrow) {
  margin: 0 0 16px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.95;
}

@media (max-width: 760px) {
  .technology-flow-heading > span {
    display: none;
  }

  .technology-detail-layout {
    grid-template-columns: minmax(0, 1fr);
    gap: 28px;
  }

  .technology-source-note h2 br {
    display: none;
  }
}

@media (max-width: 420px) {
  .technology-flow {
    padding: 20px;
  }

  .technology-flow-heading h2 {
    font-size: 18px;
  }

}
</style>
