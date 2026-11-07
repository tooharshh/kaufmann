#!/usr/bin/env bash
set -euo pipefail

repository_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repository_root"
test_container_name="kaufmann-tests-$$"
docker run --rm -d --name "$test_container_name" \
    -e POSTGRES_PASSWORD=local-test-only -p 127.0.0.1::5432 postgres:17-alpine > /dev/null
trap 'docker stop "$test_container_name" > /dev/null' EXIT
for ((attempt = 0; attempt < 30; attempt++)); do
    if docker exec "$test_container_name" pg_isready -h 127.0.0.1 -U postgres > /dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec "$test_container_name" pg_isready -h 127.0.0.1 -U postgres > /dev/null
docker exec -i "$test_container_name" psql -U postgres -v ON_ERROR_STOP=1 > /dev/null <<'SQL'
create role anon;
create role authenticated;
create schema auth;
create table auth.users (id uuid primary key);
create function auth.uid() returns uuid language sql stable as $$
    select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid
$$;
grant usage on schema auth to authenticated;
SQL
for migration in supabase/migrations/*.sql; do
    docker exec -i "$test_container_name" psql -U postgres -v ON_ERROR_STOP=1 -1 < "$migration" > /dev/null
done
test_binding="$(docker port "$test_container_name" 5432/tcp)"
test_port="${test_binding##*:}"
TEST_DATABASE_URL="postgresql://postgres:local-test-only@127.0.0.1:$test_port/postgres" uv run pytest "$@"
