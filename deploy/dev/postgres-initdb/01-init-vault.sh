#!/bin/sh
# Создаёт схему `vault` + роль `vault` с доступом только к этой схеме
# (search_path=vault). Используется как RUNTIME_VAULT_PG_DSN для
# physical isolation вault-хранилища (secrets.store, _system.*, и т.п.)
# от основной схемы `public`.
#
# Запускается только при первой инициализации pg-data volume
# (docker-entrypoint-initdb.d).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE SCHEMA IF NOT EXISTS vault;

    DO \$\$
    BEGIN
       IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'vault') THEN
          CREATE ROLE vault WITH LOGIN PASSWORD '${VAULT_PG_PASSWORD:-vault}';
       END IF;
    END
    \$\$;

    GRANT ALL ON SCHEMA vault TO vault;
    ALTER ROLE vault SET search_path = vault;
    ALTER ROLE vault IN DATABASE ${POSTGRES_DB} SET search_path = vault;
    GRANT CONNECT ON DATABASE ${POSTGRES_DB} TO vault;
EOSQL
