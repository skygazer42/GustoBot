<template>
  <figure class="architecture-figure" aria-labelledby="architecture-description">
    <div class="architecture-flow" :style="{ '--selected-route': selectedIndex, '--merge-top': `${Math.min((selectedIndex + .5) * 25, 50)}%`, '--merge-height': `${Math.abs((selectedIndex + .5) * 25 - 50)}%` }">
      <div class="architecture-entry">
        <section class="architecture-node architecture-input" aria-labelledby="architecture-input-title">
          <p class="architecture-node-label">起点 / INPUT</p>
          <h3 id="architecture-input-title">自然语言 / 文件</h3>
          <p>问题与需要处理的资料</p>
        </section>
        <section class="architecture-node architecture-api" aria-labelledby="architecture-api-title">
          <p class="architecture-node-label">接收 / RECEIVE</p>
          <h3 id="architecture-api-title" class="architecture-latin">FastAPI</h3>
          <p>接收请求</p>
        </section>
        <section class="architecture-node architecture-router" aria-labelledby="architecture-router-title">
          <p class="architecture-node-label">编排 / ORCHESTRATE</p>
          <h3 id="architecture-router-title" class="architecture-latin">LangGraph</h3>
          <p>理解对象与条件，组织证据</p>
        </section>
        <p class="architecture-fork-note">
          <strong>一份计划，按需取证。</strong>
          <span>依据领域定义，组合事实与原文。</span>
        </p>
      </div>

      <div class="architecture-processing">
        <span class="architecture-distribution" aria-hidden="true"></span>
        <span class="architecture-merge-selected" aria-hidden="true"></span>
        <div class="architecture-path-group">
          <p class="architecture-path-label">点选一条路径，看看如何取证与回答。</p>
          <ul class="architecture-paths" aria-label="按需使用的能力，事实与文档可组合取证">
            <li v-for="(path, index) in paths" :key="path.title" :class="{ 'is-selected': selectedIndex === index }">
              <span class="architecture-branch-line" aria-hidden="true"></span>
              <button class="architecture-path-button" type="button" :aria-pressed="selectedIndex === index" :aria-label="path.title" aria-controls="architecture-answer" @click="selectedIndex = index">
                <span class="architecture-number" aria-hidden="true">{{ String(index + 1).padStart(2, '0') }}</span>
                <span class="architecture-path-title">{{ path.title }}</span>
                <span class="architecture-path-copy"><span class="architecture-technology">{{ path.technology }}</span><span>{{ path.description }}</span></span>
              </button>
            </li>
          </ul>
        </div>

        <section id="architecture-answer" class="architecture-answer" aria-labelledby="architecture-answer-title" aria-live="polite">
          <p class="architecture-node-label">汇总 / RESPONSE</p>
          <h3 id="architecture-answer-title">回答</h3>
          <p class="architecture-answer-main">{{ selectedPath.output }}</p>
          <p class="architecture-sample">{{ selectedPath.evidence }}</p>
          <p class="architecture-source">{{ selectedPath.source }}</p>
        </section>
      </div>
    </div>
    <figcaption id="architecture-description" class="sr-only">
      自然语言或文件经 FastAPI 接收，由统一问答流程依据本体理解对象与条件，按需查询事实和原文，返回回答与来源。
      Neo4j 保存菜谱事实与关系，Milvus 检索文档片段。临时附件阅读与长期知识导入分别处理。
    </figcaption>
  </figure>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";

