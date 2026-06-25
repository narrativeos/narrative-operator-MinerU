<!--
 * @Author: Future Meng futuremeng@gmail.com
 * @Date: 2026-06-25 20:48:20
 * @LastEditors: Future Meng futuremeng@gmail.com
 * @LastEditTime: 2026-06-25 20:48:32
 * @FilePath: /narrative-operator-MinerU/projects/web_api_queue/README.md
 * @Description: 这是默认设置,请设置`customMade`, 打开koroFileHeader查看配置 进行设置: https://github.com/OBKoro1/koro1FileHeader/wiki/%E9%85%8D%E7%BD%AE
-->
# ⚠️ DEPRECATED

This directory (`projects/web_api_queue/`) has been **deprecated** and replaced by the new unified queue service.

## Migration

The queue functionality has been moved to:

- **Queue Service**: `services/queue/` - New Redis-backed queue service
- **Docker Compose**: `docker/compose.queue.yml` - Docker deployment configuration
- **Start Script**: `scripts/start_mineru_local.sh` - Now supports `queue` and `all` modes

## New Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────────┐
│   Gradio      │    │   FastAPI    │    │  Queue Service   │
│  (:8400)      │    │  (:8401)     │    │  (:8403)         │
│              │────│              │────│                  │
└──────┬───────┘    └──────┬───────┘    └────────┬─────────┘
       │                   │                      │
       └───────────────────┴──────────────────────┼───────────
                                                  │
                                         ┌────────┴──────┐
                                         │    Redis      │
                                         │   (:6379)     │
                                         └──────────────┘
```

## Usage

### Local startup (with Redis)
```bash
# Start all services including queue
bash scripts/start_mineru_local.sh all

# Start only queue service
bash scripts/start_mineru_local.sh queue
```

### Docker Compose
```bash
docker compose -f docker/compose.queue.yml up -d
```

## For Developers

The new queue service in `services/queue/` provides:
- Redis-based persistent queue
- RESTful API for task management
- Background consumer for task processing
- Integration with Gradio UI

See `services/queue/` for implementation details.