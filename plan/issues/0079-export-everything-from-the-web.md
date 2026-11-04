# 0079 — Export everything from the web: one click for a full database dump

Status: **built** 2026-11-05 on `issue-0079-export`, not merged (Built, below). Secrets, access and the format were decided by the owner on 2026-11-04 (below).

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

## Built (2026-11-05)
- **Settings → Sources → data** (`?tab=data`, ⌘K "Export data"; `components/data/DataPanel.tsx`, in the settings chunk):
  - before the click: "The database is 736 MB. The zip: about 251 MB, about 28 seconds to write." (`GET /api/export`: the estimate is the tables' stored size, heap and TOAST, × 0.45 at 20 MB/s, measured below);
  - "Include stored logins", off by default; ticked, it says what it adds: the Substack session cookie and the Telegram API id, hash and sign-in session, encrypted, readable after a restore only with this server's secret key;
  - Export everything opens a confirmation ("The zip holds everything INSIGHT knows … Keep it somewhere private."), then the browser downloads the stream itself (a link, never held in the page);
  - while it runs: "Writing <file> · N MB so far"; after: the file name and its size, and the restore command; a stopped download says it is not a whole export (`GET /api/export/progress/{token}`);
  - Export sources: `GET /api/export/sources.json`, the document `sources.json` imports (`SourceConfigSyncService.sources_document()`, now shared with the file export).
- **The zip** (`services/export_service.py`, `GET /api/export/everything`): as the format section says. One repeatable-read, read-only snapshot on a connection of its own (no statement timeout); each table `COPY … TO STDOUT (FORMAT csv, HEADER)` read in chunks into a zip entry written as a stream (zipfile on an output with no seek: sizes after the data; zip64 entries); the tables from the catalog (every table but `schema_migrations`, in foreign-key order); `credentials` (the only login table) a header-only CSV unless logins are asked for. A download the browser stops closes the export: its COPY and snapshot end with it.
- **The restore** (`insight_core/db/import_export.py <zip> [--into <new db>]`): checks the manifest (format, every migration present here: a newer export is refused), creates the database, refuses one with any table; in one transaction runs only the export's migrations (with their recorded times), empties every table, turns the tables' own triggers off, drops the indexes no constraint owns, COPYs each CSV in foreign-key order (columns from its header), checks each count against the manifest, checks the deferred keys, builds the indexes, turns the triggers on, sets the sequences; then `migrate.py` brings it up to this version. DEPLOYMENT.md "Exporting and restoring the database"; the routes in BACKEND.md.
- **Measured** on a copy of the lab (41,637 posts):

  | | the zip | `pg_dump -Fc` |
  |---|---|---|
  | size | 243,246,920 bytes (792 MB of CSV) | 243,876,199 bytes |
  | time, quiet machine | 27.4–29.0 s | 27.2–27.4 s |
  | time, machine busy with other checks | 19–108 s | 27–64 s |

  - **memory:** the export alone peaks at 45–47 MB RSS; the API (the branch's, in its own container) rose from 54 MiB idle to 80.5 MiB streaming at full speed and 70 MiB to a client held at 4 MB/s (uvicorn's flow control holds the stream). No process of its own needed.
  - **a stopped download** (curl cut after 5 s): before the close was added the COPY and its snapshot stayed open (52 s and counting); with it, closed within seconds, progress "stopped before the end".
  - **restore equality:** into a new database, every table's row count and checksum (md5 of the ordered rows' md5s) equal the original, 31 of 31 with logins included (`schema_migrations` too); with logins left out, 30 of 31 and `credentials` 0 rows (4 in the original). The indexes, constraints and triggers (and their on state) are the same.
  - **restore time:** 352 s the first time (a busy machine, every index kept up row by row), 72 s quiet (posts 53 s: the search GIN index); with the plain indexes built after the load (44 indexes, 7.9 s), **41.4 s, as `pg_restore` of the same dump (41.4 s)**; posts 21.6 s.
  - **an older export migrating up:** a copy at migration 0058 (25 tables, 342,776 rows, zip 221 MB): the restore ran its 53 migrations, loaded it, then migrated 0059–0065; the result equals the same copy migrated in place, table by table (only `schema_migrations`' times for those 7 differ).
  - **explored alone:** `psql -f schema.sql` into an empty database makes the 31 tables.
- **Tests:** `tests/test_export.py` (an export of the run's database restored into a new one equals it table by table, with and without logins; triggers on after; refuses a database with data and an export from a newer INSIGHT; the routes: attachment, the generator closed, progress, sources.json read back by the importer); `lib/exportText.test.ts`; `components/data/DataPanel.test.tsx`.
- **Bundle (gzip):** the feed route 172,937 bytes (+0.08% over 172,793), the post route 313,005 (+0.05% over 312,854); the settings chunk (`SourcesConfig`) 42.3 kB.
- **Limits:** a restore is a command into a new database (switch with `DB_NAME`), never an import from the web; included logins read only with the same secret key; progress lives in the API's memory (a restart forgets it, the download is unaffected).

## Not in this issue
- Scheduled backups (the owner decided against them).
- Import from the web (a restore stays a command: it replaces everything).