const paths = [
  { title: "日常问答", technology: "大模型", description: "回答当前领域的一般问题。", output: "把一般问题说清楚", evidence: "结合当前对话回答；没有资料支持的具体用量，不凭空估算。", source: "回答方式 · 不代表实时查询结果" },
  { title: "文档检索", technology: "Milvus · 原文片段", description: "按来源与版本查找相关内容。", output: "带着原文回答", evidence: "“锅中油预热，放入蛋液。”", source: "菜谱原文 · data/recipe.json / 番茄炒蛋" },
  { title: "事实与关系", technology: "OWL / SHACL / Neo4j", description: "对齐具体做法，求值并校验证据。", output: "先确认做法，再查事实", evidence: "RecipeVariant → HAS_STEP → CookingStep", source: "关系定义 · recipes.ttl / HAS_STEP" },
  { title: "附件阅读", technology: "上传 → 解析 → 本轮阅读", description: "临时附件与长期知识分别处理。", output: "依据本轮附件回答", evidence: "先解析文件，再结合问题读取内容。文件未记载的内容，明确说明。", source: "处理方式 · 长期知识单独导入" }
];
const selectedIndex = ref(2);
const selectedPath = computed(() => paths[selectedIndex.value]);
</script>

<style scoped lang="scss">
.architecture-figure {
  container-type: inline-size;
  margin: 0;
  color: var(--ink);
  font-family: var(--sans);
}

.architecture-flow {
  --route-gutter: clamp(42px, 6.9cqw, 70px);
  --merge-gutter: clamp(46px, 8.7cqw, 88px);
  --answer-width: clamp(190px, 23cqw, 250px);
  --router-center: 59.375%;
  padding-top: 6px;
}

.architecture-entry {
  display: grid;
  grid-template-columns: repeat(16, minmax(0, 1fr));
  align-items: stretch;
  margin-bottom: 60px;
}

.architecture-node {
  position: relative;
  min-width: 0;
  min-height: 117px;
  padding-top: 14px;
  border-top: 2px solid var(--clay);
}

.architecture-input { grid-column: 1 / 4; }
.architecture-api { grid-column: 5 / 8; }
.architecture-router { grid-column: 9 / 12; }

.architecture-node p,
.architecture-answer p,
.architecture-path-copy {
  margin: 0;
  color: var(--muted);
  font-size: 14px;
  line-height: 1.6;
}

.architecture-node .architecture-node-label,
.architecture-answer .architecture-node-label {
  margin: 0 0 10px;
  font-size: 14px;
  line-height: 1.4;
}

.architecture-node h3 {
  margin: 0 0 8px;
  font-family: var(--serif);
  font-size: 22px;
  font-weight: 600;
  line-height: 1.25;
}

.architecture-node .architecture-latin {
  font-family: var(--sans);
  font-size: 24px;
  font-weight: 400;
}

.architecture-router h3 { color: var(--clay); }

.architecture-input::after,
.architecture-api::after {
  position: absolute;
  top: 57px;
  left: calc(100% + 12px);
  width: calc(100% / 3 - 24px);
  height: 1px;
  background: var(--clay);
  content: '';
}

.architecture-input::before,
.architecture-api::before {
  position: absolute;
  top: 54px;
  right: calc(-100% / 3 + 12px);
  width: 6px;
  height: 6px;
  border-top: 1px solid var(--clay);
  border-right: 1px solid var(--clay);
  transform: rotate(45deg);
  content: '';
}

.architecture-router::after {
  position: absolute;
  top: 100%;
  left: 50%;
  width: 1px;
  height: 42px;
  background: var(--clay);
  content: '';
}

.architecture-fork-note {
  grid-column: 13 / 17;
  align-self: start;
  margin: 5px 0 0;
  padding-left: 18px;
  border-left: 1px solid var(--line);
  color: var(--muted);
  font-size: 14px;
  line-height: 1.7;
}

.architecture-fork-note strong,
.architecture-fork-note span { display: block; }
.architecture-fork-note strong { color: var(--ink); font-weight: 500; }

.architecture-processing {
  position: relative;
  display: grid;
  grid-template-columns: var(--route-gutter) minmax(0, 1fr) var(--merge-gutter) var(--answer-width);
  align-items: center;
}

