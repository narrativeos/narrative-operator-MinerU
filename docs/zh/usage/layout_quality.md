# 版面量化评分工具 (AHP-熵权TOPSIS)

针对 MinerU 解析引擎输出的版面量化指标，采用"自下而上提取，自上而下评估"的双层架构：

- **[逐页层]** 每页独立计算 12 指标局部特征向量 (Page-level)
- **[全书层]** 噪声页剔除 → 均值/方差聚合 → 全书版面指纹 → TOPSIS 综合评级 (Book-level)，
  同时进行跨页 (Spread) 对称性分析与 3σ 异常页检测，输出《全书排版一致性质检报告》

可用于：

1. 图书版面质量分级与出版社/设计师风格指纹识别
2. 全书排版一致性 QA 质检（捕捉外包交接、风格漂移的异常页）
3. VLM 训练数据的质量分级与筛选

## 方法流程

| 步骤 | 方法 | 说明 |
| --- | --- | --- |
| Step 0 | 逐页→全书聚合 | 噪声页剔除（空白页/版权页）+ 均值/方差聚合生成版面指纹 + 跨页对称性分析 + 3σ 异常页检测 |
| Step 1 | AHP 层次分析法 | 主观权重（专家经验，一致性检验要求 CR < 0.1） |
| Step 2 | 熵权法 | 客观权重（数据差异越大，权重越高） |
| Step 3 | 线性组合 | 组合权重 `W = alpha*W_sub + (1-alpha)*W_obj` |
| Step 4 | TOPSIS 逼近理想解 | 综合贴近度 `C = D- / (D+ + D-)`, 越接近 1 越好 |

## 指标体系与数据来源

4 个准则层 × 12 个指标（`+` 为正向越大越好，`-` 为负向越小越好）。
指标由 `scripts/layout_quality/extractor.py` 直接从 MinerU 的
`*_model.json`（布局模型原始检测）与 `*_middle.json`（后处理结果）计算，**无需 Ground Truth**：

| 指标 | 方向 | 计算口径 |
| --- | --- | --- |
| C1 重叠面积比 | + | 后处理块与原始检测框的重叠面积 / 后处理块面积（后处理不凭空造框） |
| C2 曼哈顿角点对齐误差 | - | 块边到对齐簇（页边距/栏边界，1D 聚类）的平均曼哈顿偏离 (pt) |
| C3 最小权重边覆盖匹配相似度 | + | 块边被其他共线块边覆盖的平均长度比例 |
| C4 平均交并比 mIoU | + | 原始检测与后处理匹配框对的平均 IoU（自一致性，非对 GT 精度） |
| C5 边界精度 | + | 1 - 匹配框对平均归一化边界位移 |
| C6 像素准确率 | + | 匹配框对交集/并集面积的聚合比值 |
| C7 空间得分 | + | 左缘规整度 + 左右边距均衡 + 垂直间距规律性 |
| C8 锚点得分 | + | 锚点关联满足率（image↔caption、paragraph_title→正文） |
| C9 格式得分 | + | span 高度一致性 + 行距规律性 + 行左缘对齐一致性 |
| C10 上下文得分 | + | 阅读顺序 (index) 与空间顺序的一致率 |
| C11 统一页面分区评分 | + | 正文类块面积落入估计正文区（y 方向 5%~95% 分位带）的比例 |
| C12 块级语义纯度 | + | 块类型-内容一致性（文本块结合 OCR 置信度、表格块含 table_body 等） |

> **口径说明**：C4~C6 原定义为"对 GT 的检测精度"，本工具无 GT，改为
> "原始检测 ↔ 后处理结果"的自一致性口径，衡量的是管线稳定性而非绝对精度；
> C7~C10 原预期来自外部 VLM 评分管线，本工具用 MinerU 结构数据做启发式代理。
> 若你有外部评测管线产出的指标，可用 CSV 模式直接覆盖。

辅助字段（供去噪/跨页对称分析）：版面覆盖率、文本块数、视觉重心（bbox 面积加权）、页宽。

## 使用方式

在仓库根目录执行（依赖 `numpy` + `pandas`）：

