import { C, Cite, Code, Compare, Figure, H2, H3, List, P, Quiz, Takeaway, type QuizQuestion } from '../components';
import { DatabaseFigure, DepthFigure, GrowthFigure, ImageFigure, RequestPathFigure, WeightFigure } from '../figures';

const SRC = {
  ousterhoutTalk: 'https://www.youtube.com/watch?v=bmSAYlu0NcY',
  ousterhoutBook: 'https://web.stanford.edu/~ouster/cgi-bin/book.php',
  seam: 'https://martinfowler.com/bliki/LegacySeam.html',
  yagni: 'https://martinfowler.com/bliki/Yagni.html',
  toggles: 'https://martinfowler.com/articles/feature-toggles.html',
  strangler: 'https://martinfowler.com/bliki/StranglerFigApplication.html',
  fastapiErrors: 'https://fastapi.tiangolo.com/tutorial/handling-errors/',
  psycopgPool: 'https://www.psycopg.org/psycopg3/docs/advanced/pool.html',
  multiStage: 'https://docs.docker.com/build/building/multi-stage/',
  legacyGenai: 'https://pypi.org/project/google-generativeai/',
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
  {
    prompt: <>Every package installs from a prebuilt wheel, yet the image ships <C>gcc</C>. What is the compiler doing there?</>,
    options: ['Compiling the Postgres database driver', 'Speeding up the Python runtime', 'Nothing; it is unused weight', 'Building the React frontend assets'],
    answer: 2,
    why: <>Nothing compiles at install time, which is why the image built and every test passed without it. A compiler in a runtime image is only weight and attack surface; if a build really needs one, use a multi-stage build.</>,
  },
  {
    prompt: 'The retirement migration drops 31 tables. What makes that step safe to take?',
    options: ['Leaving the feature flag on', 'Commenting the code out first', 'Copying the tables into JSON', 'A git tag and a backup'],
    answer: 3,
    why: <>The tag keeps the code readable and the backup keeps the data restorable. A flag or commented-out code is the dormant weight we are removing; neither one brings back a dropped table.</>,
  },
];

