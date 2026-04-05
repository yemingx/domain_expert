# 科研文献调研技能

## 功能描述
通用科研文献调研工具，支持任意主题的PubMed文献自动检索、智能分析和多格式报告生成。原NIPD文献调研技能已泛化为通用科研调研工具。

## 核心目标
- 自动检索PubMed最新文献（支持任意主题）
- 智能筛选和去重，保留高价值核心文献
- 多维度技术和行业分析
- 生成标准化报告（Markdown/Word/PPT/HTML）
- 构建本地文献知识库，支持历史对比

## 适用场景
- 每周/每月定期领域文献跟踪
- 项目立项前的技术调研
- 行业趋势分析和投资研究
- 临床决策参考资料生成
- 学术研究文献综述

## 前置要求
1. Python 3.8+
2. Node.js + Puppeteer（用于HTML-PPT转PDF）
3. 依赖库：
   ```bash
   pip install requests pyyaml pandas numpy openpyxl python-dotenv pymupdf weasyprint beautifulsoup4 lxml
   ```
4. chrome-headless-shell：由Puppeteer自动下载缓存至`/root/.cache/puppeteer/`，不占用工作区Gitee配额
5. 网络访问权限（PubMed、学术期刊网站）

## 数据配置

### 期刊影响因子数据库
- **数据来源**：2024JCR完整版（Clarivate官方数据）
- **数据文件**：
  - `data/2024JCR完整版.xlsx` - 原始Excel文件（22,249条记录）
  - `data/journal_if_2024.json` - 转换后的JSON格式（22,188条记录）
- **更新方式**：替换Excel文件后自动重新生成JSON
- **匹配逻辑**：精确匹配 → 大小写不敏感匹配 → 模糊匹配

## 使用方法

### 命令行参数
```bash
# 基础用法（使用默认配置）
python scripts/fetch_papers.py

# 指定主题和时间范围
python scripts/fetch_papers.py --topic "CRISPR" --topic-name "基因编辑" --days 30

# 指定最大文献数量
python scripts/fetch_papers.py --topic "AI Medicine" --topic-name "AI医学" --days 60 --max-papers 10

# 使用配置文件
python scripts/fetch_papers.py --config config/my_topic.json
```

### 参数说明
| 参数 | 说明 | 示例 |
|------|------|------|
| `--topic` | PubMed检索关键词 | `"CRISPR"`, `"NIPD"` |
| `--topic-name` | 主题中文名称（用于报告标题） | `"基因编辑"`, `"无创产前诊断"` |
| `--days` | 检索时间范围（天） | `7`, `30`, `60` |
| `--max-papers` | 最大文献数量 | `5`, `10`, `20` |
| `--config` | 配置文件路径 | `config/nipd.json` |

### 配置文件示例（config/example.json）
```json
{
  "topic": "NIPD",
  "topic_name": "无创产前诊断",
  "days": 60,
  "max_papers": 5,
  "queries": {
    "NIPD": "((\"non-invasive prenatal diagnosis\"[Title/Abstract] OR ...))",
    "CRISPR": "(CRISPR[Title/Abstract] OR \"gene editing\"[Title/Abstract])"
  }
}
```

### 使用示例

#### 示例1：类器官文献调研（完整流程：调研→打包→发送→同步）
```bash
# 步骤1：运行文献调研
python scripts/fetch_papers.py \
  --topic "Organoid" \
  --topic-name "类器官" \
  --days 90 \
  --max-papers 5

# 步骤2：自动打包、同步Gitee、发送钉钉
python scripts/auto_package_send_sync.py "类器官" "Organoid" "90" "5"
```

#### 示例2：NIPD文献调研（默认）
```bash
python scripts/fetch_papers.py \
  --topic "NIPD" \
  --topic-name "无创产前诊断" \
  --days 60 \
  --max-papers 5
```

#### 示例3：CRISPR基因编辑文献调研
```bash
python scripts/fetch_papers.py \
  --topic "CRISPR" \
  --topic-name "基因编辑" \
  --days 30 \
  --max-papers 10
```

