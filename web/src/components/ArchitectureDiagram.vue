<template>
  <figure class="architecture-figure" aria-labelledby="architecture-caption">
    <div class="architecture-column-labels" aria-hidden="true">
      <span>01 / 提问</span><span>02 / 理解与编排</span><span>03 / 按需处理</span><span>04 / 回答</span>
    </div>
    <div class="architecture-graph">
      <div class="architecture-node architecture-input">
        <UiIcon name="ask" />
        <strong>你的问题</strong>
        <span>自然语言 · 附件</span>
      </div>

      <div class="architecture-node architecture-router">
        <span class="architecture-api">FastAPI · 请求入口</span>
        <UiIcon name="bot" />
        <strong>LangGraph</strong>
        <span>意图识别与分流</span>
      </div>

      <div class="architecture-processing">
        <p class="architecture-path-label">按意图选择处理路径</p>
        <ul class="architecture-paths" aria-label="按需选择的主要处理分支">
          <li class="architecture-node"><strong>日常问答</strong><span>大模型 · 直接回答</span></li>
          <li class="architecture-node"><strong>知识检索</strong><span>pgvector <span aria-label="无合格结果时后备到">→</span> Milvus</span></li>
          <li class="architecture-node"><strong>图谱与统计</strong><span>Neo4j · MySQL</span></li>
          <li class="architecture-node"><strong>文件处理</strong><span>解析 → 入库 → 检索</span></li>
        </ul>
      </div>

      <div class="architecture-node architecture-output">
        <UiIcon name="check" />
        <strong>汇总回答</strong>
        <span>正文 · 可用来源</span>
      </div>
    </div>
    <figcaption id="architecture-caption" class="architecture-caption">
      <span class="architecture-legend"><i aria-hidden="true"></i>主要调用方向</span>
      <span>各分支按需调用；知识检索无合格结果时，再由 pgvector 转向 Milvus。</span>
    </figcaption>
  </figure>
</template>

<script setup lang="ts">
import UiIcon from "./UiIcon.vue";
</script>

<style scoped lang="scss">
.architecture-figure {
  --connector: var(--clay);
  --connector-gap: 32px;
  margin: 0;
}

.architecture-column-labels,
.architecture-graph {
  display: grid;
  grid-template-columns: 1fr 1.15fr 1.65fr 1fr;
  column-gap: var(--connector-gap);
}

.architecture-column-labels {
  margin-bottom: 18px;
  color: var(--muted);
  font-size: 11px;
  line-height: 1.8;
}

.architecture-graph {
  align-items: center;
}

.architecture-node {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 0;
  padding: 16px 10px;
  border: 1px solid var(--control-line);
  border-radius: 6px;
  background: var(--surface);
  text-align: center;
}

.architecture-node strong {
  font-size: 14px;
  font-weight: 700;
  line-height: 1.7;
}

.architecture-node > span {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.8;
}

.architecture-node > .ui-icon {
  width: 22px;
  height: 22px;
  margin-bottom: 6px;
  color: var(--clay);
}

.architecture-input::after,
.architecture-router::after,
.architecture-processing::after,
.architecture-paths > li::before,
.architecture-paths > li::after {
  position: absolute;
  top: 50%;
  height: 1px;
  background: var(--connector);
  content: '';
}

.architecture-input::after {
  right: calc(-1 * var(--connector-gap));
  width: var(--connector-gap);
}

.architecture-router {
  padding-top: 0;
  padding-bottom: 18px;
  border-color: var(--clay);
}

.architecture-router > .architecture-api {
  align-self: stretch;
  margin: 0 -10px 14px;
  padding: 9px 8px;
  border-bottom: 1px solid var(--control-line);
  border-radius: 5px 5px 0 0;
  color: var(--clay);
  background: var(--wash);
  font-size: 11px;
}

.architecture-router > .ui-icon {
  width: 28px;
  height: 28px;
}

