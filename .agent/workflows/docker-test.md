---
description: How to test and verify code changes in the Docker environment
---

# Docker Testing Workflow

> **CRITICAL**: All code testing and verification MUST be done inside Docker containers.
> NEVER use local `python`, `py_compile`, or `node` commands on Windows.
> The application runs ONLY in Docker.

## Docker Configuration

| Item | Value |
|:--|:--|
| Container name | `shukatsu-agent` |
| Compose file | `docker-compose.yml` |
| Port mapping | **Host 5001 → Container 5000** |
| Web UI | `http://localhost:5001` |
| Code mount | **NOT mounted** — code is `COPY`'d at build time |
| Data volume | `./data:/app/data` (persistent DB, browser state) |
| Env file | `./.env:/app/.env:ro` |

> [!IMPORTANT]
> Because code is `COPY`'d (not volume-mounted), **every code change requires `docker-compose up -d --build`** to take effect.

## Steps

// turbo-all

1. Rebuild and restart after code changes:
```powershell
docker-compose -f C:\Users\23111\.gemini\antigravity\scratch\job-agent\docker-compose.yml up -d --build
```

2. Check container is running:
```powershell
docker ps --filter "name=shukatsu-agent"
```

3. Check startup logs for errors:
```powershell
docker logs shukatsu-agent --tail 50
```

4. Run Python syntax/import checks inside the container:
```powershell
docker exec shukatsu-agent python -m py_compile <file_path_inside_container>
docker exec shukatsu-agent python -c "from <module> import <func>; print('OK')"
```

5. Test API endpoints:
```powershell
docker exec shukatsu-agent python -c "import requests; print(requests.get('http://localhost:5000/api/gmail/modes').json())"
```
Or from host: `curl http://localhost:5001/api/gmail/modes`

6. View web UI in browser at `http://localhost:5001`

## Important Notes
- Database is SQLite WAL mode at `/app/data/jobs.db` inside container
- Always use `get_db_connection()` (not `get_db()`) for DB access
- Gmail browser profile persists in `./data/gmail_profile/`
- Container auto-restarts (`restart: unless-stopped`)