#### 示例4：AI医学文献调研
```bash
python scripts/fetch_papers.py \
  --topic "artificial intelligence" \
  --topic-name "AI医学" \
  --days 90 \
  --max-papers 8
```

### 分步执行
1. **仅检索文献**：
   ```bash
   python scripts/fetch_papers.py --days 7 --output data/papers.json
   ```
2. **文献筛选和分析**：
   ```bash
   python scripts/analyze_papers.py --input data/papers.json --output data/analyzed_papers.json
   ```
3. **下载PDF全文**：
   ```bash
   python scripts/download_pdfs.py --input data/analyzed_papers.json --output pdfs/
   ```
4. **生成报告**：
   ```bash
   python scripts/generate_report.py --input data/analyzed_papers.json --output reports/
   ```

## 功能模块

### 1. 文献检索模块
- **数据源**：PubMed
- **检索策略**：
  - 时间范围：可配置（默认最近7天）
  - 关键词组合：中英文关键词自动匹配
  - 筛选规则：排除综述、病例报告等（可配置）
  - 排序方式：按发表时间倒序
- **输出**：文献元数据（标题、DOI、摘要、期刊、发表日期、作者、原文链接）

### 2. 文献筛选模块
- **去重**：基于DOI唯一标识去重
- **相关性过滤**：AI语义匹配，排除无关文献
- **优先级排序**：综合期刊影响因子、引用数、相关性排序

### 3. PDF下载模块
- **多渠道支持**：
  - Springer系列：https://link.springer.com/content/pdf/{doi}.pdf
  - Nature系列：https://www.nature.com/articles/{doi后缀}.pdf
  - ScienceDirect：https://www.sciencedirect.com/science/article/pii/{doi_clean}/pdfft
  - Frontiers：https://www.frontiersin.org/articles/{doi}/pdf
  - BMJ系列：https://casereports.bmj.com/content/bmjcr/{doi后缀}.full.pdf
  - 通用DOI解析：https://doi.org/{doi}
- **失败处理**：标注失败原因（需权限、无开放获取等）

### 4. 多维度分析模块
#### 单篇文献分析：
- 技术路线：核心技术原理、实验方法、检测流程
- 技术优势和不足：性能指标（灵敏度、特异性、PPV）、局限性
- 技术壁垒：样本处理、算法、数据库、监管、专利难点
- 落地可行性：临床验证阶段、成本、政策支持、市场接受度
- 泛化能力：疾病谱扩展、人群适用性、跨场景迁移潜力

#### 整体行业分析：
- 技术发展趋势：主流技术路线演变、新兴技术突破
- 市场格局：主要玩家、市场规模、渗透率、价格区间
- 政策环境：医保政策、监管要求、行业规范
- 未来展望：发展方向、待解决问题、投资机会

### 5. 报告生成模块
#### 报告结构：
1. **封面**：报告名称、生成时间、文献范围、数量
2. **单篇文献分析**：5维度表格呈现，带可点击DOI链接
3. **总体分析**：行业趋势、共性优势/不足、壁垒、落地前景
4. **发展建议**：技术、临床、监管、市场层面建议
5. **参考文献**：所有文献来源、行业指南、公开数据来源

#### 输出格式（六种格式并行生成）：
- **Markdown格式**：便于编辑和二次修改
- **Word格式**：左右分栏对照（英文/中文）+ 深度分析6维度
- **PPT格式**：华大基因蓝色科技版模板
  - 首页标题左半部分，深蓝渐变背景
  - 完整标题无省略号，动态字体调整
  - 标题页和摘要页合并，左右分栏显示
  - 深度分析6维度卡片网格，内容完整显示
  - 适合汇报使用
- **HTML格式-阅读版**（2026-03-13新增）：精美静态网页报告
  - 蓝白渐变主题（#003366 → #0066cc）
  - 响应式布局，支持移动端
  - 统计概览卡片（文献数、天数、维度、完整度）
  - 左右分栏摘要（英文/中文）
  - 6维度分析卡片网格（3列布局）
  - 纯HTML+CSS，单文件即可查看