```bash
# 1. 单本书质检 (主要用法): 输出 <目录>/layout_quality.csv (与 middle.json/model.json 同目录)
python -m scripts.layout_quality.cli output/<uuid>/demo3/hybrid_auto

# 2. 多本书对比 (至少 2 本): 每本书各自输出 layout_quality.csv,
#    TOPSIS 综合评分结果写入 --out (默认 ./layout_quality)
python -m scripts.layout_quality.cli <目录1> <目录2> ...

# 3. 外部逐页指标 CSV (19 列: 书名,页码,版面覆盖率,文本块数,重心x,重心y,页宽,C1~C12)
python -m scripts.layout_quality.cli --csv 你的minerU逐页指标.csv

# 4. 书级聚合指标 CSV (13 列: 样本名 + C1~C12)
python -m scripts.layout_quality.cli --book-csv 你的书级指标.csv

# 5. 内置模拟演示 (含自检)
python -m scripts.layout_quality.cli --demo
```

常用参数：

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--out` | `./layout_quality` | 综合评分结果输出目录（目录模式下逐页明细恒写入 `<目录>/layout_quality.csv`，不受此参数影响） |
| `--alpha` | 0.5 | 主观(AHP)权重占比，0~1 |
| `--n-sigma` | 3.0 | 异常页检测 σ 阈值 |
| `--name` | 父目录名 | 书名（仅单目录模式） |

## FastAPI 接口

`mineru-api` 服务（`mineru/cli/fast_api.py`）内置两个版面质量评分端点，
将逐页指标、全书绝对评分与 QA 报告以 JSON 形式返回（只读计算，不写文件）：

| 端点 | 说明 |
| --- | --- |
| `GET /layout_quality?path=<hybrid_auto 目录>` | 对任意 MinerU `hybrid_auto` 输出目录评分 |
| `GET /tasks/{task_id}/layout_quality` | 按解析任务 ID 自动定位输出目录并评分 |

两个端点均支持可选参数 `n_sigma`（默认 3.0，异常页检测 σ 阈值）。

```bash
# 1. 对指定目录评分
curl "http://127.0.0.1:8401/layout_quality?path=/path/to/hybrid_auto"

# 2. 按任务 ID 评分
curl "http://127.0.0.1:8401/tasks/<task_id>/layout_quality"
```

返回示例（节选）：

```json
{
  "book": "page_2",
  "total_pages": 4,
  "valid_pages": 4,
  "dropped_pages": [],
  "score": {
    "value": 0.8802,
    "percent": 88.02,
    "grade": "T1(国际一流)",
    "stability_index": 0.87,
    "spread_symmetry": 0.9637,
    "outlier_count": 0,
    "sub_scores": {"C1重叠面积比": 0.9978}
  },
  "fingerprint": {"C1重叠面积比": {"mean": 0.998, "std": 0.0003}},
  "outliers": [],
  "pages": [
    {"页码": 1, "是否有效": "是", "版面覆盖率": 0.5716, "文本块数": 12, "C1重叠面积比": 0.9986}
  ],
  "qa_report": "全书排版一致性质检报告全文 ..."
}
```

### 解析请求选项：`return_layout_quality`

`POST /file_parse`（同步）与 `POST /tasks`（异步）均支持表单选项
`return_layout_quality`（默认 `false`）。开启后，解析完成时自动计算整书版面质量评分，
无需再单独调用上面的 GET 端点：

- **JSON 响应**：顶层新增 `layout_quality` 字段，内容同 `GET /layout_quality` 的单书结果
  （多文件任务为 `{"books": [...]}`）；
- **ZIP 响应**（`response_format_zip=true`）：每本书的 `hybrid_auto/` 目录内新增
  `layout_quality.json`（与 `*_middle.json` / `*_model.json` 同目录，每本书一份）；
- 开启该选项会**强制落盘** `*_middle.json` / `*_model.json`（评分原料），
  但不改变响应内容——`return_middle_json` / `return_model_output` 仍单独控制是否随响应返回；
- 评分为 best-effort：模块不可用或数据缺失时解析结果正常返回，只是没有 `layout_quality` 字段；
- 已评分的任务再次调用 `GET /tasks/{task_id}/layout_quality`（默认 `n_sigma`）时直接复用缓存。

```bash
# 同步解析并返回评分
curl -X POST "http://127.0.0.1:8401/file_parse" \
  -F "files=@book.pdf" -F "backend=hybrid-engine" \
  -F "return_layout_quality=true"

