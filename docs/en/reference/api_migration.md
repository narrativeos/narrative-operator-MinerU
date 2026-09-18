# Interface Migration Guide (3.x → 4.0)

For downstream applications and integrators. This guide covers only the **interface layer** breaking changes and migration steps from 3.x to 4.0: the V1 HTTP API, the Python SDK, the CLI, and the OpenAI-compatible VLM server. For the general migration (installation, configuration, models, and output protocol), see [Migrating from 3.x to 4.0](migration_4.md).

## Scope

- You call MinerU to parse documents via the **HTTP API**, the **Python SDK**, or the **CLI**, and need to move your 3.x calls to 4.0.
- Out of scope: legacy platforms such as AMD and domestic accelerator cards (still pinned to `mineru<4`; see [Legacy Platforms](../usage/compatibility.md)).

## 1. Interface Overview

| Capability | 3.x | 4.0 |
| --- | --- | --- |
| Sync parse | `POST /file_parse` (multipart, synchronous) | Removed; unified as an async V1 job |
| Async parse | `POST /tasks` + `GET /tasks/{id}` + `GET /tasks/{id}/result` | `POST /v1/parse/jobs` + `GET /v1/parse/jobs/{id}` + `GET /v1/files/{file_id}/content` |
| Upload | multipart directly to `/file_parse` | `POST /v1/uploads` → upload bytes → `POST /v1/uploads/{id}/complete` |
| Health check | `GET /health` | `GET /v1/health` (includes `features.sources`, `features.output_formats`) |
| Quality | `backend` (`pipeline`/`vlm`/`hybrid`/`vlm-http-client`) | `tier` (`flash`/`basic`/`standard`/`advanced`) |
| Python parse | `from mineru.cli.common import do_parse` | `from mineru.parser import parse, MinerUApiParser` |
| CLI parse | `mineru -p in.pdf -o out` | `mineru-kit parse in.pdf -o out.md` |
| WebUI | `mineru-gradio` | `mineru-webui` / `mineru-kit webui` |
| Model download | `mineru-models-download -m all` | `mineru-kit models download --tier standard` |
| VLM server | No standalone OpenAI service | `mineru-kit vlm-server` (OpenAI-compatible, new) |

In one line: **the synchronous `/file_parse` is gone, replaced by the async V1 flow "upload → job → poll → download"; `backend` becomes `tier`; `do_parse` becomes `parse()` / `MinerUApiParser`.**

## 2. V1 HTTP API

### 2.1 Base URL and Auth

| | 3.x | 4.0 |
| --- | --- | --- |
| Base URL | `http://host:port` | Local `http://host:port`; official `https://mineru.net/api` |
| Path prefix | None (`/file_parse`) | All endpoints are under `/v1` |
| Auth | None | When the service starts with `--api-key`, send `Authorization: Bearer $MINERU_API_KEY` |

### 2.2 Request Flow Comparison

3.x is a single synchronous step:

```
POST /file_parse   (multipart: file, backend, ...)   →   200 + result
```

4.0 is four asynchronous steps:

```
1. POST /v1/uploads                 → 200 {id, upload_url, upload_method, upload_headers}
2. PUT  {upload_url}  (raw bytes)   → 200
3. POST /v1/uploads/{id}/complete   → 200 {status: "completed", file: {id}}
4. POST /v1/parse/jobs              → 202 {job_id, status}
   GET  /v1/parse/jobs/{job_id}     → poll until a terminal state
   GET  /v1/files/{file_id}/content → download the artifacts
```

### 2.3 Full curl Example

Against a local service at `http://127.0.0.1:8000` (anonymous access omits the auth header; for production use the [tested full script](../usage/http_api.md)):

```bash
BASE=http://127.0.0.1:8000
PDF=document.pdf
BYTES=$(stat -f%z "$PDF")                 # macOS; on Linux use stat -c%s
SHA=$(shasum -a 256 "$PDF" | cut -d' ' -f1)

# 1. Create the upload
UP=$(curl -fsS -X POST "$BASE/v1/uploads" -H 'Content-Type: application/json' \
  -d "{\"filename\":\"$PDF\",\"bytes\":$BYTES,\"mime_type\":\"application/pdf\",\"purpose\":\"parse\",\"sha256sum\":\"$SHA\"}")
UPLOAD_ID=$(echo "$UP" | jq -r .id)
UPLOAD_URL=$(echo "$UP" | jq -r .upload_url)

# 2. Upload the bytes (when status is pending)
curl -fsS -X PUT "$UPLOAD_URL" --data-binary @"$PDF" -o /dev/null

# 3. Complete the upload to get the file_id
FILE_ID=$(curl -fsS -X POST "$BASE/v1/uploads/$UPLOAD_ID/complete" | jq -r .file.id)

# 4. Create the parse job
JOB_ID=$(curl -fsS -X POST "$BASE/v1/parse/jobs" -H 'Content-Type: application/json' \
  -d "{\"files\":[{\"source\":{\"type\":\"file_id\",\"file_id\":\"$FILE_ID\"}}],\"tier\":\"standard\",\"output_formats\":[\"markdown\",\"middle_json\",\"zip\"]}" \
  | jq -r .job_id)

# 5. Poll until a terminal state (completed / partial / failed / canceled)
while :; do
  ST=$(curl -fsS "$BASE/v1/parse/jobs/$JOB_ID" | jq -r .status)
  case "$ST" in completed|partial|failed|canceled) break;; esac
  sleep 2
done

# 6. Download an artifact (markdown shown)
MD_ID=$(curl -fsS "$BASE/v1/parse/jobs/$JOB_ID" \
  | jq -r '.files[] | select(.status=="completed") | .output_files.markdown.file_id')
curl -fsSL "$BASE/v1/files/$MD_ID/content" -o document.md
```

