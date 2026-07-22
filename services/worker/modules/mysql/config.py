MYSQL_DUMP_BASE_FLAGS = ['--single-transaction', '--set-gtid-purged=OFF', '--skip-lock-tables']
MYSQL_DUMP_MAX_RETRIES = 3
MYSQL_DUMP_RETRY_DELAY = 5

# MySQL 8.0 changed the default utf8mb4 collation from utf8mb4_general_ci to
# utf8mb4_0900_ai_ci. A dump taken from an 8.0+ source embeds this collation in
# CREATE TABLE statements; restoring into a pre-8.0 destination (which doesn't
# know this collation) fails with "Unknown collation". Stripped in transit when
# the destination is detected as < 8.0 — see handler._dest_needs_collation_strip().
SED_STRIP_MYSQL80_COLLATION = r's/ COLLATE utf8mb4_0900_ai_ci//g'
