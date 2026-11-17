#!/bin/bash
# Publish the Study Bridge plugin HTTP port (6188) from the astrbot container to
# the host, WITHOUT touching the existing compose file (uses an extra override).
# Safe to re-run. Roll back with:
#   rm docker-compose.study.yml && docker compose up -d
# ASCII only. LF only.
set -u
say(){ printf '%s\n' "$*"; }
CT=astrbot

IP=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$CT" 2>/dev/null)
say "[0] container_ip=${IP:-none}"
[ -z "$IP" ] && { say "ERR=no_container_ip"; exit 1; }

say "[1] health INSIDE the container"
if docker exec "$CT" sh -c 'curl -s -m 5 http://127.0.0.1:6188/api/study/health' 2>/dev/null; then
  say ""
else
  say "ERR=no_listen_inside"
  docker logs "$CT" --tail 120 2>&1 | grep -iE 'study|6188' | tail -20
  exit 2
fi

say "[2] reachable from host via container IP"
if curl -s -m 5 "http://$IP:6188/api/study/health" >/dev/null 2>&1; then
  say "ok"
else
  say "ERR=bind_loopback_only"
  say "fix: plugin config http.host must be 0.0.0.0, then restart astrbot"
  exit 3
fi

say "[3] compose project"
DIR=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.project.working_dir"}}' "$CT" 2>/dev/null)
SVC=$(docker inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$CT" 2>/dev/null)
say "dir=${DIR:-none} svc=${SVC:-none}"
if [ -z "$DIR" ] || [ ! -d "$DIR" ]; then say "ERR=not_compose"; exit 4; fi
cd "$DIR" || { say "ERR=cd_failed"; exit 4; }

MAIN=""
for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
  if [ -f "$f" ]; then MAIN="$f"; break; fi
done
say "compose_file=${MAIN:-none}"
[ -z "$MAIN" ] && { say "ERR=no_compose_file"; exit 4; }
[ -z "$SVC" ] && SVC=astrbot

say "[4] additive override + recreate"
cat > docker-compose.study.yml <<YAML
services:
  ${SVC}:
    ports:
      - "0.0.0.0:6188:6188"
YAML

if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"; else COMPOSE="docker-compose"; fi
say "compose_cmd=$COMPOSE"
$COMPOSE -f "$MAIN" -f docker-compose.study.yml up -d || { say "ERR=compose_up_failed"; exit 5; }

say "[5] wait for the plugin to come back"
OK=0
for i in 1 2 3 4 5 6 7 8; do
  sleep 4
  if curl -s -m 5 http://127.0.0.1:6188/api/study/health; then say ""; OK=1; break; fi
done
[ "$OK" != "1" ] && { say "ERR=health_failed_after_publish"; docker logs "$CT" --tail 60 2>&1 | tail -20; exit 6; }

say "[6] docker port"
docker port "$CT" || true
if command -v ufw >/dev/null 2>&1; then say "[7] ufw"; ufw status | head -3; fi
say "APP_URL=http://${PUBLIC_HOST:-YOUR_SERVER_IP}:6188"
say "DONE"
