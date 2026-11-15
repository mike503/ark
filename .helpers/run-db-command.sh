#!/bin/bash
# Execute SQL commands piped to this script
#
# Usage:
#   echo "SELECT 1;" | .helpers/run-db-command.sh
#   cat server/db/schema.sql | .helpers/run-db-command.sh

set -a
# shellcheck disable=SC1091
source "$(dirname "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)")/.env"
set +a
mysql -u"$DATABASE_USER" -p"$DATABASE_PASSWORD" -A "$DATABASE_NAME"
