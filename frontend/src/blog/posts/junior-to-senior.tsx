import { C, Cite, Code, Compare, Figure, H2, List, P, Quiz, Takeaway, type QuizQuestion } from '../components';
import { DepthFigure, GrowthFigure, RequestPathFigure, WeightFigure } from '../figures';

const SRC = {
  ousterhoutTalk: 'https://www.youtube.com/watch?v=bmSAYlu0NcY',
  ousterhoutBook: 'https://web.stanford.edu/~ouster/cgi-bin/book.php',
  seam: 'https://martinfowler.com/bliki/LegacySeam.html',
  yagni: 'https://martinfowler.com/bliki/Yagni.html',
  toggles: 'https://martinfowler.com/articles/feature-toggles.html',
  strangler: 'https://martinfowler.com/bliki/StranglerFigApplication.html',
  fastapiErrors: 'https://fastapi.tiangolo.com/tutorial/handling-errors/',
  psycopgPool: 'https://www.psycopg.org/psycopg3/docs/advanced/pool.html',
};

const QUESTIONS: QuizQuestion[] = [
  {
    prompt: <>A route catches every exception and returns <C>{'{"success": false}'}</C>. The database is down. What status does the browser get?</>,
    options: ['An HTTP 500 server error', 'An HTTP 200 success response', 'An HTTP 404 missing resource', 'An HTTP 409 conflict response'],
    answer: 1,
    why: <>The exception never reaches FastAPI, so the response is a normal 200 with a failure hidden in the body. Every caller has to remember to look inside — and the raw <C>str(e)</C> goes out with it.</>,
  },
  {
    prompt: 'You imagine deleting a module, and the complexity simply vanishes. What was the module?',
    options: ['A deep module earning keep', 'A seam with two adapters', 'A pass-through adding no value', 'A feature toggle still needed'],
    answer: 2,
    why: <>That is the deletion test. If deleting it makes complexity reappear in many callers, it was earning its keep. If nothing reappears, it was only forwarding calls — like most of the 136 bridge methods.</>,
  },
  {
    prompt: <>The feature flag says <C>Hidden, not deleted</C>. What does Pete Hodgson call the price of keeping it?</>,
    options: ['A carrying cost, like inventory', 'A build cost, paid once', 'A merge cost, paid weekly', 'A runtime cost, paid nowhere'],
    answer: 0,
    why: <>Hodgson: teams should view toggles “as inventory which comes with a carrying cost”. Fowler makes the same point for presumptive features: their complexity makes everything else harder to change.</>,
  },
  {
    prompt: 'When is a seam a real one, rather than a hypothetical one?',
    options: ['When one adapter fills it', 'When it has an interface', 'When tests can mock it', 'When two adapters fill it'],
    answer: 3,
    why: <>One adapter means nothing varies across the seam yet. <C>SourceKind</C> is real: seven adapters fill it, from RSS to Telegram to YouTube.</>,
  },
  {
    prompt: <>The backend opens a raw database connection in 165 places. What does one connection module buy you?</>,
    options: ['Locality: change pooling in one place', 'Leverage: fewer routes for every caller', 'Depth: more methods on the interface', 'Speed: queries run without any locks'],
    answer: 0,
    why: <>Locality is what maintainers get from depth: timeouts, pooling and transactions change in one file instead of 31. It is also the precondition for merging the API and ingestion into one process.</>,
  },
  {
    prompt: 'Telegram fetching was rebuilt four times. What is the senior move for the next change?',
    options: ['Rewrite it once more, properly', 'Converge behind one seam, gradually', 'Freeze it and never touch', 'Copy it per source type'],
    answer: 1,
    why: <>Fowler’s strangler fig: move behaviour piece by piece behind a stable interface instead of restarting. Mark IX gave ingestion that interface: <C>run_ingestion()</C> and <C>SourceKind</C>.</>,
  },
];

