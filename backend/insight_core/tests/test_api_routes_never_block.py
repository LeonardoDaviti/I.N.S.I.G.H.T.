"""v10.17 (issue 0195): no route blocks the API's event loop. An `async def` route runs on the loop itself, so a sync
service call inside it (a database read, a file write) stops every other request of the process until it returns:
the audit found 16 GET routes so (the top bar's overview, polled on every page, among them). A sync route is a plain
`def` (FastAPI runs it in its threadpool); an async one awaits its sync work (asyncio.to_thread).

The guard reads every route of the app's modules (main.py, the routers) from the source:
  - an async route awaits something (else it is a plain def), except ALLOWED_ASYNC;
  - an async route calls no sync service directly: no call on services()'s services (services().x.y(...)) and no
    call of a module function that makes one, unless awaited (an async service method) or handed to to_thread.
No database."""
from __future__ import annotations

import ast
import unittest
from pathlib import Path
from typing import List, Set

BACKEND = Path(__file__).resolve().parents[2]
# An async route that awaits nothing on purpose: the watchdog's measure busy-loops this process's loop (issue 0117).
ALLOWED_ASYNC = {("main.py", "debug_spin")}


def route_files() -> List[Path]:
    files = [BACKEND / "main.py"]
    for p in sorted((BACKEND / "insight_core").rglob("*.py")):
        if "tests" in p.parts:
            continue
        text = p.read_text(encoding="utf-8")
        if "@router." in text or "@app." in text:
            files.append(p)
    return files


def _is_route(fn: ast.AST) -> bool:
    return any(ast.unparse(d).startswith(("app.", "router.")) for d in getattr(fn, "decorator_list", []))


def _rooted_in_services(node: ast.AST) -> bool:
    """Whether an attribute chain starts at a call of services() (the registry of sync services)."""
    while isinstance(node, (ast.Attribute, ast.Call, ast.Subscript)):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "services":
                return True
            node = node.func
        else:
            node = node.value
    return False


def _service_call(call: ast.Call) -> bool:
    """services().x.y(...): a method of a sync service called."""
    return isinstance(call.func, ast.Attribute) and _rooted_in_services(call.func.value)


def _sync_helpers(tree: ast.Module) -> Set[str]:
    """The module's own sync functions that call a sync service themselves."""
    return {n.name for n in tree.body if isinstance(n, ast.FunctionDef)
            and any(isinstance(c, ast.Call) and _service_call(c) for c in ast.walk(n))}


def blocking_routes() -> List[str]:
    """["file:line name: why"] for every async route that blocks the loop."""
    out = []
    for path in route_files():
        rel = path.relative_to(BACKEND).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"))
        helpers = _sync_helpers(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, ast.AsyncFunctionDef) or not _is_route(fn) or (rel, fn.name) in ALLOWED_ASYNC:
                continue
            awaited = {id(n.value) for n in ast.walk(fn) if isinstance(n, ast.Await)}
            if not awaited and not any(isinstance(n, (ast.AsyncFor, ast.AsyncWith)) for n in ast.walk(fn)):
                out.append(f"{rel}:{fn.lineno} {fn.name}: async but awaits nothing (make it a plain def)")
                continue
            for call in (n for n in ast.walk(fn) if isinstance(n, ast.Call) and id(n) not in awaited):
                if _service_call(call):
                    out.append(f"{rel}:{call.lineno} {fn.name}: {ast.unparse(call.func)}(...) on the loop")
                elif isinstance(call.func, ast.Name) and call.func.id in helpers:
                    out.append(f"{rel}:{call.lineno} {fn.name}: {call.func.id}() calls a sync service on the loop")
    return out


# Issue 0206: a page's open starts no work in the API process (Discover's list and its web reads, the main source's
# scan and tests ran in its background: 17-300 s with the API's memory); the jobs process does it, the API marks it
# wanted. The GET routes that still do, each with why (not this wave's).
ALLOWED_GET_STARTS = {("insight_core/markx/research_api.py", "mx_research_page")}   # a research run's next step


def get_routes_starting_work() -> List[str]:
    """["file name: call"] of every GET route that starts background work (a `.start(`, `create_task`, `add_task`)."""
    out = []
    for path in route_files():
        rel = path.relative_to(BACKEND).as_posix()
        for fn in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or (rel, fn.name) in ALLOWED_GET_STARTS:
                continue
            if not any(ast.unparse(d).startswith(("app.get", "router.get")) for d in fn.decorator_list):
                continue
            out += [f"{rel} {fn.name}: {ast.unparse(c.func)}" for c in ast.walk(fn)
                    if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                    and c.func.attr in ("start", "create_task", "add_task")]
    return out


class NoPageStartsWork(unittest.TestCase):
    def test_no_get_route_starts_background_work(self):
        self.assertEqual(get_routes_starting_work(), [])

    def test_discover_has_no_api_side_starter(self):
        from insight_core.services import discover_main_source, discover_reads
        self.assertFalse(hasattr(discover_reads, "start") or hasattr(discover_reads, "running"))
        self.assertFalse(hasattr(discover_main_source.MainSource, "start"))


class RoutesNeverBlock(unittest.TestCase):
    def test_no_async_route_runs_sync_work_on_the_loop(self):
        self.assertEqual(blocking_routes(), [])

    def test_the_guard_sees_a_blocking_route(self):
        bad = ast.parse(
            "@app.get('/x')\nasync def a():\n    return services().reader.unread_counts()\n"
            "@app.get('/y')\nasync def b():\n    x = await asyncio.to_thread(services().news.news, 'all')\n"
            "    services().news.hide('u')\n    return x\n"
            "@app.get('/z')\nasync def c():\n    return await asyncio.to_thread(services().news.news, 'all')\n")
        found = []
        for fn in (n for n in bad.body if isinstance(n, ast.AsyncFunctionDef)):
            awaited = {id(n.value) for n in ast.walk(fn) if isinstance(n, ast.Await)}
            found.append((fn.name, bool(awaited), [ast.unparse(c.func) for c in ast.walk(fn)
                                                   if isinstance(c, ast.Call) and id(c) not in awaited
                                                   and _service_call(c)]))
        self.assertEqual(found, [("a", False, ["services().reader.unread_counts"]),
                                 ("b", True, ["services().news.hide"]),
                                 ("c", True, [])])

    def test_the_routes_are_read(self):
        # main.py and the Mark X routers are among the files read (a moved router would silently escape the guard)
        names = {p.name for p in route_files()}
        self.assertTrue({"main.py", "api.py", "tracks_api.py", "discover_main_source.py"} <= names, names)


if __name__ == "__main__":
    unittest.main()
