# Maintaining a codebase: resources

## Knowledge

- [Talk: "A Philosophy of Software Design", John Ousterhout, Talks at Google (2018)](https://www.youtube.com/watch?v=bmSAYlu0NcY)
  Deep classes, defining errors out of existence, tactical vs strategic programming. Use for: the first thing to watch, and for depth and error handling.
- [Book: _A Philosophy of Software Design_, 2nd ed., John Ousterhout (2021)](https://web.stanford.edu/~ouster/cgi-bin/book.php)
  The full argument; the 2nd edition adds "Decide What Matters" and a comparison with _Clean Code_. Use for: going deeper after the talk.
- [Article: "Legacy Seam", Martin Fowler (2024)](https://martinfowler.com/bliki/LegacySeam.html)
  Feathers' definition of a seam, from _Working Effectively with Legacy Code_. Use for: seams, adapters, testing through an interface.
- [Article: "Feature Toggles (aka Feature Flags)", Pete Hodgson on martinfowler.com](https://martinfowler.com/articles/feature-toggles.html)
  Toggle categories, why release toggles are transitionary, toggles as inventory with a carrying cost. Use for: the `INSIGHT_ANALYSIS` switch and any future flag.
- [Article: "Yagni", Martin Fowler](https://martinfowler.com/bliki/Yagni.html)
  Cost of build vs cost of carry for presumptive features. Use for: deciding whether to keep dormant code.
- [Article: "Strangler Fig", Martin Fowler (2024)](https://martinfowler.com/bliki/StranglerFigApplication.html)
  Gradual modernisation instead of rewrites. Use for: converging behind one interface (ingestion, the Rust question).
- [Docs: FastAPI, Handling Errors](https://fastapi.tiangolo.com/tutorial/handling-errors/)
  `HTTPException` and `@app.exception_handler`. Use for: replacing the bridge's `{"success": false}` envelopes.
- [Docs: psycopg 3, Connection pools](https://www.psycopg.org/psycopg3/docs/advanced/pool.html)
  `ConnectionPool` and `with pool.connection()`: commit on success, rollback on error. Use for: the connection seam (issue 0003, slice 8).

## Wisdom (communities)

None chosen yet; ask the owner whether they want one before proposing any.

## Gaps

- No source yet on reviewing AI-agent-written code specifically (how tactical habits show up in agent diffs).