.architecture-distribution {
  position: absolute;
  z-index: 1;
  top: -18px;
  right: calc(100% - var(--router-center));
  bottom: calc(100% - (var(--selected-route) + .5) * 25%);
  left: calc(var(--route-gutter) * .4);
  border-top: 1px solid var(--clay);
  border-left: 1px solid var(--clay);
  pointer-events: none;
}

.architecture-path-group { position: relative; grid-column: 2; min-width: 0; }
.architecture-path-label { position: absolute; top: -48px; margin: 0; color: var(--muted); font-size: 13px; }
.architecture-merge-selected { position: absolute; z-index: 1; top: var(--merge-top); right: calc(var(--answer-width) + var(--merge-gutter) * .5); width: 1px; height: var(--merge-height); background: var(--clay); pointer-events: none; }

.architecture-paths {
  position: relative;
  display: grid;
  grid-template-rows: repeat(4, minmax(96px, 1fr));
  margin: 0;
  padding: 0;
  list-style: none;
}

.architecture-paths::before,
.architecture-paths::after {
  position: absolute;
  top: 12.5%;
  bottom: 12.5%;
  width: 1px;
  background: var(--control-line);
  content: '';
}

.architecture-paths::before { left: calc(var(--route-gutter) * -.6); }
.architecture-paths::after { right: calc(var(--merge-gutter) * -.5); }

.architecture-paths > li {
  position: relative;
  min-width: 0;
  border-top: 1px solid var(--line);
}

.architecture-path-button {
  display: grid;
  grid-template-columns: 40px minmax(100px, .85fr) minmax(0, 1.5fr);
  align-items: start;
  width: 100%;
  min-height: 100%;
  padding: 17px 10px 17px 0;
  border: 0;
  border-radius: 6px;
  color: inherit;
  background: transparent;
  text-align: left;
  transition: background-color var(--duration) var(--ease);
}
.architecture-path-button:hover,
.architecture-paths > .is-selected .architecture-path-button { background: var(--wash); }
.architecture-paths > .is-selected .architecture-path-title { color: var(--clay); }

.architecture-paths > li:last-child { border-bottom: 1px solid var(--line); }

.architecture-branch-line {
  position: absolute;
  top: 50%;
  left: calc(var(--route-gutter) * -.6);
  width: calc(var(--route-gutter) * .6 - 12px);
  height: 1px;
  background: var(--control-line);
}

.architecture-branch-line::before {
  position: absolute;
  top: -3px;
  left: -3px;
  width: 7px;
  height: 7px;
  border: 1px solid var(--clay);
  border-radius: 50%;
  background: var(--paper);
  content: '';
}

.architecture-branch-line::after,
.architecture-answer::after {
  position: absolute;
  top: -3px;
  right: 0;
  width: 6px;
  height: 6px;
  border-top: 1px solid var(--clay);
  border-right: 1px solid var(--clay);
  transform: rotate(45deg);
  content: '';
}

.architecture-paths > li::after {
  position: absolute;
  top: 50%;
  right: calc(var(--merge-gutter) * -.5);
  width: calc(var(--merge-gutter) * .5 - 12px);
  height: 1px;
  background: var(--control-line);
  content: '';
}