export default function JuniorToSenior() {
  return (
    <>
      <P className="mt-0 text-[1.1875rem] text-fg-2">
        In sixteen months INSIGHT grew from 964 lines to 99,059. About half of that is weight we carry and never use. This is the story of how
        that happened, the junior habits that caused it, and the senior practices we are switching to — with real code from this repository, the
        image diet that already shipped, and the decision to retire analysis.
      </P>

      <Figure n={1} caption="Tracked lines at the last commit of each Mark (lockfiles and images excluded). The dashed bar is where the cleanup in issue 0005 should land.">
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
      <Code caption="backend/main.py — the route" lang="python">{`
@app.put("/api/sources/{source_id}/enabled")
async def set_source_enabled(source_id: str, body: dict):
    """Enable/disable a source. Body: {enabled: bool}"""
    try:
        return api_bridge.set_source_enabled(source_id, bool(body.get("enabled")))
    except Exception as e:
        logger.exception("Failed to set source enabled")
        return {"success": False, "error": str(e)}
`}</Code>
      <Code caption="backend/insight_api_bridge.py — the bridge it calls" lang="python">{`
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
        lang="python"
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
      <Code caption="frontend/src/services/api.ts — two of the 72" lang="ts">{`
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
        lang="python"
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
      <Code caption="frontend/src/lib/features.ts" lang="comment">{`
 * processes posts (summaries, highlights, the intelligence inspector, notes and
 * chat, stories and related posts) is hidden unless the build sets
 * \`VITE_INSIGHT_ANALYSIS=on\`. Hidden, not deleted: the components stay.
`}</Code>
      <P>
        “The components stay” means about 28,700 lines are still built, tested and shipped, along with 31 database tables. Some of it still runs:
        every post saved during ingestion still computes “memory pivot” columns that only analysis ever read:
      </P>
      <Code caption="backend/insight_core/db/repo_posts.py:191 — on every saved post, analysis on or off" lang="python">{`
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
        comes back in Mark X, it is rebuilt on today’s reading core, one feature at a time, each one earning its place. It is not restored wholesale. On
        11 October the owner made that call; <a href="#retire" className="text-link">section 7</a> weighs what it gains and what it costs.
      </P>
      <Takeaway>A flag that never turns back on is not a feature switch. It is dead code with a light switch on the wall.</Takeaway>

      <H2 id="dead">4. Code nobody runs, and code that lies</H2>
      <P>Some files survived only because nobody looked. Three examples:</P>
      <Code caption="backend/Dockerfile:21 — the image deletes code the repository keeps" lang="dockerfile">{`
RUN rm -rf fastapi pydantic psycopg uvicorn.py dotenv
`}</Code>
      <P>
        Those are hand-written fake copies of real libraries, 711 lines, added so tests could run without installing anything. The image throws
        them away; outside Docker, they make tests pass or fail by accident.
      </P>
      <Code caption="backend/insight_core/tests/old tests/test_runner.py:30" lang="python">{`
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
      <Code caption="backend/insight_core/ingestion/__init__.py" lang="python">{`
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

      <H2 id="optimization">6. The image diet: 949 MB to 464 MB</H2>
      <P>
        Before touching the structure, we made the cheapest cut first: the backend Docker image. One commit removed 336 lines and changed 9, and
        the image lost half its weight. Every finding in it is a habit worth unlearning.
      </P>
      <Figure n={5} caption="The backend image through the optimization pass, measured with docker images. Python packages alone went from 332 MB to 133 MB. All 460 backend tests passed inside the new image.">
        <ImageFigure />
      </Figure>

      <H3>Lesson 1: measure before you cut, and after</H3>
      <P>
        “The image feels big” is not a finding. <C>docker images</C> said 949 MB; <C>du</C> on the installed packages said 332 MB of them was Python
        libraries. After each cut we measured again, and then ran the whole test suite <em>inside the new image</em>, because the image is what ships,
        not your laptop. A cut you have not measured is a guess; a cut you have not tested in the real artifact is a risk.
      </P>

      <H3>Lesson 2: a dependency stays only if something imports it</H3>
      <Code caption="backend/requirements.txt — the eight lines nothing imported" lang="diff">{`
-feedparser
-youtube-transcript-api
-praw
-asyncpraw
-markdown
-pymdown-extensions
-google-generativeai
-langfuse>=4,<5
`}</Code>
      <P>
        Each line was added for a reason once, and never removed when the reason left. Two are telling. <C>praw</C> and <C>asyncpraw</C> are the
        sync and async versions of the same Reddit library, and neither was used. <C>google-generativeai</C> is Google’s old SDK, installed next to
        its replacement <C>google-genai</C>; its own page says “All support for this repository ended permanently on November 30, 2025” (
        <Cite href={SRC.legacyGenai}>PyPI, google-generativeai</Cite>). Every dependency costs install size, upgrade work and attack surface, so
        the check is mechanical: grep for the import. No import, no line.
      </P>

      <H3>Lesson 3: build tools do not belong in the runtime image</H3>
      <P>
        The image installed <C>gcc</C>, a C compiler. Nothing needed it: every package installs from a prebuilt wheel, and the proof is that the
        image built and all tests passed without it. A compiler in a production image is weight the app never uses, and one more tool for
        anyone who breaks in. Docker’s own docs describe the pattern for when you <em>do</em> need one: build in one stage and copy only the result out, so
        “none of the build tools required to build the application are included in the resulting image” (
        <Cite href={SRC.multiStage}>Docker docs, Multi-stage builds</Cite>).
      </P>

      <H3>Lesson 4: a tool that can never fail can also never help</H3>
      <P>The Langfuse tracer was 217 lines wrapped around every Gemini call. Its own header explains the problem:</P>
      <Code caption="backend/insight_core/observability/langfuse_tracer.py (deleted)" lang="comment">{`
Everything here is wrapped so tracing can NEVER break a briefing: if Langfuse is
disabled, misconfigured, the SDK is missing, or the host is unreachable, every
function degrades to a no-op.

... for self-hosted hosts (.local / localhost / private IPs) we force
\`verify=False\` at the requests layer
`}</Code>
      <P>
        Read that twice. When anything is wrong, the tracer silently does nothing, so nobody learns it is broken. To reach a self-hosted server it
        switched off TLS certificate checks. And it needed an extra host entry in Docker Compose. Observability earns its place only if someone
        reads it and it fails loudly when it stops working; this one did neither, so it went.
      </P>

      <H3>Lesson 5: one way to build</H3>
      <P>
        The repository root had a second <C>Dockerfile</C> that installed Node into a Python image and ran the API next to the Vite
        <em> development</em> server, plus a root <C>requirements.txt</C> that still listed LangChain. The docs told readers to install from it. Two
        entry points, and the wrong one looked official. Deleting both made the real build, <C>docker compose up</C>, the only build.
      </P>
      <Takeaway>Weight hides where nobody re-checks: requirement files, base images, wrappers, old entry points. Measure, grep, delete, then verify inside the artifact you ship.</Takeaway>

      <H2 id="retire">7. Retiring analysis: the good and the bad</H2>
      <P>
        On 11 October 2026 the owner decided: analysis is retired <strong>completely</strong>, and better analysis will be built later. Briefings,
        stories, the inbox, topics, entity and event memory, evidence, experts, milestones and track briefings all leave <C>main</C>. Deleting is a
        decision with costs, so a senior writes both columns down before cutting.
      </P>
      <Figure n={6} caption="Table sizes on a local copy of the database (7,102 posts). Analysis tables hold 208 of 282 MB, 74%. The entity tables alone are almost three times the posts table.">
        <DatabaseFigure />
      </Figure>
      <div className="mt-8 grid gap-4 lg:-mx-24 lg:grid-cols-2">
        <section className="rounded-md border border-fg p-4">
          <h3 className="text-[1rem] font-semibold text-fg">What it gains</h3>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-[1.55] text-fg marker:text-fg-3">
            <li><strong>About 28,700 lines</strong> and their tests leave every build, test run and refactor.</li>
            <li><strong>The database shrinks by about three quarters</strong>: 31 tables, 208 of 282 MB on the local copy.</li>
            <li><strong>Ingestion does less per post</strong>: no more “memory pivot” columns computed on every save.</li>
            <li><strong>No stale answers</strong>: about 37 analysis routes that were never gated stop serving data nobody updates.</li>
            <li><strong>A lighter image</strong>: the Gemini SDK leaves, and so does the Gemini key in Connections.</li>
            <li><strong>One app, one mode</strong>: every screen has one behaviour to test, not two.</li>
            <li><strong>A clean start for Mark X</strong>: new analysis is designed on the reading core, not around the old one.</li>
          </ul>
        </section>
        <section className="rounded-md border border-dashed border-line-strong p-4">
          <h3 className="text-[1rem] font-semibold text-fg">What it costs</h3>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-[1.55] text-fg marker:text-fg-3">
            <li><strong>Working features disappear for a while</strong>, including some the owner likes: milestones and track briefings. Their <em>ideas</em> are not lost: they are written down as issues, to be built again, better.</li>
            <li><strong>Data is dropped</strong>: the entity graph and the archive of past briefings. Rebuilding them costs compute and model tokens.</li>
            <li><strong>The tag is not an undo button.</strong> Once the bridge and the connection code change, the old code will not drop back in. The tag is reading material.</li>
            <li><strong>Some work will be redone.</strong> That cost was paid when it was built; keeping dead code does not get it back.</li>
            <li><strong>Hidden couplings can break reading</strong>: ingestion still imports the memory services, and posts still carry analysis columns.</li>
          </ul>
        </section>
      </div>
      <H3>How the costs are contained</H3>
      <List>
        <li><strong>Keep the ideas, not the code:</strong> what the owner liked is recorded in <C>plan/issues</C>: entity pages with milestones (0001), a readable track briefing (0002) and a citation graph between posts (0004). Each one comes back as new work on the reading core.</li>
        <li><strong>Reversible where it can be:</strong> a git tag for the code and a database backup before the migration that drops the tables.</li>
        <li><strong>Port before cut:</strong> archive backfill and the ingestion log viewer move into the Ingestion tab first, because they are reading tools that only lived on an analysis page.</li>
        <li><strong>One fixed test surface:</strong> the <C>run_ingestion()</C> tests stay unchanged through every slice. If they stay green, reading did not move.</li>
        <li><strong>Small slices:</strong> backend, frontend and schema are cut separately, and the owner reviews each one.</li>
        <li><strong>A rule for coming back:</strong> a new analysis feature ships only with a reading test it passes, so Mark X earns what Mark VII assumed.</li>
      </List>
      <Takeaway>Deleting is a decision, not a cleanup. Write down what it gains and what it costs, keep the ideas you still want as issues, make it reversible where you can, and say plainly where you can’t.</Takeaway>

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
              ['Install it in case we need it', 'A dependency stays only if imported', 'Eight unused packages removed'],
              ['Ship the compiler with the app', 'The runtime image holds only what runs', 'gcc removed from the image'],
              ['Wrap a tool so it never fails', 'Fail loudly, or remove the tool', 'The Langfuse tracer deleted'],
              ['Keep a feature because it was built', 'Weigh gains and costs, then cut', 'Analysis retired, tag and backup'],
              ['One big change', 'One slice, one commit, owner reviews', 'Issue 0005, eleven slices'],
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
        The image diet has shipped. The rest, including the analysis retirement, is planned as eleven small slices in
        <C>plan/issues/0005-minimal-codebase.md</C>. Each one keeps reading working, runs every test, and is reviewed on its own.
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
          ['Runtime image', 'What ships and runs. Build tools (compilers, dev servers) stay in a build stage.'],
          ['Reversible step', 'A cut you can undo: a git tag for code, a backup for data. Say so when a cut is not reversible.'],
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
        <li><Cite href={SRC.multiStage}>Docker docs, Multi-stage builds</Cite>: keeping build tools out of the image you ship.</li>
      </List>
      <P className="text-fg-2">
        Something unclear, or want to try the deletion test on a file yourself? Ask your agent: it can walk you through any example here against the
        live code.
      </P>
    </>
  );
}
