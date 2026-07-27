---
description: How to test and verify code changes locally or in Docker
---

# Local-First Testing Workflow

The application is designed to run directly in a Python virtual environment.
Docker is optional and should only be used when the developer explicitly wants
container parity. On machines with limited disk space, use the local workflow.

## Local workflow (default)

1. Create/install the environment with `setup.bat` (Windows) or `setup.sh`.
2. Run syntax checks with `python -m compileall .`.
3. Run regression tests with `python -m unittest discover -s tests -v`.
4. Start with `start.bat`, `start.sh`, or `python app.py`.
5. Open `http://localhost:5000`.

The default host is `127.0.0.1`; remote access must be explicitly enabled.

## Optional Docker Configuration

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
docker compose up -d --build
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
