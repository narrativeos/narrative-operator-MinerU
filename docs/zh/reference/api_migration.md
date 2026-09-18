# 接口迁移说明（3.x → 4.0）

面向下游应用与集成方。本文只讲**接口层**从 3.x 到 4.0 的破坏性变更和迁移步骤：V1 HTTP API、Python SDK、CLI、OpenAI 兼容 VLM 服务。安装、配置、模型与输出协议的通用迁移见[从 3.x 迁移到 4.0](migration_4.md)。

## 适用范围

- 你通过 **HTTP API**、**Python SDK** 或 **CLI** 调用 MinerU 解析文档，需要把 3.x 的调用方式改成 4.0。
- 不在本文范围：AMD 与国产加速卡等旧平台（继续限制 `mineru<4`，见[旧平台适配](../usage/compatibility.md)）。

## 1. 接口总览

| 能力 | 3.x | 4.0 |
| --- | --- | --- |
| 同步解析 | `POST /file_parse`（multipart，同步返回） | 无，统一为异步 V1 任务 |
| 异步解析 | `POST /tasks` + `GET /tasks/{id}` + `GET /tasks/{id}/result` | `POST /v1/parse/jobs` + `GET /v1/parse/jobs/{id}` + `GET /v1/files/{file_id}/content` |
| 上传 | multipart 直传 `/file_parse` | `POST /v1/uploads` → 上传字节 → `POST /v1/uploads/{id}/complete` |
| 健康检查 | `GET /health` | `GET /v1/health`（含 `features.sources`、`features.output_formats`） |
| 档位 | `backend`（`pipeline`/`vlm`/`hybrid`/`vlm-http-client`） | `tier`（`flash`/`basic`/`standard`/`advanced`） |
| Python 解析 | `from mineru.cli.common import do_parse` | `from mineru.parser import parse, MinerUApiParser` |
| CLI 解析 | `mineru -p in.pdf -o out` | `mineru-kit parse in.pdf -o out.md` |
| WebUI | `mineru-gradio` | `mineru-webui` / `mineru-kit webui` |
| 模型下载 | `mineru-models-download -m all` | `mineru-kit models download --tier standard` |
| VLM 服务 | 无独立 OpenAI 服务 | `mineru-kit vlm-server`（OpenAI 兼容，新增） |

一句话：**同步 `/file_parse` 没了，改成"上传 → 任务 → 轮询 → 下载"的异步 V1 流程；`backend` 换成 `tier`；`do_parse` 换成 `parse()` / `MinerUApiParser`。**

## 2. V1 HTTP API

### 2.1 Base URL 与鉴权

| | 3.x | 4.0 |
| --- | --- | --- |
| Base URL | `http://host:port` | 本地 `http://host:port`；官方 `https://mineru.net/api` |
| 路径前缀 | 无（`/file_parse`） | 所有端点带 `/v1` |
| 鉴权 | 无 | 服务以 `--api-key` 启动时，请求携带 `Authorization: Bearer $MINERU_API_KEY` |

### 2.2 请求流程对比

3.x 是同步一步：

```
POST /file_parse   (multipart: file, backend, ...)   →   200 + 结果
```

4.0 是异步四步：

```
1. POST /v1/uploads                 → 200 {id, upload_url, upload_method, upload_headers}
2. PUT  {upload_url}  (原始字节)     → 200
3. POST /v1/uploads/{id}/complete   → 200 {status: "completed", file: {id}}
4. POST /v1/parse/jobs              → 202 {job_id, status}
   GET  /v1/parse/jobs/{job_id}     → 轮询直到终态
   GET  /v1/files/{file_id}/content → 下载产物
```

### 2.3 完整 curl 示例

以本地服务 `http://127.0.0.1:8000` 为例（匿名访问省略鉴权头；生产环境请用[经过测试的完整脚本](../usage/http_api.md)）：