- **HTML格式-PPT版**（2026-03-13新增，推荐）⭐
  - 16:9宽屏比例（56.25vw），适合投影展示
  - 蓝紫渐变主题（#003366 → #0066cc → #764ba2）
  - 无动画效果，静态展示
  - 完整内容显示，无省略号
  - 页面结构：封面→概览→文献（每篇2页）→总结→结束
  - 适合投影汇报和打印
- **PDF格式（从HTML-PPT自动转换）**（2026-03-16新增）📄
  - 自动转换：HTML-PPT生成后自动使用Puppeteer转换
  - 精确尺寸：**1920×1080px**（16:9全高清）
  - 每页对应一张PPT幻灯片，可直接打印或投影
  - chrome-headless-shell缓存至系统目录，不占用Gitee配额

## 配置说明
```yaml
# 检索配置
search:
  days: 7                  # 默认检索最近7天
  keywords:
    english: ["NIPD", "noninvasive prenatal diagnosis", "cffDNA", "single gene disorder", "monogenic"]
    chinese: ["无创单病", "胎儿游离DNA", "产前诊断"]
  exclude_types: ["Review", "Case Report"]  # 排除的文献类型

# 筛选配置
filter:
  min_relevance_score: 0.7  # 最低相关性阈值
  max_papers: 50            # 最多保留文献数量

# 下载配置
download:
  enabled: true             # 是否自动下载PDF
  save_path: "./pdfs"       # PDF保存路径
  timeout: 30               # 下载超时时间（秒）

# 分析配置
analysis:
  enable_industry_analysis: true  # 是否启用行业分析
  impact_factor_weight: 0.3       # 影响因子权重
  citation_weight: 0.2            # 引用数权重
  relevance_weight: 0.5           # 相关性权重

# 输出配置
output:
  markdown_path: "./reports/markdown"
  pdf_path: "./reports/pdf"
  include_cover: true
  include_toc: true
  page_size: "A4"
  # PPT配置
  ppt:
    theme: "medical"  # 医疗主题
    background: "light_blue_gradient"  # 浅蓝色渐变背景
    rounded_cards: true  # 圆角卡片
    shadow_effect: true  # 阴影效果
    auto_font_size: true  # 自动调整字号
    auto_wrap: true  # 自动换行
    line_spacing: 1.2  # 行间距
```

## 定期执行配置
使用cron定期执行：
```bash
# 每周一早上8点生成上周报告
0 8 * * 1 cd /path/to/skill && python scripts/run_full_pipeline.py --days 7 >> /var/log/nipd_research.log 2>&1

# 每月1号早上9点生成上月报告
0 9 1 * * cd /path/to/skill && python scripts/run_full_pipeline.py --days 30 >> /var/log/nipd_research.log 2>&1
```

## 输出格式说明

### 默认输出文件（6种格式）
| 格式 | 文件名示例 | 用途 |
|------|-----------|------|
| **Markdown** | `主题最新文献报告_日期.md` | 编辑、阅读、版本控制 |
| **Word** | `主题最新文献报告_日期.docx` | 左右分栏对照（英文/中文） |
| **HTML阅读版** | `主题文献调研报告_日期.html` | 浏览器阅读（蓝白渐变主题） |
| **HTML-PPT版** | `主题文献调研报告_日期_ppt.html` | 投影展示（16:9宽屏）⭐推荐 |
| **PDF（HTML-PPT转换）** | `主题文献调研报告_日期_ppt.pdf` | 可直接打印/投影的幻灯片PDF |
| **JSON数据** | `papers_complete.json` | 结构化数据，供二次开发 |

### 自动打包
运行完成后，手动打包发送：
- **完整包格式**: `主题文献调研报告_日期_完整包.zip`
  - 包含所有格式的报告文件
  - 便于存档和分享
  - 默认使用zip格式（用户指定）

### 自动同步Gitee
- 自动将 `result/主题文献调研/` 目录同步到Gitee仓库
- 提交信息：`[主题] 自动同步报告 日期时间`
- 确保数据备份，支持历史版本追溯

### 自动发送钉钉
- 发送文字通知：包含检索信息、文件清单、生成时间
- 发送完整包：`.tar.gz` 文件包含所有报告
- 目标群聊：配置在 `scripts/auto_package_send_sync.py` 中的 `DINGTALK_CHAT_ID`

