# 0079 — Export everything from the web: one click for a full database dump

Status: **idea, filed for the future** (owner, 2026-11-04). Not scheduled. Secrets and access decided by the owner the same day (below).

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

## Not in this issue
- Scheduled backups (the owner decided against them).
- Import from the web (a restore stays a command: it replaces everything).