```bash
BASE=http://127.0.0.1:8000
PDF=document.pdf
BYTES=$(stat -f%z "$PDF")                 # macOS；Linux 用 stat -c%s
SHA=$(shasum -a 256 "$PDF" | cut -d' ' -f1)

# 1. 创建上传
UP=$(curl -fsS -X POST "$BASE/v1/uploads" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"$PDF\",\"bytes\":$BYTES,\"mime_type\":\"application/pdf\",\"purpose\":\"parse\",\"sha256sum\":\"$SHA\"}")
UPLOAD_ID=$(echo "$UP" | jq -r .id)
UPLOAD_URL=$(echo "$UP" | jq -r .upload_url)

# 2. 上传字节（status 为 pending 时）
curl -fsS -X PUT "$UPLOAD_URL" --data-binary @"$PDF" -o /dev/null

# 3. 完成上传，拿到 file_id
FILE_ID=$(curl -fsS -X POST "$BASE/v1/uploads/$UPLOAD_ID/complete" | jq -r .file.id)

# 4. 创建解析任务
JOB_ID=$(curl -fsS -X POST "$BASE/v1/parse/jobs" -H 'Content-Type: application/json' \
  -d "{\"files\":[{\"source\":{\"type\":\"file_id\",\"file_id\":\"$FILE_ID\"}}],\"tier\":\"standard\",\"output_formats\":[\"markdown\",\"middle_json\",\"zip\"]}" \
  | jq -r .job_id)

# 5. 轮询到终态（completed / partial / failed / canceled）
while :; do
  ST=$(curl -fsS "$BASE/v1/parse/jobs/$JOB_ID" | jq -r .status)
  case "$ST" in completed|partial|failed|canceled) break;; esac
  sleep 2
done

# 6. 下载产物（以 markdown 为例）
MD_ID=$(curl -fsS "$BASE/v1/parse/jobs/$JOB_ID" \
  | jq -r '.files[] | select(.status=="completed") | .output_files.markdown.file_id')
curl -fsSL "$BASE/v1/files/$MD_ID/content" -o document.md
```