# 异步解析, 结果 (JSON 或 ZIP) 中自动包含评分
curl -X POST "http://127.0.0.1:8401/tasks" \
  -F "files=@book.pdf" -F "backend=hybrid-engine" \
  -F "return_layout_quality=true"
```

> 说明：
> - `sub_scores` / `fingerprint` / `pages` 均含全部 12 个指标（C1~C12），示例仅节选。
> - 任务端点要求解析请求开启 `return_middle_json` 与 `return_model_output`
>   （或 `return_layout_quality`），否则输出目录中没有
>   `*_middle.json` / `*_model.json`，返回 404；任务未完成时返回 202。
> - `scripts.layout_quality` 是仓库内开发工具包，若运行环境无法导入
>   （如仅安装了 `mineru` 包的生产镜像），端点返回 501。
> - 多文件任务返回 `{"task_id": ..., "books": [...]}`；单文件任务直接返回单书结果（含 `task_id` 字段）。

## 输出

| 文件 | 内容 |
| --- | --- |
| `<hybrid_auto>/layout_quality.csv` | 逐页指标明细（19 列：页码、是否有效、版面覆盖率、文本块数、C1~C12），与 `middle.json`/`model.json` 同目录，每本书一个 |
| `<hybrid_auto>/layout_quality_score.csv` | 全书版面质量综合评分（单行：综合评分/百分制/档位/稳定性/对称度/异常页数/C1~C12 子分），绝对分，单本书即可计算 |
| `版面量化综合评分结果.csv` | （多本书模式）每本书的综合评分（绝对）、综合贴近度（相对）、名次、档位、排版稳定性指数、跨页对称度、异常页数等，写入 `--out` |
| `逐页版面指标明细.csv` | （CSV 输入模式）合并逐页明细，含书名列，写入 `--out` |

> 全书排版一致性质检报告（版面指纹均值±标准差、噪声页剔除清单、3σ 异常页清单）与全书综合评分打印到 stdout，不落盘。
> 单本书目录模式只产生 `<hybrid_auto>/` 下前两个文件，不产生评分 CSV（TOPSIS 排序需至少 2 本）。

## 全书综合评分（绝对分）

```
综合评分 = Σⱼ wⱼ · sⱼ      (wⱼ = AHP 主观权重, sⱼ ∈ [0,1] 归一化子分)
```

- **归一化**：C1、C3~C12 本身在 [0,1]，直接截断；C2 角点对齐误差 (pt) 用 `1/(1+x/10)` 衰减（10pt≈3.5mm 误差记半分）
- **权重**：AHP 主观权重（专家判断矩阵）。熵权需跨书方差、单书不可用，故绝对分单/多书模式统一用 AHP 权重，口径一致
- **定档**：T1≥0.75 / T2≥0.50 / T3≥0.25 / T4
- 排版稳定性指数、跨页对称度仅作辅助列展示，不进总分
- 与 TOPSIS `综合贴近度`（相对分，批内排名）的区别：绝对分不依赖其他书，单本书独立可算

## 模块结构

```
scripts/layout_quality/
├── indicators.py    # 指标体系定义 (4 准则层 x 12 指标)
├── ahp.py           # AHP 主观赋权 (特征向量法 + 一致性检验 + 判断矩阵)
├── entropy.py       # 熵权法客观赋权
├── topsis.py        # TOPSIS 逼近理想解综合排序 + 档位
├── aggregator.py    # BookAggregator: 去噪/聚合/跨页对称/3σ/质检报告
├── extractor.py     # model.json + middle.json -> 逐页 12 指标 + 辅助字段
├── scoring.py       # 全书版面质量综合评分 (绝对分): 归一化 + AHP 加权
├── service.py       # API 服务层: 纯计算入口 (供 FastAPI 端点, 无副作用)
├── pipeline.py      # 组合赋权与 TOPSIS 评估主流程
├── demo.py          # 内置模拟演示与自检
└── cli.py           # 命令行入口
```

单元测试：`tests/unittest/test_layout_quality.py`

```bash
python -m unittest tests.unittest.test_layout_quality -v
```
