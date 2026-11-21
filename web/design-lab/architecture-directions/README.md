# GustoBot 本体架构图对比

用户已从英文图对比页选定 **03 技术总览**。英文主图保留，新增同构图中文配套图，展示为 04；01、02 继续作为知识表示和查询机制的说明图。

正式 PNG、SVG 位于 [`docs/assets/architecture`](../../../docs/assets/architecture/)，使用方式见 [`docs/ARCHITECTURE.md`](../../../docs/ARCHITECTURE.md)。英文版为 Arial 常规字重；中文版采用宋体中文与 Times New Roman 英文、数字。README 展示宽度为 800px。四张 PNG 为 2800×1300，SVG 文字转为矢量路径，均无前端运行依赖。此前的执行流程与 Mermaid 保留在 [`ARCHITECTURE_FLOW.md`](../../../docs/ARCHITECTURE_FLOW.md)。

| 图示 | 侧重点 |
| --- | --- |
| 知识表示 | 本体、实例事实与来源原文的关联 |
| 查询与求值 | 查询规划、联合取证、规则求值与有据回答 |
| 03 技术总览 · 英文（已选） | 构建和问答共享本体基础，图谱与原文汇流取证 |
| 04 技术总览 · 中文 | 03 的宋体 / Times New Roman 配套图 |

开发服务运行时可打开 `/design-lab/architecture-directions/`。`index.html` 由 Oil UI Pro 0.34.5 的对比页工具生成，内嵌上述正式 PNG，支持并排、单张与原生尺寸查看。此目录只是选图工具，README 使用图片不需要启动它。

README 技术架构默认展示已选英文03，中文版可展开查看；知识表示与查询机制图放在对应说明段落。此轮中文配套仅调整语言和字体，已按800px自查；英文文件哈希核对保留。之前资源保留供回看，历史说明见 [`ARCHITECTURE_OPTIONS.md`](../../../docs/ARCHITECTURE_OPTIONS.md)。
