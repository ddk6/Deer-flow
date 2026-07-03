# DFlow 标书 Agent 改造路线

## 1. 当前判断

DFlow 适合以 DeerFlow 2.0 为基座做“标书 Agent”，但第一阶段不应该重写 Agent Runtime。当前最稳妥的切入点是 Skill 系统：新增一个标书领域 Skill，让 Agent 在不改核心编排、模型工厂、前端和沙箱的情况下，先具备招标文件解读、应答矩阵、风险清单和投标文件大纲能力。

## 2. 关键矛盾

| 矛盾 | 当前取舍 |
|---|---|
| 想快速做出标书能力 vs DeerFlow 架构较完整 | 先走 Skill，不碰运行时主链路 |
| 标书需要严谨溯源 vs LLM 容易补全幻觉 | 所有要求、风险、响应建议必须绑定来源条款 |
| 需要生成完整投标文件 vs 公司材料尚未结构化 | 先生成矩阵和大纲，再接入公司资料库 |
| 标书场景高风险 vs Agent 可自动调用工具 | 提交、签章、报价、法律承诺必须人工确认 |
| 未来要长期使用 vs 初期不要过度设计 | RAG、MCP、多 Agent 分阶段引入 |

## 3. 推荐方案

### 阶段 0：代码基座

- 已将本地 DeerFlow 源码初始化为 Git 仓库。
- `origin` 指向 `https://github.com/ddk6/DFlow.git`。
- `upstream` 指向 `https://github.com/bytedance/deer-flow.git`，并禁用 push，避免误推官方仓库。

### 阶段 1：标书 Skill MVP

新增 `skills/public/bid-proposal-agent/SKILL.md`：

- 招标文件解读
- 文件清单
- 要求矩阵
- 风险清单
- 投标策略
- 投标文件大纲
- 人工确认边界

技术成熟度：Production。原因是 DeerFlow 已有 Skill 加载、文件上传、沙箱和流式对话能力，新增 Skill 属于低风险扩展。

### 阶段 2：公司资料知识库

引入 RAG 保存公司资料：

- 资质证书
- 产品白皮书
- 项目案例
- 团队简历
- 售后服务承诺
- 合同红线
- 常用技术方案

技术成熟度：Pilot。原因是 RAG 对标书很有价值，但必须解决权限、版本、溯源和长期记忆污染问题。

### 阶段 3：标书生成流水线

建立结构化流程：

1. 上传招标文件
2. 自动解析文件清单
3. 抽取要求矩阵
4. 匹配公司资料
5. 生成响应策略
6. 分章节生成技术标/商务标
7. 自动审查 P0 风险
8. 导出 Word/Excel

技术成熟度：Production/Pilot 混合。文件解析和章节生成可进主流程，自动评分和风险判断先小范围试用。

### 阶段 4：工具与 MCP

可考虑 MCP 接入：

- 本地文件系统资料库
- 企业网盘
- PostgreSQL/SQLite 资料索引
- GitHub 项目资料

技术成熟度：Pilot。必须先定义目录白名单、只读权限、审计日志和人工确认。

### 阶段 5：多 Agent 审查

拆成角色：

- 招标文件解析员
- 商务响应员
- 技术方案专家
- 风险审查员
- 格式与交付检查员

技术成熟度：Lab。多 Agent 对质量审查有价值，但早期容易增加延迟、成本和不可控循环。

## 4. 架构图

```text
User
  |
  v
Frontend Chat / Upload
  |
  v
Gateway API --------------------+
  |                             |
  v                             v
LangGraph Agent Runtime      Uploaded Files
  |
  +--> Skill System
  |      |
  |      +--> bid-proposal-agent
  |
  +--> Tools
  |      |
  |      +--> read_file / write_file / web_search / document conversion
  |
  +--> Sandbox Workspace
         |
         +--> requirement_matrix.md
         +--> risk_register.md
         +--> proposal_outline.md
```

## 5. 数据流

```text
招标文件/附件/公司资料
  -> 上传与转换
  -> 文件清单
  -> 条款抽取
  -> 要求矩阵
  -> 风险清单
  -> 公司资料匹配
  -> 响应策略
  -> 分章节草稿
  -> 人工审查
  -> Word/Excel 交付物
```

## 6. 状态流

