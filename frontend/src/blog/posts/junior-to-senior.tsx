import { C, Cite, Code, Compare, Figure, H2, H3, List, P, Quiz, Takeaway, type QuizQuestion } from '../components';
import {
  CommitsFigure,
  DatabaseFigure,
  DepthFigure,
  GrowthFigure,
  ImageFigure,
  LinesFigure,
  RequestPathFigure,
  WeightFigure,
  WorkflowFigure,
} from '../figures';

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
  {
    prompt: 'The article reader was tested only on fixtures its authors wrote. What did it lose, unnoticed, for at least 18 days?',
    options: ['Every date written in prose', 'Every image inside an article', 'Every title longer than a line', 'Every post from Reddit feeds'],
    answer: 1,
    why: <>It kept only text blocks: headings, paragraphs, quotes and list items. 11 of 18 page-read posts had 0 images while their pages had 7 to 30. A corpus of real pages tests the site nobody thought of.</>,
  },
  {
    prompt: 'Two branches both add decision 025 to the log. When should a shared number be taken?',
    options: ['When the branch is created', 'When the owner pushes main', 'When the branch is merged', 'When the release is named'],
    answer: 2,
    why: <>At merge time only one branch can take the next number, so two cannot collide. Taken at branch time, every parallel branch sees the same “next” number — which is what happened to 025 and 026.</>,
  },
  {
    prompt: 'Two reviews of one evening found six bugs, a regression and a security exposure. When should they have run?',
    options: ['After the release went out', 'Once a month, in one batch', 'Only when the owner asks', 'On each branch, before merging'],
    answer: 3,
    why: <>The feed finder was merged 46 minutes before its review was recorded. Reviewing the branch first keeps findable bugs off main, and keeps each fix next to its change.</>,
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
      <P className="text-[1rem] text-fg-2">
        <strong className="text-fg">Updated 28 October 2026.</strong> Sections 1–7 are as written on 11 October; issue 0005 has since been built (12
        October). Two parts are new: <a href="#workflow" className="text-link">section 8</a>, how an issue moves through the repository now, from
        something the owner noticed to a release, and <a href="#speed" className="text-link">section 9</a>, how fast we ship, measured from git, and
        whether that is good.
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

      <H2 id="workflow">8. How an issue moves now</H2>
      <P>
        Sections 1–7 describe the code. This one describes the process that changes it, because that process changed too. In October INSIGHT
        stopped being built one Mark at a time and started being built one issue at a time: 30 issues, 0007 to 0036, in the last two weeks. Each
        one passes the same steps, and each step leaves something in git you can read afterwards.
      </P>
      <Figure n={7} wide caption="The loop every issue goes through since 16 October. The loudest box is the step that caught the most: two independent reviews, whose findings became an issue of their own (0029).">
        <WorkflowFigure />
      </Figure>

      <H3>An issue is a file, and its first line says where it stands</H3>
      <P>
        There is no tracker. An issue is one markdown file in <C>plan/issues/</C>, numbered, with a <C>Status:</C> line — <em>discussion</em>,
        <em> ready-for-agent</em>, <em>built</em>, <em>built, not deployed</em>, <em>done</em> — and the <C>README.md</C> beside them lists them all. When the
        owner decides something, the issue quotes the owner, word for word, with the date:
      </P>
      <Code caption="plan/issues/0036-source-doctor.md" lang="text">{`
Status: **ready-for-agent** (owner, 2026-10-28: "our checker of sources
should check if that old source is working, if not it should automatically
run our feed finder or follow page and find all the posts"; "everything
your pick").
`}</Code>
      <P>
        Most issues start as something the owner noticed while reading. On 16 October one commit (<C>3c0c157</C>) turned a list of observations
        from the server into eight specs, 0007 to 0014. Not every observation becomes work: 0013, priority order, was moved to “discussion
        (future)” two minutes later, and 0025, Reddit ending its RSS, is recorded as “decided: no change”. A spec says what is wrong, what to
        build, how it will be tested, and often what was measured first. Then a review reads the spec before anyone builds it (<C>524c7d0</C>,
        “Apply the spec review to issues 0007–0014”).
      </P>

      <H3>Agents build in parallel, each in its own worktree</H3>
      <P>
        A ready spec goes to an implementer agent. Each agent gets its own <C>git worktree</C>: a separate checkout on its own branch, so four agents
        can build four issues at once without touching each other’s files or the main checkout. Each writes the tests first, then the code, then
        runs the whole suite, the type check, lint and the build — the same checks this post had to pass. Then the branch is merged, and when two
        branches touched the same file, the conflict is resolved at the merge. On 16 October four merges landed between 16:20 and 16:26.
      </P>

      <H3>Two reviews, and their findings become an issue</H3>
      <P>
        After a batch is merged, two read-only review agents look at the whole range. One checks it against the minimal-codebase standard of issue
        0005: is anything here bigger than it needs to be? The other checks correctness and security, and has to reproduce each finding or trace
        it to a file and line. On the evening of 27 October they reviewed <C>0b1458d..1c07573</C>, and their findings were committed as issue
        0029: 16 correctness findings, 9 of them marked must-fix, and about 360 lines of overengineering. Each fix commit names its finding, and the
        issue says what was done with every one, including the four it skipped.
      </P>

      <H3>Real sites, a preview, and a version line</H3>
      <P>
        Unit tests run on fixtures. INSIGHT reads other people’s websites, so fixtures are not enough, and every source feature is checked live:
        the feed finder on ten named sites, the page watcher on Anthropic, Cohere, x.ai and Pipecraft, each result written into the issue with its
        request count and time. A regression run of the page watcher over 32 real sites found a crash that no unit test had: one of
        deepmind.google’s sitemaps was not valid XML, and the parser reports that at a different call than the guard expected.
      </P>
      <Code caption="backend/insight_core/ingestion/kinds/page_watch.py — the fix, 94b9457" lang="diff">{`
     try:
         parser.feed(body)
+        # The parser reports a broken document here, at the read, after the events before it.
+        for event, node in parser.read_events():
+            ...
     except ET.ParseError:
         pass
-    for event, node in parser.read_events():
-        ...
`}</Code>
      <P>
        Before anything is deployed, it runs on a preview: the same containers, on a copy of the real database. That is where the illogicalities
        audit (0027, 22 findings) clicked through every page, and where the missing images below were measured. Finally, a repo-root
        <C> VERSION</C> file names the release, and the build stamps it into a line at the bottom of the Ingestion tab (issue 0020), so the owner
        can see what runs instead of guessing:
      </P>
      <Code caption="Sources → Ingestion, the version line (issue 0020)" lang="text">{`
I.N.S.I.G.H.T. Mark IX v9.1 · b9fcc6e · 27 Oct 2026
`}</Code>
      <P>
        Agents do not push. The owner does, and deploys. While v9.2 shipped, five more issues (0022, 0030, 0031, 0033, 0034) were built on their own
        branches on 28 October and held there, merged into nothing, for v9.3.
      </P>

      <H3>Traced end to end: the feed finder (0026)</H3>
      <List>
        <li><strong>The question.</strong> Add source accepted only a feed address; pasting an article page added a source that could never fetch. The owner wanted the finder as fast and as accurate as possible.</li>
        <li><strong>Measure first.</strong> A throwaway prototype ran on 40 real pages. It found that the standard <C>{'<link rel="alternate">'}</C> is not enough (borretti.me, Old New Thing and Martin Fowler only have a visible “RSS” link), that a feed must never be downloaded whole (danluu.com’s is 6.6 MB, Project Zero’s 11 MB; the first 16 KB prove it), and that guessing paths one by one took 10.8 s on Ars Technica.</li>
        <li><strong>Spec.</strong> Those measurements became the design: cheapest stage first, stop at the first stage that finds something, 5 s per request, 10 s overall. Committed at 22:11 on 27 October.</li>
        <li><strong>Build.</strong> An agent built it test-first in a worktree; merged at 22:27.</li>
        <li><strong>Live check.</strong> All ten sites named in the spec answered as expected, from 1 request and 0.6 s (Medium) to 11 requests and 1.9 s (anthropic.com/news, correctly “none”).</li>
        <li><strong>Review.</strong> The correctness review found that a slow answer for an address could overwrite what you had typed since, and that the finder leaked threads past its 10 s budget. Both fixed in 0029 and shipped in v9.2.</li>
      </List>

      <H3>Traced end to end: the missing images (0032)</H3>
      <P>
        Early on 28 October the owner compared an Anthropic post on anthropic.com with INSIGHT’s copy. INSIGHT’s had no images, and it opened with
        “Chapter 01: Connecting people to trusted sources”, a line from the page’s sticky table of contents. The cause was one line in the shared
        article reader, which keeps only text blocks:
      </P>
      <Code caption="backend/insight_core/ingestion/kinds/parsing.py, extract_article_html, as of 6d92a20 (9 October)" lang="python">{`
blocks = re.findall(
    r"(?is)<(?:h1|h2|h3|p|blockquote|li)[^>]*>.*?</(?:h1|h2|h3|p|blockquote|li)>",
    candidate)
...
return "\\n".join(blocks)
`}</Code>
      <P>
        No <C>img</C>, no <C>figure</C>. Then, instead of fixing the one post, the size of the problem was measured: 18 random page-read posts on the
        preview, read again. 11 of the 18 had been stored with 0 images while their pages had 7 to 30. The fix (<C>99f4b5d</C>, <C>251ba1a</C>) keeps
        images in page order and treats a table of contents as chrome. The issue then asks the harder question, why nobody saw it, and answers it
        plainly: the reader was tested “only on small hand-written fixtures. A fixture tests the rule its author thought of, never the site that
        breaks it.” The prevention was built the same day (<C>c82ff9b</C>, <C>e26f223</C>): a corpus of 24 real pages, each with its expected
        title, first and last sentence, hand-counted image count and words that must not appear, run on every reader change. Building it found
        more of the same class of bug, and the reader went from 93 to 113 of 123 expectations met; ten checks stay recorded as known gaps that
        must fail until fixed. Every page read now also records how many images the article had and kept, so the next loss shows in a
        source’s health instead of waiting for someone to look.
      </P>
      <P>
        Two checks guard the guard. The corpus was measured against two proven extractors on the same pages: INSIGHT’s reader met 89 of 99
        checks, readability-lxml 79 and trafilatura 74 (both mostly lose images), so neither was adopted. And because the corpus is what the
        fixes were tuned on, the old and new readers were run on 48 real pages <em>outside</em> it: 31 kept exactly the same text, total text
        rose from 375,000 to 383,000 characters, and of 18 sentences no longer kept, 17 were clutter (footers, “Next / Previous”, a sponsor
        box, a writer’s biography). The eighteenth was a real subtitle on the Google blog, removed by a rule written the day before; it was
        fixed with a test (<C>f86cb4d</C>). That is the honest shape of the speed: a fix shipped one loss, and the next check caught it.
      </P>

      <H3>What went wrong in the workflow itself</H3>
      <List>
        <li><strong>Stale bases.</strong> A new worktree can start from an old commit. This update’s own worktree started four commits behind <C>main</C>, and the first instruction it got was to check that and reset. Without the check, an agent builds on code that has already changed.</li>
        <li><strong>Parallel branches claim the same numbers.</strong> The design decision log is numbered. Two of the branches held for v9.3 both add decision <strong>025</strong> (read later in 0022, continue where I stopped in 0030), and two others both add <strong>026</strong> (0033 and 0034). Migration numbers are the same kind of shared counter, and need the same care at merge.</li>
        <li><strong>A fix that broke something else.</strong> <C>1c07573</C> fixed DeepMind pages, whose posts start with small <C>{'<article>'}</C> cards, by taking the first candidate long enough. It also made the reader fall back to the whole page body, so a short RSS post could be replaced by the entire page, related links included. Its own test passed. The review caught it (0029, finding 10), and <C>d13290c</C> fixed it 1 h 44 min later.</li>
        <li><strong>Reviews after the merge, not before.</strong> The feed finder was merged 46 minutes, and the page watcher 20 minutes, before the reviews that found their bugs were committed. In between, main carried bugs nobody knew about yet.</li>
        <li><strong>A flaky test.</strong> One test passed or failed depending on timing. A red run that might be noise teaches everyone to rerun instead of read.</li>
      </List>
      <Takeaway>
        The loop works because each step writes something down: the owner’s words in the issue, the measurement in the spec, the finding in the
        review issue, the fix in a commit that names it, the release in VERSION. The weak points are the shared ones: a base, a number, an order of
        merge and review.
      </Takeaway>

      <H2 id="speed">9. How fast we ship, and is that good?</H2>
      <P>
        The loop is fast. How fast is a question for git, not for memory. All numbers below are from <C>main</C> at <C>7584ff7</C>, committer dates
        and times (UTC+4), lockfiles and images left out of line counts.
      </P>
      <Figure n={8} wide caption="Commits per day on main, 9–28 October (merges included). The work comes in bursts, not a steady pace: 125 commits in the last two weeks, all of them on 16, 27 and 28 October.">
        <CommitsFigure />
      </Figure>
      <List>
        <li><strong>Commits.</strong> 125 in the last two weeks (111 changes, 14 merges): 39 on 16 October, 55 on 27 October, 31 on 28 October, none on the other eleven days. All 55 of 27 October landed between 20:07 and 23:14. Averaged, that is about 9 a day; it never happened that way.</li>
        <li><strong>Issues.</strong> 30 opened (0007–0036), on the same three days. Of the 26 on <C>main</C>, 18 are built or have a first version built, 1 is half built (0012) and 7 are not (discussion, future, a decided “no change”, and three ready for an agent). The other 4, and 0022, are built on branches waiting for v9.3.</li>
        <li><strong>Lines.</strong> +9,488 and −3,861, net +5,627. The tree held 64,824 lines when issue 0005 was merged on 12 October; it holds 71,077 now. Half the net growth is tests.</li>
        <li><strong>Releases.</strong> v9.1 at 20:57 on 27 October (when the VERSION file arrived; the server’s earlier build counts as v9.0), and v9.2 at 01:07 on 28 October: 4 h 9 min apart. The image fix landed 42 minutes after the v9.2 commit; the owner pushed <C>main</C> up to it.</li>
      </List>
      <Figure n={9} caption="Net lines added on main in the last two weeks, by kind. Tests grew the most; code and config grew by less than half of what was added, because 2,849 lines left.">
        <LinesFigure />
      </Figure>

      <H3>From noticed to built</H3>
      <P>
        Commit times record when work landed, not when thinking started, so these are the visible part of each story.
      </P>
      <div className="mt-6 overflow-x-auto lg:-mx-24">
        <table className="w-full border-collapse text-left text-[0.875rem] leading-[1.5]">
          <thead>
            <tr className="border-b border-line-strong text-[0.75rem] font-medium text-fg-3">
              <th className="py-2 pr-4 font-medium">Issue</th>
              <th className="py-2 pr-4 font-medium">From</th>
              <th className="py-2 pr-4 font-medium">To</th>
              <th className="py-2 font-medium">Elapsed</th>
            </tr>
          </thead>
          <tbody className="text-fg">
            {[
              ['0007–0014, the owner’s server notes', 'specs, 16 Oct 16:00', 'last merge 16:26, review fixes 16:43', '43 min'],
              ['0026, the feed finder', 'spec, 27 Oct 22:11', 'merged 22:27', '16 min'],
              ['0029, the review findings', 'recorded, 27 Oct 23:13', 'both halves merged 00:56', '1 h 43 min'],
              ['0032, the missing images', 'the reader as of 9 Oct 19:15', 'fixed, 28 Oct 01:49', 'at least 18 days'],
              ['0022, bookmarks', 'owner asks, 16 Oct', 'decided 28 Oct 01:47, built on a branch', '12 days, by choice'],
            ].map(([issue, from, to, elapsed]) => (
              <tr key={issue} className="border-b border-line align-top">
                <td className="py-2.5 pr-4 font-semibold">{issue}</td>
                <td className="py-2.5 pr-4 text-fg-2">{from}</td>
                <td className="py-2.5 pr-4 text-fg-2">{to}</td>
                <td className="py-2.5 tabular-nums">{elapsed}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <P>
        The two slow rows are the instructive ones. Bookmarks took twelve days on purpose: the owner asked “first discuss how bookmarks should
        work”, and the issue stayed in discussion until the model was decided. The images took eighteen days by accident: the bug was live, and
        nothing was looking.
      </P>

      <div className="mt-8 grid gap-4 lg:-mx-24 lg:grid-cols-2">
        <section className="rounded-md border border-fg p-4">
          <h3 className="text-[1rem] font-semibold text-fg">What speed bought</h3>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-[1.55] text-fg marker:text-fg-3">
            <li><strong>Feedback turned into features the same evening.</strong> The owner’s notes of 16 October were built and reviewed within the hour; the feed finder went from spec to merge in 16 minutes, after a 40-page prototype.</li>
            <li><strong>Testing on the real web, not on guesses.</strong> 40 pages measured before the finder, 10 sites checked after it, 18 stored posts re-read before deciding how bad the image loss was.</li>
            <li><strong>Small, named commits.</strong> 111 changes in two weeks, each one sentence about what changed. A fix and its finding can be found, read and reverted alone.</li>
            <li><strong>Tests grew fastest.</strong> 2,816 of the 5,627 net new lines are tests.</li>
            <li><strong>Dead code found sooner.</strong> The review removed a YouTube path in Add source that no caller could reach, built on code from March (−145 lines); the 0005 cleanup had not caught it.</li>
          </ul>
        </section>
        <section className="rounded-md border border-dashed border-line-strong p-4">
          <h3 className="text-[1rem] font-semibold text-fg">What it cost</h3>
          <ul className="mt-3 list-disc space-y-2 pl-5 text-[0.9375rem] leading-[1.55] text-fg marker:text-fg-3">
            <li><strong>A silent bug lived for weeks.</strong> Every article read from its page lost its images from at least 9 October to 28 October, through issue 0008’s full-text cleanup on 16 October, which touched the same reader.</li>
            <li><strong>One evening, many bugs.</strong> The reviews of 27 October’s work found six bugs, one regression and one security exposure: two new routes were an unauthenticated fetch proxy that accepted <C>file://</C> and returned a site’s error body to the caller.</li>
            <li><strong>Churn.</strong> Removing the Reddit “Fetch comments” button (0027) at 22:35 orphaned its whole backend, route, job and scraper, until the review removed it at 00:48 (−177 lines).</li>
            <li><strong>Open ends.</strong> Four correctness findings were skipped in that pass (a 429 that discards posts already read, followed pages lost on a rebuild from sources.json, two nits).</li>
            <li><strong>The weight comes back.</strong> The 0005 target was 55–60k lines; it landed at 65k, and two weeks later the tree is at 71k. The reader’s JS is 485,552 bytes, 0.31% over its baseline: a third of its 1% budget used since 12 October.</li>
          </ul>
        </section>
      </div>

      <H3>What makes speed useful here, rather than reckless</H3>
      <P>
        Speed is cheap when mistakes are cheap to find and cheap to undo. In INSIGHT that is true only where something is watching. Reviews
        found the regression, the security exposure and the dead code within hours. A preview with real data showed the image loss as a number
        (11 of 18) instead of an anecdote. Versioned releases say which mistakes are on the server. Where nothing watched — a reader heuristic tested
        on hand-written fixtures — the same speed let a bug live for eighteen days.
      </P>
      <P>
        <strong>The verdict:</strong> fast is right for a single-user tool that one owner reads every day and redeploys with one command. But on 27
        October the work went faster than its checks. Four changes, all small:
      </P>
      <List>
        <li><strong>Review before merge.</strong> Run both reviews on each branch, and merge after its must-fix findings are fixed, not 20–46 minutes before they are known.</li>
        <li><strong>Fewer parallel branches per release.</strong> Five branches held for v9.3 already collide on two decision numbers. Take shared numbers (decisions, migrations) at merge time, not at branch time, and keep a release to what can be reviewed in one sitting.</li>
        <li><strong>The corpus is a gate.</strong> No change to the article reader merges unless all the real pages in the 0032 corpus still read as expected.</li>
        <li><strong>Make silent losses loud.</strong> Record, per page read, how many images the page had and how many were kept (0032, step 2), so the next eighteen-day bug is a warning on day one.</li>
      </List>
      <Takeaway>
        Speed is a multiplier, not a virtue. It multiplies whatever checks you have. Measure the pace from git, put the checks before the merge,
        and give every heuristic a corpus of the real world to fail against.
      </Takeaway>

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
              ['Fix what was reported, in place', 'An issue file: the owner’s words, a Status line', 'plan/issues, 0007–0036'],
              ['Test on the fixture you wrote', 'Test on real pages, kept as a corpus', 'Issue 0032: 24 pages, 93 → 113 of 123 checks'],
              ['Review after it is merged', 'Review each branch before it merges', 'Issue 0029, the lesson'],
              ['Ship whatever is on main', 'A version line says what runs', 'VERSION, Mark IX v9.2 (0020)'],
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
        <C>plan/issues/0005-minimal-codebase.md</C>. Each one keeps reading working, runs every test, and is reviewed on its own. (Update, 28
        October: all eleven were built on 12 October; the last four rows of the table come from sections 8 and 9.)
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
          ['Status line', 'The first line of an issue file: where it stands, and the owner’s decision in the owner’s own words.'],
          ['Worktree', 'A second checkout of the same repository on its own branch, so agents build in parallel without colliding.'],
          ['Corpus', 'Real pages kept as test fixtures, with what each must read as. It catches the site a hand-written fixture never imagined.'],
          ['Version line', 'What runs, stamped at build: Mark, release, commit, date. The answer to “is my fix deployed?”'],
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