.architecture-router::before,
.architecture-output::before,
.architecture-paths > li strong::before {
  position: absolute;
  top: calc(50% - 3px);
  left: -5px;
  width: 6px;
  height: 6px;
  border-top: 1px solid var(--connector);
  border-right: 1px solid var(--connector);
  content: '';
  transform: rotate(45deg);
}

.architecture-router::after {
  right: calc(-0.5 * var(--connector-gap));
  width: calc(0.5 * var(--connector-gap));
}

.architecture-processing {
  position: relative;
  min-width: 0;
}

.architecture-path-label {
  display: none;
}

.architecture-paths {
  position: relative;
  display: grid;
  gap: 12px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.architecture-paths::before,
.architecture-paths::after {
  position: absolute;
  top: 38px;
  bottom: 38px;
  width: 1px;
  background: var(--connector);
  content: '';
}

.architecture-paths::before {
  left: calc(-0.5 * var(--connector-gap));
}

.architecture-paths::after {
  right: calc(-0.5 * var(--connector-gap));
}

.architecture-paths > li {
  height: 76px;
  padding: 10px;
  border-color: var(--line);
}

.architecture-paths > li::before {
  left: calc(-0.5 * var(--connector-gap));
  width: calc(0.5 * var(--connector-gap));
}

.architecture-paths > li::after {
  right: calc(-0.5 * var(--connector-gap));
  width: calc(0.5 * var(--connector-gap));
}

.architecture-processing::after {
  right: calc(-1 * var(--connector-gap));
  width: calc(0.5 * var(--connector-gap));
}

.architecture-output {
  border-color: var(--clay);
}

.architecture-caption {
  display: flex;
  align-items: baseline;
  gap: 12px 20px;
  margin-top: 24px;
  padding-top: 16px;
  border-top: 1px solid var(--line);
  color: var(--muted);
  font-size: 12px;
  line-height: 1.9;
}

.architecture-legend {
  display: inline-flex;
  flex-shrink: 0;
  align-items: center;
  gap: 8px;
}

.architecture-legend i {
  width: 20px;
  height: 1px;
  background: var(--connector);
}

@media (max-width: 760px) {
  .architecture-column-labels {
    display: none;
  }

  .architecture-graph {
    grid-template-columns: minmax(0, 1fr);
    row-gap: 26px;
  }

  .architecture-input,
  .architecture-router,
  .architecture-output {
    width: min(100%, 320px);
    justify-self: center;
    padding: 12px;
  }

  .architecture-input,
  .architecture-output {
    display: grid;
    grid-template-columns: 24px auto;
    column-gap: 12px;
    justify-content: center;
    text-align: left;
  }

  .architecture-input > .ui-icon,
  .architecture-output > .ui-icon {
    grid-row: 1 / span 2;
    align-self: center;
    margin: 0;
  }

  .architecture-input::after,
  .architecture-router::after,
  .architecture-processing::after {
    top: 100%;
    right: auto;
    left: 50%;
    width: 1px;
    height: 26px;
  }

  .architecture-router::before,
  .architecture-output::before {
    top: -6px;
    left: calc(50% - 3px);
    transform: rotate(135deg);
  }

  .architecture-router {
    gap: 2px;
    padding-top: 0;
  }

  .architecture-router > .architecture-api {
    margin: 0 -12px 9px;
    padding: 6px 8px;
  }

  .architecture-router > .ui-icon {
    display: none;
  }

  .architecture-processing {
    padding: 12px;
    border: 1px dashed var(--control-line);
    border-radius: 6px;
  }

  .architecture-path-label {
    display: block;
    margin: 0 0 10px;
    color: var(--clay);
    font-size: 12px;
    line-height: 1.8;
    text-align: center;
  }

  .architecture-paths {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 10px;
  }

  .architecture-paths > li {
    height: auto;
    min-height: 76px;
    padding: 10px 6px;
  }

  .architecture-paths::before,
  .architecture-paths::after,
  .architecture-paths > li::before,
  .architecture-paths > li::after,
  .architecture-paths > li strong::before {
    display: none;
  }

  .architecture-caption {
    flex-direction: column;
    gap: 6px;
    margin-top: 20px;
  }
}
</style>