## Word报告自动修复机制（2026-03-15新增）

### 功能说明
Word报告生成时自动检测内容完整性，发现问题时自动修复：

**检查项：**
| 检查项 | 标准 | 自动修复动作 |
|--------|------|-------------|
| 标题 | 不为空，长度≥10字符 | 标记警告 |
| 英文摘要 | 不为空，长度≥200字符，无省略号 | 从PubMed重新获取 |
| 中文翻译 | 不为空，无省略号，长度≥英文30% | 使用大模型重新翻译 |
| 6维度分析 | 不为空，长度≥20字符 | 重新调用分析API |

**修复流程：**
```
检查完整性 → 发现问题 → 自动修复 → 重新检查 → 生成Word
                ↓
         重新获取摘要（PubMed API）
         重新翻译中文
         重新6维度分析
         仍有未修复 → 继续生成（不阻止）
```

**配置参数：**
```python
# 在 generate_word_with_validation.py 中
auto_fix=True  # 启用自动修复（默认开启）
```

**使用示例：**
```bash
# 运行调研（自动修复已默认启用）
python scripts/fetch_papers.py --topic "virtual cell" --topic-name "虚拟细胞" --days 30

# 输出示例：
# 🔍 严格检查Word报告内容完整性
# ⚠️ 发现 3/4 篇文献内容不完整
# 🔧 开始自动修复不完整的文献...
# ✓ 重新获取英文摘要: 1332字符
# 🔤 重新翻译摘要...
# ✓ 中文翻译: 394字符
# ✅ 自动修复完成，修复了 3 篇文献
# 📝 Word报告已生成
```

## 输出示例
- 报告文件名：`类器官最新文献报告_2025-12-14至2026-03-14.md`
- Word文件名：`类器官最新文献报告_2025-12-14至2026-03-14.docx`
- PPT文件名：`类器官最新文献报告_2025-12-14至2026-03-14.pptx`
- 完整包：`类器官文献调研报告_2026-03-14_完整包.tar.gz`
- 文献库：`data/主题_literature_db.json`（历史所有分析过的文献）

## 迭代扩展
- 支持接入CNKI、万方等中文数据库
- 增加AI深度解读功能
- 支持邮件/企业微信自动推送报告
- 支持多领域扩展（不限于NIPD）

## 目录结构
```
literature-research/
├── SKILL.md                    # 本技能说明文件
├── README.md                   # 使用指南
├── requirements.txt            # Python依赖
├── .env                        # API配置（火山引擎/阿里云）
├── config/
│   ├── config.example.yaml     # 配置模板
│   └── config.yaml             # 用户配置
├── scripts/
│   ├── fetch_papers.py         # 文献检索主脚本 ⭐核心
│   ├── auto_package_send_sync.py # 自动打包+发送+同步 ⭐推荐
│   ├── analyze_content.py      # 6维度深度分析
│   ├── generate_report.py      # Word报告生成
│   ├── generate_ppt.py         # PPT报告生成
│   ├── generate_ppt_optimized.py # PPT优化版
│   ├── generate_html.py        # HTML报告生成
│   ├── utils.py                # 工具函数（翻译、IF查询）
│   └── archive/                # 归档脚本
├── templates/
│   ├── report_template.md      # Markdown报告模板
│   └── ppt_template.pptx       # PPT模板（华大基因蓝色科技版）
├── data/
│   ├── 2024JCR完整版.xlsx      # 期刊影响因子原始数据
│   └── journal_if_2024.json    # 转换后的IF数据库
└── result/                     # 输出目录（自动同步Gitee）
    └── 主题文献调研/
        └── YYYY-MM-DD/
            ├── 主题最新文献报告_日期.md
            ├── 主题最新文献报告_日期.docx
            ├── 主题最新文献报告_日期.pptx
            ├── 主题文献调研报告_日期.html
            ├── 主题文献调研报告_日期_ppt.html
            ├── papers_complete.json
            └── 主题文献调研报告_日期_完整包.tar.gz
```
