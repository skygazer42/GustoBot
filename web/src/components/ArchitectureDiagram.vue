<template>
  <figure class="architecture-figure" aria-labelledby="architecture-description">
    <div class="architecture-flow">
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
          <p>识别意图，按需分流</p>
        </section>
        <p class="architecture-fork-note">
          <strong>四条路径，按需选择。</strong>
          <span>依问题与资料，进入合适分支。</span>
        </p>
      </div>

      <div class="architecture-processing">
        <span class="architecture-distribution" aria-hidden="true"></span>
        <div class="architecture-path-group">
          <p class="architecture-path-label">按需选择的处理路径</p>
          <ul class="architecture-paths" aria-label="四条替代处理路径，并非依次执行">
            <li>
              <span class="architecture-branch-line" aria-hidden="true"></span>
              <span class="architecture-number" aria-hidden="true">01</span>
              <h3>日常问答</h3>
              <div class="architecture-path-copy">
                <p class="architecture-technology">大模型</p>
                <p>回答当前领域的一般问题。</p>
              </div>
            </li>
            <li>
              <span class="architecture-branch-line" aria-hidden="true"></span>
              <span class="architecture-number" aria-hidden="true">02</span>
              <h3>文档检索</h3>
              <div class="architecture-path-copy">
                <p class="architecture-technology architecture-fallback">
                  <span>LightRAG</span>
                  <span class="architecture-condition">共享领域索引</span>
                  <span>文档上下文</span>
                </p>
                <p>从当前领域资料中检索相关内容。</p>
              </div>
            </li>
            <li>
              <span class="architecture-branch-line" aria-hidden="true"></span>
              <span class="architecture-number" aria-hidden="true">03</span>
              <h3>关系与统计</h3>
              <div class="architecture-path-copy">
                <p class="architecture-technology">LightRAG / 可选 SQL</p>
                <p>同一索引回答关系问题；统计按需启用。</p>
              </div>
            </li>
            <li>
              <span class="architecture-branch-line" aria-hidden="true"></span>
              <span class="architecture-number" aria-hidden="true">04</span>
              <h3>文件处理</h3>
              <div class="architecture-path-copy">
                <p class="architecture-technology">解析 → 入库 → 检索</p>
                <p>将上传资料转为可检索的内容。</p>
              </div>
            </li>
          </ul>
        </div>

        <section class="architecture-answer" aria-labelledby="architecture-answer-title">
          <p class="architecture-node-label">汇总 / RESPONSE</p>
          <h3 id="architecture-answer-title">回答</h3>
          <p class="architecture-answer-main">正文<br class="architecture-answer-break">与可用来源</p>
          <p>汇总所选路径的结果；有来源信息时，一并列出出处。</p>
        </section>
      </div>
    </div>
    <figcaption id="architecture-description" class="sr-only">
      自然语言或文件经 FastAPI 接收，由 LangGraph 识别意图，按需调用处理分支，最终汇总正文与可用来源。
      四条分支为替代路径，并非依次执行。文档与关系检索共享当前领域的 LightRAG 索引，SQL 统计按需启用。
    </figcaption>
  </figure>
</template>

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
  --answer-width: clamp(150px, 17.6cqw, 178px);
  --router-center: 59.375%;
  padding-top: 6px;
}

.architecture-entry {
  display: grid;
  grid-template-columns: repeat(16, minmax(0, 1fr));
  align-items: stretch;
  margin-bottom: 28px;
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
.architecture-path-copy p {
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
  font-family: var(--archive-latin, Georgia, serif);
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
  height: 10px;
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
  top: -18px;
  right: calc(100% - var(--router-center));
  bottom: 87.5%;
  left: calc(var(--route-gutter) * .4);
  border-top: 1px solid var(--clay);
  border-left: 1px solid var(--clay);
  pointer-events: none;
}

.architecture-path-group { grid-column: 2; min-width: 0; }
.architecture-path-label { display: none; }

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
  background: var(--clay);
  content: '';
}

.architecture-paths::before { left: calc(var(--route-gutter) * -.6); }
.architecture-paths::after { right: calc(var(--merge-gutter) * -.5); }

.architecture-paths > li {
  position: relative;
  display: grid;
  grid-template-columns: 46px 164px minmax(0, 1fr);
  align-content: start;
  min-width: 0;
  padding: 17px 0 14px;
  border-top: 1px solid var(--line);
}

.architecture-paths > li:last-child { border-bottom: 1px solid var(--line); }

.architecture-branch-line {
  position: absolute;
  top: 50%;
  left: calc(var(--route-gutter) * -.6);
  width: calc(var(--route-gutter) * .6 - 12px);
  height: 1px;
  background: var(--clay);
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
  background: var(--clay);
  content: '';
}

.architecture-number {
  color: var(--archive-number, #94702c);
  font-family: var(--archive-latin, Georgia, serif);
  font-size: 26px;
  font-style: italic;
  line-height: 1.1;
  font-variant-numeric: tabular-nums;
}

.architecture-paths h3 {
  margin: 1px 0 0;
  font-family: var(--serif);
  font-size: 20px;
  font-weight: 600;
  line-height: 1.3;
}

.architecture-path-copy { min-width: 0; padding-left: 7px; }

.architecture-path-copy .architecture-technology {
  margin-bottom: 7px;
  color: var(--ink);
  font-family: var(--archive-latin, Georgia, serif), var(--sans);
  font-size: 18px;
  line-height: 1.3;
}

.architecture-fallback {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px 10px;
}

.architecture-fallback .architecture-condition {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--clay);
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.5;
}

.architecture-condition::before,
.architecture-condition::after {
  width: 12px;
  height: 1px;
  background: var(--clay);
  content: '';
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

@container (max-width: 900px) and (min-width: 801px) {
  .architecture-paths > li { grid-template-columns: 38px 132px minmax(0, 1fr); }
  .architecture-paths h3 { font-size: 19px; }
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
    display: block;
    margin: 0 0 14px;
    color: var(--clay);
    font-size: 14px;
    font-weight: 600;
    line-height: 1.5;
  }

  .architecture-paths { grid-template-rows: none; }

  .architecture-paths > li {
    grid-template-columns: 36px minmax(0, 1fr);
    gap: 8px 0;
    padding: 17px 0;
  }

  .architecture-number { grid-row: 1 / span 2; }
  .architecture-paths h3 { font-size: 20px; }
  .architecture-path-copy { grid-column: 2; padding-left: 0; }
  .architecture-path-copy .architecture-technology { font-size: 18px; }
  .architecture-condition::before,
  .architecture-condition::after { display: none; }

  .architecture-distribution,
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
  .architecture-answer-break { display: none; }
}
</style>
