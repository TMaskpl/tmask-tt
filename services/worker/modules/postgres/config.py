PG_DUMP_BASE_FLAGS = ['--clean', '--if-exists', '--no-owner', '--no-privileges', '--verbose']
PG_DUMP_MAX_RETRIES = 3
PG_DUMP_RETRY_DELAY = 5

# pg_dump 17's plain-text preamble unconditionally emits `SET transaction_timeout = 0;`
# (transaction_timeout is a PG17-only GUC). Destinations running an older server reject
# it with "unrecognized configuration parameter" and, with psql's ON_ERROR_STOP=1, abort
# the whole restore — even though the rest of the dump is fully compatible. Strip it in
# transit so newer client tools can still restore into older Postgres servers.
SED_STRIP_INCOMPATIBLE_SET = r'/^SET transaction_timeout/d'
