# Application schema migrations

Run `python scripts/migrate_database.py` with `DATABASE_URL` set to the target
`mysql+pymysql://...` database. The command creates missing tables and records
each successful revision in `schema_migrations`. Application startup does not
run migrations. This command does not import or modify historical SQLite data.

Migrations run forwards in the order declared in `MIGRATIONS`. Add a new revision
for later schema changes; never edit an applied revision to alter an existing
installation. Unknown recorded revisions fail visibly. The initial revision
preserves existing tables and rows; it does not repair a divergent existing
schema. MySQL DDL is not transactionally reversible, so each revision must support
rerunning after partial DDL completion. No downgrade, table drop, or reset is provided.

Revision 0002 requires MySQL 8 and uses `utf8mb4_0900_bin` so source, domain, version,
asset and job identifiers preserve case, accents and trailing spaces. Upgrading
existing 0001 tables temporarily removes the ingestion job's foreign key, converts
the three metadata tables, and restores the same exact-source foreign key. It
preserves all rows and repairs an interrupted conversion when rerun.
