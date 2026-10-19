# Sida 수집 서버 (collector)

Sida 앱이 보내는 사용 기록(`docs/telemetry.md`)을 받아 Postgres에 넣는 작은 서버입니다. 팀 VPS의 `/opt/sida-data`에서 Docker로 돕니다. 로컬 앱 패키지에는 들어가지 않습니다.

- `POST /api/v1/events`: 기록 묶음을 받습니다(최대 100개, 512KB). 202 `{"accepted", "stored"}`
- `GET /api/v1/health`: `{"ok": true}`
- 기록을 읽어 가는 경로는 없습니다. 앱에는 비밀값이 없으니(누구나 코드를 볼 수 있음) 받는 모양과 크기를 엄격히 검사하고, 설치 ID마다 시간당 2,000개, 보내는 주소마다 시간당 5,000개로 제한합니다. 보내는 주소는 제한에만 쓰고 저장하지 않습니다.
- 같은 기록(같은 `id`)을 다시 보내면 한 번만 저장됩니다.

## 설치 (VPS)

`/opt/sida-data`에 이미 `db`(Postgres)와 `caddy`가 있다는 전제입니다.

1. 이 폴더의 `Dockerfile`, `requirements.txt`, `__init__.py`, `app.py`를 서버의 `/opt/sida-data/collector/`에 복사합니다.
2. `docker-compose.yml`에 서비스를 더합니다.

   ```yaml
   api:
     build: ./collector
     environment:
       SIDA_DB_HOST: db
       SIDA_DB_USER: sida
       SIDA_DB_NAME: sida
       SIDA_DB_PASSWORD_FILE: /run/secrets/db_password
     secrets: [db_password]
     networks: [sida_internal]
     depends_on:
       db:
         condition: service_healthy
     mem_limit: 256m
     restart: unless-stopped
   ```

3. `Caddyfile`을 바꿉니다.

   ```
   sida-data.duckdns.org {
     handle /api/v1/* {
       request_body {
         max_size 1MB
       }
       reverse_proxy api:8000
     }
     handle /health {
       respond "ok" 200
     }
     handle {
       respond 404
     }
   }
   ```

4. `docker compose up -d --build api && docker compose restart caddy`
5. 확인: `curl https://sida-data.duckdns.org/api/v1/health`

## 기록 보기

```bash
docker compose exec db psql -U sida -d sida -c \
  "select kind, count(*) from events group by kind order by 2 desc;"
```

## 테스트

`tests/collector/`가 메모리 저장소로 검사합니다(Postgres 없이 `pytest`로 돕니다).