> 生产环境请使用仓库中经过测试的 [`scripts/http_api_example.sh`](https://github.com/opendatalab/MinerU/blob/master/scripts/http_api_example.sh)，它包含超时、响应校验、有界轮询、`partial` 处理和跨源凭据隔离。

### 2.4 参数映射

| 3.x 字段 | 4.0 字段 | 说明 |
| --- | --- | --- |
| `backend` | `tier` | `pipeline`→`basic`；`vlm`/`vlm-http-client`→`advanced`；`hybrid`/`hybrid-auto-engine`→`standard`；`flash`→`flash` |
| `file`（multipart） | `files[].source` | `file_id` / `url` / `inline` / `local`（仅本地服务） |
| `page_range` | `files[].page_range` | `1-5,8,r3-r1`；`r1` 为末页，`all` 为全部 |
| `return_type` | `output_formats` | `markdown` / `middle_json` / `structured_content` / `zip` |
| `return_layout_pdf` | `output_formats` 中的 `layout_pdf` | 3.x 在 zip 内附带 `layout.pdf`；4.0 改为独立产物 `{文件名}.layout.pdf`（仅本地服务、仅 PDF 输入） |
| `lang` | （移除） | 4.0 自动识别语言 |
| `formula_enable` / `table_enable` | （移除） | 由 `tier` 决定 |
| 结果中的 `img_path` | `image_path` / `image_source.path` | 3.x 图片块顶层 `img_path` 键在 4.0 图片块 schema 中改名为 `image_path`（相对路径）或 `image_source.path`（绝对路径）；读取旧缓存/旧结果的代码需按新键取值 |

### 2.5 移除的端点与行为

- `POST /file_parse`、`POST /tasks`、`GET /tasks/{id}`、`GET /tasks/{id}/result`、`DELETE /tasks`、`DELETE /tasks/{id}`
- parse job SSE 事件流（`GET /v1/parse/jobs/{id}/events`）
- `POST /v1/parse/jobs` 的 `wait` 参数——V1 始终异步，创建即返回 `202`，客户端自行轮询
- 独立 `images` 输出格式——图片只通过 `zip` 产物返回
- 3.x 任务级细粒度进度字段（`progress_percent` / `current_page` / `total_pages` / `current_stage`）——4.0 默认只返回 job 级文件计数（`progress.completed/failed/total`）；本地服务的 PDF 文件在运行期间通过 `files[].progress`（`current_page` / `total_pages` / `stage`）提供页级进度，见 [parse-jobs 文档](../../next/api/parse-jobs.md)
- 3.x 结果图片块的顶层 `img_path` 键——4.0 图片块使用 `image_path` / `image_source.path`，见 2.4 参数映射

## 3. Python SDK

### 3.1 本地解析

3.x：

```python
from mineru.cli.common import do_parse
do_parse(output_dir="out", pdf_file_names=["a.pdf"], pdf_path="a.pdf", backend="hybrid")
```

4.0：

```python
from pathlib import Path
from mineru.parser import parse

result = parse("a.pdf", tier="standard", page_range="1-3")
Path("a.md").write_text(result.markdown(), encoding="utf-8")
Path("a.json").write_text(result.to_json(), encoding="utf-8")
```

### 3.2 连接自部署 V1 API

```python
from mineru.parser import MinerUApiParser

parser = MinerUApiParser(
    api_url="http://127.0.0.1:8000",   # /v1 之前的服务根地址
    api_key="",                          # 服务启用 --api-key 时必填
    tier="standard",
    include_images=True,
)
result = parser.parse("a.pdf", page_range="1-3")
print(result.markdown())
```

批量处理复用同一个 `MinerUApiParser` 实例，逐文件捕获异常（`failed`/`canceled` 终态与网络错误都会抛异常）。

### 3.3 结果对象 `ParseResult`

- `result.markdown()` / `result.to_json()` / `result.to_dict()`
- `ParseResult.from_json()` / `ParseResult.from_dict()` 用于恢复
- 旧结果里的 `pdf_info`、`_backend` 等字段**不是** 4.0 结构，不要当作模板；历史产物只在明确支持的兼容读取路径中使用，见[输出格式](output_files.md)。

## 4. CLI

| 3.x | 4.0 |
| --- | --- |
| `mineru -p in.pdf -o out` | `mineru-kit parse in.pdf -o out.md`（一次性）；`mineru parse in.pdf -o out.md`（文档库） |
| `mineru -p ./dir -o ./out` | `mineru-kit parse ./dir -o ./out --format zip` |
| `mineru-gradio` | `mineru-webui` / `mineru-kit webui` |
| `mineru-api` | `mineru-kit api-server` |
| `mineru-models-download -m all` | `mineru-kit models download --tier standard` |

`mineru-kit parse` 与 Python SDK 默认解析全部页；`mineru parse`（文档库）默认前 10 页。详见[命令行工具](../usage/cli_tools.md)。

## 5. OpenAI 兼容 VLM 服务（4.0 新增）

`mineru-kit vlm-server`（或 `mineru-openai-server`）提供 OpenAI 兼容的 VLM 推理接口：

```
GET  /v1/models
POST /v1/chat/completions
```

注意：这是 **VLM 推理**接口，**不是**文档解析 API，两者地址不可互换。文档解析 API 与 VLM 服务的关系见[迁移指南](migration_4.md)。

## 6. 迁移检查清单

- [ ] 把 `/file_parse`、`/tasks` 调用改成 V1"上传 → 任务 → 轮询 → 下载"
- [ ] `backend` 参数改成 `tier`
- [ ] 结果读取从 `pdf_info` 改成 `ParseResult` / V1 产物文件
- [ ] Python `do_parse` 改成 `parse()` / `MinerUApiParser`
- [ ] CLI `mineru -p` 改成 `mineru-kit parse`
- [ ] 用 `GET /v1/health` 的 `features.sources` / `features.output_formats` 做能力发现
- [ ] 先在独立环境验证，再迁移生产

## 7. 常见问题

- **`POST /file_parse` 返回 404？** 4.0 已移除该路由，改用 V1 任务流程。
- **能同步等待结果吗？** 不能。V1 始终异步，创建返回 `202`，客户端轮询 `GET /v1/parse/jobs/{id}`。
- **图片怎么拿？** 请求 `output_formats` 含 `zip`，从 zip 产物中读取图片 sidecar。
- **本地能跳过上传吗？** 可以。本地服务以 `--allow-local-source` 启动且 `features.sources` 含 `local` 时，用 `{"type":"local","path":"..."}` 直接引用本地路径。
- **`tier` 和 `backend` 怎么对应？** 见上文「2.4 参数映射」。

