# 队列服务模式

队列服务允许将文档解析任务提交到 Redis 队列中，由消费者异步处理，支持高并发场景。

## 架构说明

队列服务由两个 Docker 容器组成：
- `mineru-redis`: 独立 Redis 实例，仅在内网通信，不对外开放端口
- `mineru-queue`: 队列管理服务，提供 HTTP API (端口 8403)

## 两种部署模式

### 模式一：Mac 本地开发（MinerU 在宿主机）

适用于 macOS 等没有 GPU 的环境，MinerU FastAPI 运行在宿主机上。

```
┌─────────────────────────────────────────────────┐
│  Docker Network (docker_mineru-queue)            │
│                                                   │
│  ┌──────────────┐    内部网络    ┌──────────────┐
│  │ mineru-redis  │ ◄──────────► │ mineru-queue  │
│  │ :6379 (内部)  │               │ :8403 (外部)  │
│  └──────────────┘                └──────┬───────┘
│                                        │
│                              host.docker.internal:8401
│                                        │
│                                        ▼
│                              ┌──────────────────┐
│                              │ MinerU FastAPI    │
│                              │ (宿主机)          │
│                              └──────────────────┘
└─────────────────────────────────────────────────┘
```

**特点：**
- MinerU FastAPI 运行在宿主机（使用 CPU 或 MLX）
- 队列容器通过 `host.docker.internal` 访问宿主机 API
- 适合开发测试环境

**启动方式：**
```bash
# 1. 在宿主机启动 MinerU FastAPI
python -m mineru.cli.fast_api --host 0.0.0.0 --port 8401

# 2. 启动队列服务
docker compose -f docker/compose.queue.yml up -d
```

### 模式二：GPU 服务器部署（MinerU 在 Docker 中）

适用于有 GPU 的 Linux 服务器，MinerU FastAPI 也在 Docker 容器中运行。

```
┌─────────────────────────────────────────────────────────┐
│  Docker Network (docker_mineru-queue)                    │
│                                                          │
│  ┌──────────────┐    ┌──────────────┐    ┌────────────┐ │
│  │ mineru-redis  │ ◄─► │ mineru-queue │ ◄─► │ mineru-api │ │
│  │ :6379 (内部)  │     │ :8403 (外部) │     │ :8401 (内部)│ │
│  └──────────────┘     └──────────────┘     └─────┬────┘ │
│                                                   │     │
│                                          GPU 设备映射   │
│                                          NVIDIA/AMD GPU  │
└─────────────────────────────────────────────────────────┘
```

**特点：**
- MinerU FastAPI 运行在 Docker 容器中（使用 GPU）
- 所有服务在同一 Docker 网络内通信
- 适合生产环境

**启动方式：**
```bash
# 修改 compose.queue.yml，添加 mineru-api 服务
# 设置 MINERU_API_URL=http://mineru-api:8401
# 添加 GPU 设备映射到 mineru-api 容器

docker compose -f docker/compose.queue.yml up -d
```

## 配置参数

### Redis 配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MINERU_REDIS_HOST` | `redis` | Redis 主机名 |
| `MINERU_REDIS_PORT` | `6379` | Redis 端口 |
| `MINERU_REDIS_PASSWORD` | `mineru_queue_redis` | Redis 密码 |
| `MINERU_REDIS_DB` | `0` | Redis 数据库编号 |

### 队列配置
| 参数 | 默认值 | 说明 |
|------|--------|------|
| `MINERU_API_URL` | `http://host.docker.internal:8401` | MinerU FastAPI 地址 |
| `MINERU_QUEUE_MAX_SIZE` | `20` | 最大队列长度 |
| `MINERU_QUEUE_RESULT_TTL` | `86400` | 结果保留时间（秒） |
| `MINERU_QUEUE_POLL_INTERVAL` | `1.0` | 轮询间隔（秒） |

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

- Redis 不对外开放端口，仅通过 Docker 内部网络通信
- Redis 使用密码保护，默认密码为 `mineru_queue_redis`
- 生产环境建议修改默认密码