> For production, use the tested [`scripts/http_api_example.sh`](https://github.com/opendatalab/MinerU/blob/master/scripts/http_api_example.sh) in the repo, which includes timeouts, response validation, bounded polling, `partial` handling, and cross-origin credential isolation.

### 2.4 Parameter Mapping

| 3.x field | 4.0 field | Notes |
| --- | --- | --- |
| `backend` | `tier` | `pipeline`→`basic`; `vlm`/`vlm-http-client`→`advanced`; `hybrid`/`hybrid-auto-engine`→`standard`; `flash`→`flash` |
| `file` (multipart) | `files[].source` | `file_id` / `url` / `inline` / `local` (local server only) |
| `page_range` | `files[].page_range` | `1-5,8,r3-r1`; `r1` is the last page, `all` is every page |
| `return_type` | `output_formats` | `markdown` / `middle_json` / `structured_content` / `zip` |
| `lang` | (removed) | 4.0 detects the language automatically |
| `formula_enable` / `table_enable` | (removed) | Determined by `tier` |

### 2.5 Removed Endpoints and Behaviors

- `POST /file_parse`, `POST /tasks`, `GET /tasks/{id}`, `GET /tasks/{id}/result`, `DELETE /tasks`, `DELETE /tasks/{id}`
- The parse job SSE event stream (`GET /v1/parse/jobs/{id}/events`)
- The `wait` parameter on `POST /v1/parse/jobs` — V1 is always async; creation returns `202` and the client polls
- The standalone `images` output format — images are returned only through the `zip` artifact


## 3. Python SDK

### 3.1 Local Parsing

3.x:

```python
from mineru.cli.common import do_parse
do_parse(output_dir="out", pdf_file_names=["a.pdf"], pdf_path="a.pdf", backend="hybrid")
```

4.0:

```python
from pathlib import Path
from mineru.parser import parse

result = parse("a.pdf", tier="standard", page_range="1-3")
Path("a.md").write_text(result.markdown(), encoding="utf-8")
Path("a.json").write_text(result.to_json(), encoding="utf-8")
```

### 3.2 Connecting to a Self-Hosted V1 API

```python
from mineru.parser import MinerUApiParser

parser = MinerUApiParser(
    api_url="http://127.0.0.1:8000",   # the service root before /v1
    api_key="",                          # required when the service uses --api-key
    tier="standard",
    include_images=True,
)
result = parser.parse("a.pdf", page_range="1-3")
print(result.markdown())
```

For batch processing, reuse a single `MinerUApiParser` instance and catch exceptions per file (both `failed`/`canceled` terminal states and network errors raise exceptions).

### 3.3 The `ParseResult` Object

- `result.markdown()` / `result.to_json()` / `result.to_dict()`
- `ParseResult.from_json()` / `ParseResult.from_dict()` to restore
- Fields like `pdf_info` and `_backend` in old results are **not** the 4.0 structure; do not use them as templates. Historical artifacts are only read on explicitly supported compatibility paths; see [Output File Format](output_files.md).

## 4. CLI

| 3.x | 4.0 |
| --- | --- |
| `mineru -p in.pdf -o out` | `mineru-kit parse in.pdf -o out.md` (one-shot); `mineru parse in.pdf -o out.md` (doclib) |
| `mineru -p ./dir -o ./out` | `mineru-kit parse ./dir -o ./out --format zip` |
| `mineru-gradio` | `mineru-webui` / `mineru-kit webui` |
| `mineru-api` | `mineru-kit api-server` |
| `mineru-models-download -m all` | `mineru-kit models download --tier standard` |

`mineru-kit parse` and the Python SDK parse all pages by default; `mineru parse` (doclib) defaults to the first 10 pages. See [CLI Tools](../usage/cli_tools.md).

## 5. OpenAI-Compatible VLM Server (New in 4.0)

`mineru-kit vlm-server` (or `mineru-openai-server`) provides an OpenAI-compatible VLM inference interface:

```
GET  /v1/models
POST /v1/chat/completions
```

Note: this is a **VLM inference** interface, **not** the document parsing API; their addresses are not interchangeable. See the [migration guide](migration_4.md) for the relationship between the parsing API and the VLM server.

## 6. Migration Checklist

- [ ] Replace `/file_parse` and `/tasks` calls with the V1 "upload → job → poll → download" flow
- [ ] Change the `backend` parameter to `tier`
- [ ] Read results from `ParseResult` / V1 artifact files instead of `pdf_info`
- [ ] Change Python `do_parse` to `parse()` / `MinerUApiParser`
- [ ] Change CLI `mineru -p` to `mineru-kit parse`
- [ ] Use `GET /v1/health` `features.sources` / `features.output_formats` for capability discovery
- [ ] Verify in an isolated environment before migrating production

## 7. FAQ

- **`POST /file_parse` returns 404?** That route is removed in 4.0; use the V1 job flow.
- **Can I wait synchronously for the result?** No. V1 is always async; creation returns `202` and the client polls `GET /v1/parse/jobs/{id}`.
- **How do I get the images?** Request `zip` in `output_formats` and read the image sidecars from the zip artifact.
- **Can I skip the upload locally?** Yes. When the local server starts with `--allow-local-source` and `features.sources` includes `local`, use `{"type":"local","path":"..."}` to reference a local path directly.
- **How do `tier` and `backend` map?** See [2.4 Parameter Mapping](#24-parameter-mapping).

