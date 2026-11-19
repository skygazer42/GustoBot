<template>
  <main class="info-page" aria-labelledby="about-title">
    <header class="info-heading">
      <p class="eyebrow">GustoBot · 餐桌手记</p>
      <h1 id="about-title" tabindex="-1">关于陶陶</h1>
      <p class="info-deck">一份食谱，一次恰到好处的陪伴。</p>
    </header>

    <div class="about-story-layout">
      <section class="about-story" aria-labelledby="story-title">
        <h2 id="story-title">从「今天吃什么」，<br />到「原来这样做」。</h2>
        <p>做饭时，我们需要的有时是一份清楚的做法，有时只是一个小小的确认：鸡蛋什么时候盛出，番茄要炒到多软，手边少了一样食材又该怎么办。</p>
        <p>陶陶 · 餐桌手记，是 GustoBot 的食谱阅读与 AI 对话界面。食材、步骤和提问放在一起，让你读得明白，也能随时接着问。</p>
        <a class="about-primary-link" href="?" @click="emit('navigate', $event)">翻开今天的食谱<UiIcon name="arrow" /></a>
      </section>
      <aside class="about-letter" aria-label="陶陶的餐桌手记">
        <UiIcon class="about-bot" name="bot" />
        <p class="eyebrow">你好，我是陶陶</p>
        <p class="about-letter-title">不急，<br />这一餐慢慢来。</p>
        <span class="about-letter-rule" aria-hidden="true"></span>
        <p>陪你弄懂一点火候，<br />也多懂一点餐桌上的故事。</p>
        <span class="about-signature">陶陶</span>
      </aside>
    </div>

    <section class="about-principles" aria-labelledby="principles-title">
      <div class="info-section-heading"><h2 id="principles-title">我们在意的三件小事</h2></div>
      <ol>
        <li><span>01</span><h3>先把做法说清楚</h3><p>用量容易找，步骤容易读。火候和关键动作，值得被认真说明。</p></li>
        <li><span>02</span><h3>陪伴可以轻一点</h3><p>需要时展开对话，专心时轻轻收起。切换形态，问题和草稿都还在。</p></li>
        <li><span>03</span><h3>让知识有来处</h3><p>有参考资料的回答保留来源，让好奇心可以继续往下走。</p></li>
      </ol>
    </section>

    <section class="about-project" aria-labelledby="project-title">
      <div><p class="eyebrow">开放的厨房</p><h2 id="project-title">一起，把它做得更好。</h2><p>GustoBot 是一个菜谱知识问答开源项目。欢迎翻阅实现，也欢迎留下使用中的想法。</p></div>
      <div class="about-project-links">
        <a class="info-text-link" href="https://github.com/skygazer42/GustoBot" target="_blank" rel="noopener noreferrer">项目源码<UiIcon name="expand" /><span class="sr-only">（在新标签页打开）</span></a>
        <a class="info-text-link" href="https://github.com/skygazer42/GustoBot/issues" target="_blank" rel="noopener noreferrer">问题与建议<UiIcon name="expand" /><span class="sr-only">（在新标签页打开）</span></a>
      </div>
    </section>

    <footer class="info-footer">
      <span>代码采用 Apache-2.0 许可；第三方数据遵循各自许可。</span>
      <a class="info-text-link" href="?page=technology" @click="emit('navigate', $event)">看看技术路线<UiIcon name="arrow" /></a>
    </footer>
  </main>
</template>

<script setup lang="ts">
import UiIcon from "./UiIcon.vue";

const emit = defineEmits<{ (event: "navigate", eventObject: MouseEvent): void }>();
</script>

<style scoped lang="scss">
.about-story-layout {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 64px;
  align-items: start;
}

.about-story h2 {
  margin: 0 0 22px;
  font-family: var(--serif);
  font-size: 28px;
  font-weight: 600;
  line-height: 1.65;
}

.about-story > p {
  max-width: 64ch;
  margin: 0 0 18px;
  color: var(--muted);
  font-size: 16px;
  line-height: 1.9;
}

.about-primary-link {
  display: inline-flex;
  align-items: center;
  gap: 16px;
  min-height: 48px;
  margin-top: 12px;
  padding: 10px 20px;
  border-radius: 10px;
  color: var(--surface);
  background: var(--clay);
  font-size: 15px;
  text-decoration: none;
  transition: background-color var(--duration) var(--ease);
}
.about-primary-link:hover { background: var(--clay-hover); }

.about-letter {
  padding: 28px 30px 24px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--panel);
}

.about-bot {
  width: 48px;
  height: 48px;
  margin-bottom: 16px;
  color: var(--clay);
}

.about-letter .eyebrow {
  margin-bottom: 12px;
}

.about-letter-title {
  margin: 0;
  font-family: var(--serif);
  font-size: 25px;
  font-weight: 600;
  line-height: 1.7;
}

.about-letter-rule {
  display: block;
  width: 28px;
  height: 1px;
  margin: 20px 0;
  background: var(--control-line);
}

.about-letter-rule + p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.95;
}

.about-signature {
  display: block;
  margin-top: 20px;
  color: var(--clay);
  font-family: var(--serif);
  font-size: 19px;
  text-align: right;
}

.about-principles {
  margin-top: 42px;
}

.about-principles ol {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 32px;
  margin: 0;
  padding: 0;
  list-style: none;
}

.about-principles li {
  padding-top: 16px;
  border-top: 1px solid var(--line);
}

.about-principles li > span {
  color: var(--clay);
  font-family: var(--serif);
  font-size: 23px;
  font-style: italic;
  line-height: 1.5;
}

.about-principles h3 {
  margin: 9px 0 8px;
  font-size: 15px;
  font-weight: 700;
}

.about-principles li p {
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.95;
}

.about-project {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 32px;
  margin-top: 38px;
  padding: 24px 28px;
  border: 1px solid var(--line);
  border-radius: 6px;
  background: var(--surface);
}

.about-project h2 {
  margin: 0 0 7px;
  font-family: var(--serif);
  font-size: 23px;
  font-weight: 600;
  line-height: 1.6;
}

.about-project p:not(.eyebrow) {
  max-width: 460px;
  margin: 0;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.95;
}

.about-project-links {
  display: flex;
  flex-wrap: wrap;
  flex-shrink: 0;
  gap: 12px;
}

.about-project-links .info-text-link {
  padding: 7px 14px;
  border: 1px solid var(--control-line);
  border-radius: 24px;
  text-decoration: none;
}
.about-project-links .info-text-link:hover { background: var(--wash); }

@media (max-width: 760px) {
  .about-story-layout {
    grid-template-columns: minmax(0, 1fr) 230px;
    gap: 32px;
  }

  .about-letter {
    padding-right: 22px;
    padding-left: 22px;
  }

  .about-principles ol {
    gap: 24px;
  }
}

@media (max-width: 600px) {
  .about-story-layout,
  .about-principles ol {
    grid-template-columns: minmax(0, 1fr);
    gap: 28px;
  }

  .about-story h2 {
    font-size: 25px;
  }

  .about-letter {
    padding: 24px;
  }

  .about-principles {
    margin-top: 32px;
  }

  .about-principles li {
    display: grid;
    grid-template-columns: 36px minmax(0, 1fr);
    column-gap: 12px;
  }

  .about-principles li > span {
    grid-row: 1 / span 2;
  }

  .about-principles h3 {
    margin-top: 2px;
  }

  .about-project {
    align-items: flex-start;
    flex-direction: column;
    gap: 16px;
    padding: 22px;
  }

  .about-project-links {
    gap: 12px;
  }
}
</style>