| 状态 | 存储位置 | 当前阶段 |
|---|---|---|
| 会话消息 | DeerFlow Thread State | 已有 |
| 上传文件 | `.deer-flow/threads/*/uploads` | 已有 |
| 中间产物 | `.deer-flow/threads/*/workspace` | 已有 |
| 最终交付物 | `.deer-flow/threads/*/outputs` | 已有 |
| 公司长期资料 | 待建 RAG/数据库 | 后续 |
| 项目级投标状态 | 待建 SQLite/PostgreSQL | 后续 |

## 7. 失败路径

| 失败点 | 降级策略 |
|---|---|
| PDF 扫描件无法解析 | 请求 OCR 或用户上传可复制文本版本 |
| 招标附件缺失 | 生成缺失清单，不继续承诺完整响应 |
| 公司资质无法匹配 | 标记为材料缺口，禁止编造 |
| 技术参数不满足 | 输出偏离项和替代方案 |
| 合同/报价条款高风险 | 标记人工法务/商务确认 |
| 模型输出不稳定 | 使用固定矩阵 schema 和复核 checklist |

## 8. 监控指标

第一阶段先记录人工可检查指标：

- P0 条款覆盖率
- 需求条款来源引用率
- 缺失材料数量
- 风险项数量和严重度
- 人工修改次数
- 单份标书处理耗时
- 生成内容被采纳比例

后续可接入 LangFuse 或 OpenTelemetry。

## 9. 里程碑

### M1：标书 Skill MVP

- 目标：让 DFlow 能按标书流程输出初步解读、要求矩阵、风险清单和大纲。
- 最小功能：新增 `bid-proposal-agent` Skill。
- 技术栈：DeerFlow Skill、Markdown。
- 验收标准：上传一份招标文件后，Agent 能生成结构化矩阵并标记 P0 风险。
- 可运行成果：当前 Skill 文件。
- 复盘问题：矩阵字段是否够用？风险分类是否贴合你的业务？

### M2：公司资料包

- 目标：让 Agent 能引用你的真实资质、案例和方案。
- 最小功能：整理 `company_profile/` 资料目录和材料索引表。
- 技术栈：Markdown/Excel + 文件检索。
- 验收标准：每个响应点都能映射到一个公司材料来源。
- 扩展方向：RAG 和版本管理。

### M3：RAG 知识库

- 目标：从公司资料中检索可复用证据。
- 最小功能：文档切分、Embedding、SQLite/pgvector 索引、引用返回。
- 技术栈：Python、SQLite 或 PostgreSQL、向量检索。
- 验收标准：检索结果有来源、版本和置信度。
- 风险：长期记忆污染、过期资质误用。

### M4：交付物导出

- 目标：输出 Word 标书草稿和 Excel 应答矩阵。
- 最小功能：Markdown -> DOCX，矩阵 -> XLSX。
- 技术栈：python-docx、openpyxl。
- 验收标准：格式稳定、章节完整、表格可编辑。

### M5：审查与评估

- 目标：降低废标和幻觉风险。
- 最小功能：P0 条款覆盖检查、未引用声明检查、法务/报价人工确认清单。
- 技术栈：规则检查 + LLM reviewer。
- 验收标准：每次生成都有审查报告。

## 10. ADR-001：以 Skill 作为标书 Agent 第一入口

### 背景

DFlow 以 DeerFlow 为基座，已有 LangGraph Agent Runtime、Skill 系统、文件上传、沙箱和前端对话能力。标书场景需要专业流程，但当前还没有公司资料库、评估集和交付模板。

### 决策

第一阶段不修改核心 Agent Runtime，不新增数据库，不重写前端。先新增 `bid-proposal-agent` public Skill，把标书流程固化为可加载的领域工作流。

### 备选方案

1. 直接修改主系统 prompt：更快但污染全局 Agent，后续同步 upstream 困难。
2. 新建独立标书 Agent 服务：边界清晰但初期工程量大。
3. 直接上 RAG：长期正确但初期资料治理不足，容易检索幻觉。

### 取舍

选择 Skill 的原因是低风险、可回滚、可测试、能复用 DeerFlow 现有能力。代价是第一阶段还不能自动管理长期公司资料，也不能保证 Word 格式交付。

### 风险

- Skill 触发依赖用户意图和描述质量。
- 若用户没有上传完整招标文件，矩阵可能不完整。
- 若没有公司资料，响应草稿只能给结构和占位，不能编造案例。

### 后续迁移路径

当 Skill 工作流稳定后，把“要求矩阵”“风险清单”“公司资料匹配”沉淀为独立工具和数据库表，再接入 RAG、导出模板和多 Agent 审查。
