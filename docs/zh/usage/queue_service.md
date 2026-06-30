# 队列服务模式

队列服务允许将文档解析任务提交到 SQLite 队列中，由消费者异步处理，支持高并发场景。

## 架构说明

队列使用 SQLite 作为后端，无需 Redis 或额外 Docker 容器。队列功能内嵌在 Gradio 应用中，本地开发无需任何额外部署。

## 两种使用模式

### 模式一：内嵌模式（默认，推荐本地开发）

队列直接内嵌在 Gradio 进程中，使用 SQLite 存储任务数据，无需任何额外服务。

```
┌─────────────────────────────────────────────────┐
│  Gradio 进程 (:8400)                             │
│                                                   │
│  ┌──────────────┐    ┌──────────────┐            │
│  │  Gradio UI   │ ──►│  Queue       │            │
│  │              │     │  (SQLite)    │            │
│  └──────────────┘     └──────┬───────┘            │
│                              │                     │
│                              ▼                     │
│                       ┌──────────────┐            │
│                       │  Consumer    │            │
│                       │  (后台线程)   │            │
│                       └──────┬───────┘            │
│                              │                     │
│                              ▼                     │
│                       ┌──────────────┐            │
│                       │ MinerU API   │            │
│                       │ (:8401)      │            │
│                       └──────────────┘            │
└─────────────────────────────────────────────────┘
```

**特点：**
- 无需 Docker、Redis 或任何额外服务
- 启动 Gradio 时队列自动启用
- SQLite 数据库存储在 `./output/mineru_queue.db`
- 上传文件暂存于 `./input/` 目录
- 结果输出到 `./output/` 目录

**启动方式：**
```bash
# 一键启动所有服务（包含内嵌队列）
bash scripts/start_mineru_local.sh all

# 或只启动 Gradio（队列自动启用）
bash scripts/start_mineru_local.sh gradio
```

### 模式二：远程队列模式（Docker 部署）

适用于需要独立队列服务的高并发场景，队列作为独立 Docker 容器运行。

```
┌─────────────────────────────────────────────────┐
│  Docker Network                                   │
│                                                   │
│  ┌──────────────┐    ┌──────────────┐            │
│  │ mineru-queue  │ ◄─►│ mineru-api   │            │
│  │ :8403 (外部)  │     │ :8401 (内部) │            │
│  │ (SQLite)     │     │ (GPU)        │            │
│  └──────────────┘     └──────────────┘            │
└─────────────────────────────────────────────────┘
```

**特点：**
- 队列服务独立部署，可水平扩展多个 consumer
- 使用 SQLite 替代 Redis，无需额外数据库
- 适合生产环境

**启动方式：**
```bash
# 启动队列服务（Docker）
docker compose -f docker/compose.queue.yml up -d

# 设置环境变量指向远程队列
export MINERU_QUEUE_SERVICE_URL=http://queue-server:8403

# 启动 Gradio（将使用远程队列）
bash scripts/start_mineru_local.sh gradio
```

## 配置参数

### 队列配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MINERU_QUEUE_SERVICE_URL` | 未设置（内嵌模式） | 远程队列服务地址 |
| `MINERU_API_URL` | `http://localhost:8401` | MinerU FastAPI 地址 |
| `MINERU_QUEUE_MAX_SIZE` | `20` | 最大队列长度 |
| `MINERU_QUEUE_RESULT_TTL` | `86400` | 结果保留时间（秒） |
| `MINERU_QUEUE_POLL_INTERVAL` | `1.0` | 轮询间隔（秒） |
| `MINERU_QUEUE_TMP_DIR` | `./input` | 上传文件暂存目录 |
| `MINERU_QUEUE_OUTPUT_ROOT` | `./output` | 结果输出目录 |
| `MINERU_QUEUE_DB_PATH` | `./output/mineru_queue.db` | SQLite 数据库路径 |

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/stats` | 获取队列统计 |
| `POST` | `/tasks` | 提交解析任务 |
| `GET` | `/tasks` | 获取所有任务 |
| `GET` | `/tasks/{id}` | 获取任务状态 |
| `GET` | `/tasks/{id}/result` | 下载结果 |
| `DELETE` | `/tasks` | 清空所有任务 |
| `DELETE` | `/tasks/{id}` | 删除/取消任务 |

## 安全说明

- 内嵌模式下队列仅在本机可用，不暴露网络端口
- Docker 模式下队列服务仅监听指定端口
- 生产环境建议配合反向代理和认证使用