.architecture-number {
  color: var(--clay);
  font-family: var(--serif);
  font-size: 24px;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.architecture-path-title {
  margin: 1px 0 0;
  font-family: var(--serif);
  font-size: 19px;
  font-weight: 600;
  line-height: 1.3;
}

.architecture-path-copy { min-width: 0; padding-left: 7px; }
.architecture-path-copy > span { display: block; }

.architecture-path-copy .architecture-technology {
  margin-bottom: 7px;
  color: var(--ink);
  font-family: var(--sans);
  font-size: 15px;
  line-height: 1.3;
}

.architecture-answer {
  position: relative;
  grid-column: 4;
  min-width: 0;
  padding: 17px 0 20px 22px;
  border-left: 2px solid var(--clay);
}

.architecture-answer::before {
  position: absolute;
  top: 50%;
  left: calc(var(--merge-gutter) * -.5);
  width: calc(var(--merge-gutter) * .5 - 12px);
  height: 1px;
  background: var(--clay);
  content: '';
}

.architecture-answer::after {
  top: calc(50% - 3px);
  right: auto;
  left: -18px;
}

.architecture-answer .architecture-node-label {
  color: var(--clay);
  font-family: var(--archive-latin, Georgia, serif), var(--sans);
  letter-spacing: .4px;
}

.architecture-answer h3 {
  margin: 0 0 18px;
  font-family: var(--serif);
  font-size: 35px;
  font-weight: 600;
  line-height: 1.15;
  letter-spacing: 2px;
}

.architecture-answer .architecture-answer-main {
  margin-bottom: 10px;
  color: var(--ink);
  font-size: 16px;
  line-height: 1.6;
}

.architecture-answer .architecture-sample { color: var(--ink); overflow-wrap: anywhere; }
.architecture-answer .architecture-source { margin-top: 12px; font-size: 13px; }
.architecture-paths > .is-selected::after,
.architecture-paths > .is-selected .architecture-branch-line { background: var(--clay); }
.architecture-paths > .is-selected .architecture-branch-line::before { background: var(--clay); }

@container (max-width: 900px) and (min-width: 801px) {
  .architecture-path-button { grid-template-columns: 34px minmax(92px, .85fr) minmax(0, 1.5fr); }
  .architecture-path-copy { padding-left: 0; }
}

@container (max-width: 800px) {
  .architecture-entry {
    grid-template-columns: minmax(0, 1fr);
    gap: 25px;
    margin-bottom: 24px;
  }

  .architecture-input,
  .architecture-api,
  .architecture-router,
  .architecture-fork-note { grid-column: 1; }

  .architecture-node {
    min-height: 0;
    padding: 14px 0 0;
  }

  .architecture-input::after,
  .architecture-api::after,
  .architecture-router::after {
    top: 100%;
    left: 20px;
    width: 1px;
    height: 25px;
  }

  .architecture-input::before,
  .architecture-api::before {
    top: calc(100% + 18px);
    right: auto;
    left: 17px;
    transform: rotate(135deg);
  }

  .architecture-router::after { display: none; }

  .architecture-fork-note {
    margin: 0;
    padding-left: 14px;
  }

  .architecture-processing {
    grid-template-columns: minmax(0, 1fr);
    gap: 28px;
  }

  .architecture-path-group {
    grid-column: 1;
    padding-left: 16px;
    border-left: 2px solid var(--clay);
  }

  .architecture-path-label {
    position: static;
    display: block;
    margin: 0 0 14px;
    color: var(--clay);
    font-size: 14px;
    font-weight: 600;
    line-height: 1.5;
  }

  .architecture-paths { grid-template-rows: none; }

  .architecture-path-button {
    grid-template-columns: 36px minmax(0, 1fr);
    gap: 8px 0;
    padding: 17px 0;
  }

  .architecture-number { grid-row: 1 / span 2; }
  .architecture-path-title { font-size: 20px; }
  .architecture-path-copy { grid-column: 2; padding-left: 0; }
  .architecture-path-copy .architecture-technology { font-size: 15px; }
  .architecture-distribution,
  .architecture-merge-selected,
  .architecture-paths::before,
  .architecture-paths::after,
  .architecture-branch-line,
  .architecture-paths > li::after { display: none; }

  .architecture-answer {
    grid-column: 1;
    padding: 18px 0 24px;
    border-top: 2px solid var(--clay);
    border-left: 0;
  }

  .architecture-answer::before {
    top: -29px;
    left: 20px;
    width: 1px;
    height: 27px;
  }

  .architecture-answer::after {
    top: -8px;
    left: 17px;
    transform: rotate(135deg);
  }

  .architecture-answer h3 { margin-bottom: 12px; font-size: 30px; }
}
</style>