export default function JuniorToSenior() {
  return (
    <>
      <P className="mt-0 text-[1.1875rem] text-fg-2">
        In sixteen months INSIGHT grew from 964 lines to 99,059. About half of that is weight we carry and never use. This is the story of how
        that happened, the junior habits that caused it, and the senior practices we are switching to — with real code from this repository.
      </P>

      <Figure n={1} caption="Tracked lines at the last commit of each Mark (lockfiles and images excluded). The dashed bar is where the cleanup in issue 0003 should land.">
        <GrowthFigure />
      </Figure>

      <H2 id="tactical">Junior code works today. Senior code is cheap to change tomorrow.</H2>
      <P>
        “Junior” here is not an insult. It describes a way of working that John Ousterhout calls <em>tactical programming</em>: the goal is to get
        the next feature working, as fast as possible. Each shortcut is reasonable on its own. Together they become a codebase where every
        change is slow, because every change touches many places. His alternative, <em>strategic programming</em>, spends a little of every change
        on the design, so the next change is cheaper (<Cite href={SRC.ousterhoutTalk}>Ousterhout, Talks at Google, 2018</Cite>).
      </P>
      <P>
        INSIGHT was built tactically, fast, by one owner and a series of AI agents, one Mark at a time. Mark VII alone added about 41,000 lines.
        Nobody made a bad decision; nobody owned the shape. The audit in October 2026 found where the weight is:
      </P>

      <Figure n={2} caption="Where the 99k lines go. The solid bar is what the product uses with analysis off. Dashed bars are what the cleanup removes. Rounded; audit of 2026-10-10.">
        <WeightFigure />
      </Figure>

      <P>Five habits produced almost all of it. Here they are, worst first.</P>

      <H2 id="pass-through">1. A layer “to be safe”</H2>
      <P>
        Every request in INSIGHT passes through <C>insight_api_bridge.py</C>: 2,319 lines and 136 methods between the HTTP routes and the services that
        do the work. Here is one request, enabling a source, at both layers:
      </P>
      <Code caption="backend/main.py — the route">{`
@app.put("/api/sources/{source_id}/enabled")
async def set_source_enabled(source_id: str, body: dict):
    """Enable/disable a source. Body: {enabled: bool}"""
    try:
        return api_bridge.set_source_enabled(source_id, bool(body.get("enabled")))
    except Exception as e:
        logger.exception("Failed to set source enabled")
        return {"success": False, "error": str(e)}
`}</Code>
      <Code caption="backend/insight_api_bridge.py — the bridge it calls">{`
def set_source_enabled(self, source_id: str, enabled: bool) -> Dict[str, Any]:
    """Enable/disable a single source (durable to sources.json)."""
    try:
        self.sources_service.update_source_status(source_id, enabled)
        self._export_sources_json()
        return {"success": True, "source_id": source_id, "enabled": enabled}
    except Exception as e:
        return {"success": False, "error": str(e)}
`}</Code>
      <P>Three things are wrong, and none of them is visible from one file:</P>
      <List>
        <li><strong>The error is caught twice.</strong> The backend has 111 <C>except Exception</C> in the bridge and 123 in <C>main.py</C>.</li>
        <li><strong>Failure looks like success.</strong> Because nothing is raised, the client gets HTTP 200 with <C>success: false</C> inside. Every caller must remember to look.</li>
        <li><strong>The raw exception leaves the server.</strong> <C>str(e)</C> can carry a connection string. The feed routes had to grow their own redaction, and a test that checks it, because of exactly this.</li>
      </List>
      <Figure n={3} caption="The same request, before and after. The bridge adds a hop and a second catch, and turns a failure into a 200. After: the route calls the service; one handler owns every error.">
        <RequestPathFigure />
      </Figure>
      <P>
        FastAPI already has the senior version built in: raise the exception, and register one handler with <C>@app.exception_handler</C> that turns
        it into a real HTTP error (<Cite href={SRC.fastapiErrors}>FastAPI docs, Handling Errors</Cite>). Ousterhout calls this <em>defining errors out of
        existence</em>: handle a whole class of errors in one place, instead of at every call site.
      </P>
      <Compare
        beforeLabel="today: two catches per request"
        afterLabel="where we are heading"
        before={`
# route
try:
    return api_bridge.set_source_enabled(...)
except Exception as e:
    return {"success": False, "error": str(e)}

# bridge
try:
    self.sources_service.update_source_status(...)
    return {"success": True, ...}
except Exception as e:
    return {"success": False, "error": str(e)}
`}
        after={`
@app.exception_handler(Exception)
async def internal_error(request, exc):
    logger.exception("Request failed")
    return JSONResponse(
        status_code=500,
        content={"error": "internal_error"})

@app.put("/api/sources/{source_id}/enabled")
async def set_source_enabled(
        source_id: str, body: EnabledBody):
    return services.sources.set_enabled(
        source_id, body.enabled)
`}
      />
      <Takeaway>Apply the deletion test. Imagine deleting the module: if the complexity vanishes, it was a pass-through. Delete it.</Takeaway>

      <H2 id="copies">2. Copy the helper instead of giving it a home</H2>
      <P>When code needs something small, the fastest move is to paste it where you are. INSIGHT has:</P>
      <List>
        <li><strong>165</strong> calls to <C>psycopg.connect(</C> across 31 backend files, each one opening a brand-new connection to Postgres for a single query.</li>
        <li><strong>Nine</strong> repositories with the same private <C>_json_default</C>, each one a single line that calls the shared encoder.</li>
        <li><strong>72</strong> copy-pasted <C>catch</C> blocks in the frontend’s <C>api.ts</C>, which is 2,922 lines long.</li>
      </List>
      <Code caption="frontend/src/services/api.ts — two of the 72">{`
async getEnabledSources(): Promise<SourceStats> {
  try {
    const response =
      await this.makeRequest<SourceStats>('/api/enabled-sources');
    return response;
  } catch (error) {
    console.error('Failed to get enabled sources:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch sources'
    };
  }
}

async getSources(): Promise<SourceStats> {
  try {
    const response = await this.makeRequest<SourceStats>('/api/sources');
    return response;
  } catch (error) {
    console.error('Failed to get sources:', error);
    return {
      success: false,
      error: error instanceof Error ? error.message : 'Failed to fetch sources'
    };
  }
}
`}</Code>
      <P>
        Neither of these two methods has a caller anymore. That is the other cost of copies: nobody can tell which ones are still used. The senior
        practice is <strong>one home per concept</strong>. One database module owns connections, through a pool that commits on success and rolls back
        on error (<Cite href={SRC.psycopgPool}>psycopg, Connection pools</Cite>). One request helper owns errors in the frontend.
      </P>
      <Compare
        beforeLabel="today: posts_service.py, one of 165"
        afterLabel="where we are heading"
        before={`
def get_posts_by_date(self, date, ...):
    with psycopg.connect(self.db_url) as conn:
        with conn.cursor() as cur:
            return self.repo.get_posts_by_date(
                cur, date, ...)
`}
        after={`
# db.py: the one place connections come from
pool = ConnectionPool(DATABASE_URL, max_size=4)

# any service: borrow, use, give back
with pool.connection() as conn:
    with conn.cursor() as cur:
        ...  # commit or rollback: handled
`}
      />
      <Takeaway>
        One home per concept gives you <em>locality</em>. Pooling, timeouts and transactions change in one file, not 31. It also makes the next step
        possible: running the API and ingestion in one process means sharing one pool.
      </Takeaway>

      <H2 id="hidden">3. Hidden, not deleted</H2>
      <P>
        In Mark IX the owner decided INSIGHT is a reader first, and switched AI analysis off. The switch was implemented carefully. But look at the
        comment on it:
      </P>
      <Code caption="frontend/src/lib/features.ts">{`
 * processes posts (summaries, highlights, the intelligence inspector, notes and
 * chat, stories and related posts) is hidden unless the build sets
 * \`VITE_INSIGHT_ANALYSIS=on\`. Hidden, not deleted: the components stay.
`}</Code>
      <P>
        “The components stay” means about 28,700 lines are still built, tested and shipped, along with 31 database tables. Some of it still runs:
        every post saved during ingestion still computes “memory pivot” columns that only analysis ever read:
      </P>
      <Code caption="backend/insight_core/db/repo_posts.py:191 — on every saved post, analysis on or off">{`
memory_fields = build_post_memory_fields(post)
`}</Code>
      <P>
        Pete Hodgson’s guide to feature toggles is blunt about this. Release toggles are “transitionary by nature”; teams should treat toggles “as
        inventory which comes with a carrying cost” and be “proactive in removing feature flags that are no longer needed” (
        <Cite href={SRC.toggles}>Hodgson, Feature Toggles</Cite>). Martin Fowler names the cost: unused code “adds some complexity to the software”,
        and that complexity “makes it harder to modify and debug that software, thus increasing the cost of other features” (
        <Cite href={SRC.yagni}>Fowler, Yagni</Cite>).
      </P>
      <P>
        The senior practice: <strong>git is the archive.</strong> Tag the last commit that has the analysis code, then delete it from <C>main</C>. When analysis
        comes back in Mark X, it is rebuilt on today’s reading core, one feature at a time, each one earning its place. It is not restored wholesale.
      </P>
      <Takeaway>A flag that never turns back on is not a feature switch. It is dead code with a light switch on the wall.</Takeaway>

      <H2 id="dead">4. Code nobody runs, and code that lies</H2>
      <P>Some files survived only because nobody looked. Three examples:</P>
      <Code caption="backend/Dockerfile:21 — the image deletes code the repository keeps">{`
RUN rm -rf fastapi pydantic psycopg uvicorn.py dotenv
`}</Code>
      <P>
        Those are hand-written fake copies of real libraries, 711 lines, added so tests could run without installing anything. The image throws
        them away; outside Docker, they make tests pass or fail by accident.
      </P>
      <Code caption="backend/insight_core/tests/old tests/test_runner.py:30">{`
from main import InsightOperator
`}</Code>
      <P>
        <C>InsightOperator</C> has not existed for over a year. The folder name has a space, so the test runner never loads it: 886 lines of tests that
        cannot fail. And the sources API still reports <C>{'"version": "Mark VI"'}</C>, three Marks later.
      </P>
      <Takeaway>Every file in the tree should be load-bearing. If nothing imports it, nothing runs it, or it describes something gone — delete it.</Takeaway>

      <H2 id="restart">5. Rebuild instead of converge</H2>
      <P>
        Telegram fetching was rebuilt four times across the Marks. Each rebuild started over beside the last one, so the old paths lingered. Mark IX
        did the opposite, and it is the best-designed part of the codebase today. All fetching goes through one entry point:
      </P>
      <Code caption="backend/insight_core/ingestion/__init__.py">{`
async def run_ingestion(
    request: FetchRequest,
    *,
    progress: "Optional[ProgressSink]" = None,
    runner: "Optional[IngestionRunner]" = None,
) -> RunReport:
    """Run one fetch run. The caller owns the job:
    it finishes it with report.to_payload()."""
`}</Code>
      <P>
        Behind it, every source type is an adapter for one small interface, <C>SourceKind</C>. It has eight methods. Behind them sit politeness rules,
        host limits, archive paging, checkpoints and parsing for seven kinds of source.
      </P>
      <Figure n={4} wide caption="Depth is leverage at the interface. The bridge makes you learn 136 methods and does almost nothing behind them. SourceKind asks for 8 and hides seven fetch strategies.">
        <DepthFigure />
      </Figure>
      <P>
        This is what Michael Feathers calls a <em>seam</em>: “a place where you can alter behavior in your program without editing in that place” (
        <Cite href={SRC.seam}>Fowler, Legacy Seam</Cite>). It is a <em>real</em> seam because seven adapters fill it. A seam with one adapter is only a
        guess about the future. And now that the interface exists, the next change never needs a fifth rebuild. It needs Fowler’s strangler fig:
        “a gradual process of modernization”, moving behaviour behind the stable interface piece by piece instead of rewriting (
        <Cite href={SRC.strangler}>Fowler, Strangler Fig</Cite>).
      </P>
      <Takeaway>Do not restart. Put a deep interface where the change keeps happening, and move behaviour behind it one piece at a time.</Takeaway>

      <H2 id="switch">What we are switching to</H2>
      <P>The habits, the practices that replace them, and where each one lands in INSIGHT.</P>
      <div className="mt-6 overflow-x-auto lg:-mx-24">
        <table className="w-full border-collapse text-left text-[0.875rem] leading-[1.5]">
          <thead>
            <tr className="border-b border-line-strong text-[0.75rem] font-medium text-fg-3">
              <th className="py-2 pr-4 font-medium">Junior habit</th>
              <th className="py-2 pr-4 font-medium">Senior practice</th>
              <th className="py-2 font-medium">In INSIGHT</th>
            </tr>
          </thead>
          <tbody className="text-fg">
            {[
              ['Add a layer to be safe', 'Deep modules; delete pass-throughs', 'Delete the bridge; routes call services'],
              ['Catch everything, return success: false', 'Raise; handle errors in one place', 'One FastAPI exception handler'],
              ['Paste the helper where you are', 'One home per concept', 'One connection pool, one request helper'],
              ['Hide features behind a flag forever', 'Toggles are inventory; tag and delete', 'Retire analysis to a git tag'],
              ['Keep files just in case', 'Git is the archive; the deletion test', 'Remove dead code, stubs, stale docs'],
              ['Rebuild from scratch', 'Converge behind one seam', 'run_ingestion() and SourceKind'],
              ['Ship and move on', 'Lightweight is a budget; measure', 'Image 949 MB → 464 MB, then lines'],
              ['One big change', 'One slice, one commit, owner reviews', 'Issue 0003, eleven slices'],
            ].map(([habit, practice, here]) => (
              <tr key={habit} className="border-b border-line align-top">
                <td className="py-2.5 pr-4 text-fg-2">{habit}</td>
                <td className="py-2.5 pr-4 font-semibold">{practice}</td>
                <td className="py-2.5">{here}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <P>
        Some of this has already shipped. The backend image went from 949 MB to 464 MB by dropping unused packages, the build compiler and the
        Langfuse tracer. The rest is planned as eleven small slices in <C>plan/issues/0003-minimal-codebase.md</C>. Each one keeps reading working,
        runs every test, and is reviewed on its own.
      </P>

      <H2 id="practice">Check yourself</H2>
      <P>
        Answer from memory before scrolling back. Retrieving an idea is what makes it stick; rereading only makes it feel familiar. Come back to these
        in a few days and answer them again.
      </P>
      <Quiz questions={QUESTIONS} />

      <H2 id="cheat-sheet">Cheat sheet</H2>
      <dl className="mt-6 grid gap-x-6 gap-y-3 text-[0.9375rem] leading-[1.55] sm:grid-cols-[10rem_1fr]">
        {[
          ['Module', 'Anything with an interface and an implementation: a function, a class, a package.'],
          ['Interface', 'Everything a caller must know: signature, error modes, ordering, config, cost.'],
          ['Depth', 'Behaviour you get per unit of interface you learn. Deep: small interface, a lot behind it.'],
          ['Pass-through', 'A module whose methods mostly forward to another. Fails the deletion test.'],
          ['Deletion test', 'Imagine deleting it. Complexity vanishes → it was a pass-through. Reappears → it earns its keep.'],
          ['Seam', 'A place where behaviour can change without editing that place (Feathers).'],
          ['Adapter', 'One concrete thing that fills a seam. One adapter: a guess. Two: a real seam.'],
          ['Locality', 'A change, a bug fix, a test lives in one place, not many.'],
          ['Carrying cost', 'What unused code and old flags cost every future change (Fowler, Hodgson).'],
          ['Strangler fig', 'Replace a system gradually behind a stable interface, never by restart.'],
        ].map(([term, def]) => (
          <div key={term} className="contents">
            <dt className="font-semibold text-fg">{term}</dt>
            <dd className="text-fg-2">{def}</dd>
          </div>
        ))}
      </dl>

      <H2 id="read-next">Read next</H2>
      <P>
        <strong>Start here:</strong> <Cite href={SRC.ousterhoutTalk}>John Ousterhout, “A Philosophy of Software Design”, Talks at Google</Cite>. An hour. Deep
        classes, defining errors out of existence, and tactical vs strategic programming, all of which this article leans on. The book goes further
        (<Cite href={SRC.ousterhoutBook}>2nd edition, 2021</Cite>).
      </P>
      <List>
        <li><Cite href={SRC.seam}>Martin Fowler, Legacy Seam</Cite>: the seam idea from Feathers’ <em>Working Effectively with Legacy Code</em>.</li>
        <li><Cite href={SRC.toggles}>Pete Hodgson, Feature Toggles</Cite>: why flags must be removed, and how teams keep them few.</li>
        <li><Cite href={SRC.yagni}>Martin Fowler, Yagni</Cite>: the cost of build and the cost of carry.</li>
        <li><Cite href={SRC.strangler}>Martin Fowler, Strangler Fig</Cite>: modernising without a rewrite.</li>
      </List>
      <P className="text-fg-2">
        Something unclear, or want to try the deletion test on a file yourself? Ask your agent: it can walk you through any example here against the
        live code.
      </P>
    </>
  );
}
