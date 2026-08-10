#!/bin/sh
set -eu

for value in "$TICKETINSIGHT_APP_DB_PASSWORD" "$TICKETINSIGHT_READONLY_DB_PASSWORD" "$TICKETINSIGHT_MIGRATOR_DB_PASSWORD"; do
  case "$value" in
    *"'"*|*"\\"*|"") echo "Unsafe local demo password characters" >&2; exit 1 ;;
  esac
done

mysql --protocol=socket -uroot -p"${MYSQL_ROOT_PASSWORD}" <<-EOSQL
  CREATE USER IF NOT EXISTS 'ticketinsight_app'@'%' IDENTIFIED BY '${TICKETINSIGHT_APP_DB_PASSWORD}';
  CREATE USER IF NOT EXISTS 'ticketinsight_readonly'@'%' IDENTIFIED BY '${TICKETINSIGHT_READONLY_DB_PASSWORD}';
  CREATE USER IF NOT EXISTS 'ticketinsight_migrator'@'%' IDENTIFIED BY '${TICKETINSIGHT_MIGRATOR_DB_PASSWORD}';
  GRANT SELECT, INSERT, UPDATE, DELETE ON ticketinsight.* TO 'ticketinsight_app'@'%';
  GRANT SELECT ON ticketinsight.* TO 'ticketinsight_readonly'@'%';
  GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, DROP, INDEX, REFERENCES ON ticketinsight.* TO 'ticketinsight_migrator'@'%';
  FLUSH PRIVILEGES;
EOSQL
