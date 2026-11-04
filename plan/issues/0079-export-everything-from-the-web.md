# 0079 — Export everything from the web: one click for a full database dump

Status: **spec, decided** (owner, 2026-11-04): built after 0080 merges. Secrets, access and the format were decided the same day (below).

## The owner's words
"Please add button to export whole database as we are doing with data pgdump on the web as well, because I don't like to everytime go in server and dump everything, single click should be enough."

## Today
- **A copy of the data means a shell on the server:** `docker exec … pg_dump`, then copying the file off. That's how the lab copies were made.
- **The earlier "Export sources" request** (a list of sources) is still waiting for the owner's decision. This issue covers it: sources are part of the dump, and a small sources-only export can sit next to it.
- **The owner decided: no automatic backups.** This is a dump **on request**, not a schedule.

## The idea
- **Settings → Data:**
  - **Export everything:** a `pg_dump` custom-format file (`insight-YYYY-MM-DD-HHMM.dump`), streamed to the browser as it is made, with no copy left on the server's disk;
  - **Export sources:** the source list as JSON, in the shape `sources.json` imports.
- **Shown before the click:** the database size, and an estimate of the file size and time.
- **Shown after:** the file name, its size, and the restore command:
  ```
  pg_restore -d <db> --clean --if-exists <file>
  ```
- **The lab and 0075's checks** can then start from a downloaded file instead of a server shell.

## What needs deciding or measuring
1. **Secrets:**
   - the dump holds the stored credentials (the Telegram session, API keys, cookies);
   - options:
     - (a) include them and say so before the click;
     - (b) leave the credentials tables out (`--exclude-table-data`) and have them re-entered after a restore;
     - (c) offer both.
   - **Decided (owner, 2026-11-04):** (b) by default: the logins are left out. A checkbox, "Include stored logins", adds them, and says what that includes.
2. **Who can click it** (decided, owner 2026-11-04: a confirmation is enough while INSIGHT runs on the owner's private network; an access rule comes before any hosted or shared use):
   - INSIGHT has no login today; the server is reachable on the owner's private network;
   - a full dump is everything the app knows, so the button needs at least a confirmation, and an access rule once a hosted tier or sharing exists.
3. **Where `pg_dump` runs:**
   - in the backend container (it needs the Postgres client of the database's major version: adds ~10 MB to the image, measure);
   - or as a one-off in the database container.
   - The dump must not slow reading: measure its time and the API's memory on the lab size (41,637 posts).
4. **Size:**
   - measure the dump of the lab and of a fresh server copy, with and without bodies' HTML;
   - a slow link needs a resumable download, or a size shown first.

## The format (owner, 2026-11-04: "B approach is better for us")
INSIGHT writes its own export, with no `pg_dump`: the image gets no Postgres client and nothing is downloaded.

**One zip, streamed to the browser** (`insight-YYYY-MM-DD-HHMM.zip`), holding:
- **one CSV per table** (`posts.csv`, `sources.csv`, …), written by Postgres's `COPY … TO STDOUT (FORMAT csv, HEADER)`, read in batches. Text stays text; a vector column is its text form.
- **`schema.sql`:** the migrations in order (the exact schema the data belongs to).
- **`manifest.json`:** the INSIGHT version and commit, the last migration, the time, and each table's row count. Whether logins are included.
- **`README.txt`:** how to restore it into INSIGHT, and how to explore it alone.

**Restored into INSIGHT** (a new or empty database):
- `python insight_core/db/import_export.py <zip>`;
- it checks the manifest;
- it runs the migrations up to the export's level, then loads each CSV with `COPY … FROM STDIN`, in the order the foreign keys need;
- then the normal migrations bring it up to the running version.

**Explored on its own, with no INSIGHT:**
- the CSVs open in any tool:
  - DuckDB (`SELECT * FROM 'posts.csv'`);
  - pandas;
  - SQLite (`.import`);
  - a spreadsheet for small tables;
- or `psql -f schema.sql` into any Postgres (with the pgvector extension), then `\copy` each CSV.
- The README lists both.

**Logins:** the credential tables are written as empty CSVs unless "Include stored logins" is checked; the manifest says which.

**Measure before adopting:**
- the zip's size and time on the lab (41,637 posts), against `pg_dump -Fc`;
- the API's memory while it streams;
- a restore of the lab export into a scratch database that equals the original, table by table (row counts and a checksum per table).

## Not in this issue
- Scheduled backups (the owner decided against them).
- Import from the web (a restore stays a command: it replaces everything).
