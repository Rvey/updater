import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  ArrowUpRight,
  Check,
  Copy,
  Github,
  Menu,
  X,
} from "lucide-react";
import "./homepage.css";

export const CONNECT_CMD = "curl -fsSL https://updaterapi.blitzgo.io/connect.sh | bash";
export const LINKS = {
  github: "https://github.com/Rvey/updater",
  mit: "https://github.com/Rvey/updater/blob/main/LICENSE",
  api: "https://updaterapi.blitzgo.io",
  docs: "https://updaterapi.blitzgo.io/docs",
  mcp: "https://updaterapi.blitzgo.io/mcp",
  app: "/app",
};

async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const field = document.createElement("textarea");
      field.value = value;
      field.style.position = "fixed";
      field.style.opacity = "0";
      document.body.appendChild(field);
      field.select();
      const ok = document.execCommand("copy");
      field.remove();
      return ok;
    } catch { return false; }
  }
}

function CommandBlock({ caption, dark }: { caption: string; dark?: boolean }) {
  const [copied, setCopied] = useState(false);
  const liveRef = useRef<HTMLSpanElement>(null);
  const onCopy = async () => {
    const ok = await copyText(CONNECT_CMD);
    if (ok) {
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    }
  };
  return (
    <div>
      <div className={dark ? "mk-cmd-block light-on-dark" : "mk-cmd-block"} role="group" aria-label="Connect command">
        <div className="mk-cmd-top">
          <span className="mk-traffic" aria-hidden="true">
            <i style={{ background: "#FF5F57" }} /><i style={{ background: "#FEBC2E" }} /><i style={{ background: "#28C840" }} />
          </span>
          TERMINAL — CONNECT AN AGENT
        </div>
        <div className="mk-cmd-row">
          <span className="prompt" aria-hidden="true">$</span>
          <code>{CONNECT_CMD}</code>
          <button type="button" className={copied ? "mk-copy-btn copied" : "mk-copy-btn"} onClick={onCopy} aria-live="polite">
            {copied ? <Check size={15} /> : <Copy size={15} />}
            {copied ? "Copied ✓" : "Copy"}
          </button>
        </div>
        <div className="mk-cmd-caption">{caption}</div>
      </div>
      <span ref={liveRef} className="sr-only" aria-live="polite" style={{ position: "absolute", width: 1, height: 1, overflow: "hidden", clip: "rect(0 0 0 0)" }}>
        {copied ? "Command copied to clipboard" : ""}
      </span>
    </div>
  );
}

function Nav() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);
  return (
    <header className={scrolled ? "mk-nav scrolled" : "mk-nav"}>
      <div className="mk-nav-inner">
        <a className="mk-brand" href="#top" aria-label="Updater home">
          <img src="/icon.svg" alt="Updater logo" width={26} height={26} />
          <span>Updater<span className="dot">.</span></span>
        </a>
        <nav className="mk-nav-links" aria-label="Primary">
          <a href="#why">Why Updater</a>
          <a href="#how">How it works</a>
          <a href="#demo">Demo</a>
          <a href="#features">Features</a>
          <a href="#open-source">Open source</a>
        </nav>
        <div className="mk-nav-right">
          <a className="mk-gh-link" href={LINKS.github} target="_blank" rel="noreferrer" aria-label="Updater on GitHub">
            <Github size={18} aria-hidden="true" /><span>GitHub</span>
          </a>
          <a className="mk-btn mk-btn-ghost mk-login-btn" href={LINKS.app}>Log in</a>
          <a className="mk-btn mk-btn-primary" href="#connect">Connect an agent</a>
          <button className="mk-menu-btn" type="button" aria-expanded={open} aria-label={open ? "Close menu" : "Open menu"} onClick={() => setOpen((v) => !v)}>
            {open ? <X size={20} /> : <Menu size={20} />}
          </button>
        </div>
      </div>
      <div className={open ? "mk-mobile-menu open" : "mk-mobile-menu"}>
        {open && (
          <nav aria-label="Mobile">
            <a href="#why" onClick={() => setOpen(false)}>Why Updater</a>
            <a href="#how" onClick={() => setOpen(false)}>How it works</a>
            <a href="#demo" onClick={() => setOpen(false)}>Demo</a>
            <a href="#features" onClick={() => setOpen(false)}>Features</a>
            <a href="#open-source" onClick={() => setOpen(false)}>Open source</a>
            <a href={LINKS.app} onClick={() => setOpen(false)}>Log in →</a>
          </nav>
        )}
      </div>
    </header>
  );
}

function Hero() {
  const frameRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = frameRef.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    const io = new IntersectionObserver(
      (entries) => entries.forEach((e) => { if (e.isIntersecting) e.target.classList.add("in-view"); }),
      { threshold: 0.18 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <section className="mk-hero" aria-labelledby="hero-headline">
      <div className="mk-hero-grid">
        <p className="mk-eyebrow mk-reveal" style={{ animationDelay: "0.02s" }}>
          <span className="pulse" aria-hidden="true" />
          OPEN-SOURCE SHIPPING MEMORY FOR CODING AGENTS
        </p>
        <h1 className="mk-brand-display mk-reveal" style={{ animationDelay: "0.08s" }} aria-label="Updater.">
          Updater<span className="dot">.</span>
        </h1>
        <h2 id="hero-headline" className="mk-headline mk-reveal" style={{ animationDelay: "0.16s" }}>
          Your agent ships the code.<br />Updater <span className="hl">remembers why.</span>
        </h2>
        <p className="mk-lede mk-reveal" style={{ animationDelay: "0.24s" }}>
          Keep a searchable record of every verified feature—what changed, why it mattered, how it works, and what happened next.
        </p>
        <div className="mk-reveal" style={{ animationDelay: "0.32s" }}>
          <CommandBlock caption="One command connects Codex, Claude Code, Cursor, or OpenCode." />
        </div>
        <div className="mk-hero-actions mk-reveal" style={{ animationDelay: "0.4s" }}>
          <a className="mk-btn mk-btn-primary" href={LINKS.github} target="_blank" rel="noreferrer">Explore on GitHub <ArrowUpRight size={16} /></a>
          <a className="mk-link-arrow" href="#how">See how it works <ArrowRight size={16} /></a>
          <a className="mk-btn mk-btn-ghost" href={LINKS.app}>Open workspace</a>
        </div>
        <p className="mk-trust mk-reveal" style={{ animationDelay: "0.46s" }}>MIT licensed · Self-hostable · MCP-native · Your code stays in your repo</p>
        <div className="mk-hero-shot mk-reveal" style={{ animationDelay: "0.52s" }}>
          <span className="mk-anno a1"><i />verified</span>
          <span className="mk-anno a2"><i />impact recorded</span>
          <span className="mk-anno a3"><i />context attached</span>
          <div className="mk-shot-frame" ref={frameRef}>
            <div className="mk-shot-bar">
              <span className="mk-traffic" aria-hidden="true"><i style={{ background: "#FF5F57" }} /><i style={{ background: "#FEBC2E" }} /><i style={{ background: "#28C840" }} /></span>
              <span className="url">updater — ship log</span>
              <span style={{ marginLeft: "auto", fontFamily: "var(--mk-mono)", fontSize: 11, color: "#7BA428", fontWeight: 800 }}>● SHIPPED</span>
            </div>
            <img src="/screenshots/app-overview.png" alt="Updater workspace showing the searchable ship log with update list and detail pane including why, how it works, impact, files, branch and commit" width={1440} height={900} fetchPriority="high" />
          </div>
        </div>
      </div>
    </section>
  );
}
function Problem() {
  return (
    <section className="mk-section mk-problem" aria-labelledby="problem-h">
      <div className="mk-chat-bg" aria-hidden="true">
        <div className="mk-chat-line">agent: implemented auth refresh + tests…</div>
        <div className="mk-chat-line">agent: fixed edge case in retry logic…</div>
        <div className="mk-chat-line">you: wait, why did we pick postgres here?</div>
        <div className="mk-chat-line">agent: updated PR description…</div>
        <div className="mk-chat-line">system: chat archived · context fading…</div>
        <div className="mk-chat-line">system: commit 9f3a2c1 pushed · message compressed…</div>
        <div className="mk-chat-line">system: PR #214 merged · discussion drifting out of view…</div>
      </div>
      <div className="mk-wrap">
        <p className="mk-label">THE PROBLEM</p>
        <h2 id="problem-h" className="mk-h2">The code shipped.<br />The context disappeared.</h2>
        <div className="mk-two-col">
          <p>Agent chats are temporary. Commit messages are compressed. Pull requests explain a moment, then drift out of view. Weeks later, the code is still there—but the reasoning, tradeoffs, and expected impact are scattered across tools.</p>
          <p>Onboarding takes longer. Revisits feel like archaeology. The same decisions get re-debated because nobody kept the story behind the diff.</p>
        </div>
        <p className="mk-big-close">Updater turns finished agent work into <u>durable project memory</u>.</p>
        <span className="mk-saved-pill">✓ update saved — why + impact preserved</span>
        <ul className="mk-contrast">
          <li><strong>NOT A TRANSCRIPT</strong><span>Not another chat transcript. A structured record of shipped work.</span></li>
          <li><strong>NOT GIT EITHER</strong><span>Not a replacement for Git. The missing story around the commit.</span></li>
          <li><strong>PRIVATE BY DEFAULT</strong><span>Not full repository access. Only the context your agent chooses to send.</span></li>
        </ul>
      </div>
    </section>
  );
}

function Origin() {
  return (
    <section id="why" className="mk-section" aria-labelledby="why-h">
      <div className="mk-wrap">
        <p className="mk-label">WHY UPDATER EXISTS</p>
        <div className="mk-origin-grid">
          <div>
            <h2 id="why-h" className="mk-h2">Built for the part after “done.”</h2>
            <p className="mk-sub">Coding agents make implementation fast, but speed creates a new problem: understanding what was shipped after the chat ends. Updater was created to preserve that missing layer of memory automatically—after work is verified, while the reasoning is still fresh.</p>
            <p className="mk-sub">It gives future-you and your team a clean answer to four questions: What changed? Why did we change it? How does it work? Did it have the impact we expected?</p>
            <blockquote className="mk-quote">“A changelog tells you what moved. Updater remembers the decision.”<small>— THE UPDATER THESIS</small></blockquote>
          </div>
          <div>
            <ul className="mk-questions">
              <li><b>WHAT</b> What changed, in plain language with files, branch, commit and PR attached.</li>
              <li><b>WHY</b> Why it was needed — the problem, the options, and the tradeoff you accepted.</li>
              <li><b>HOW</b> How it works — implementation notes a future reader can actually follow.</li>
              <li><b>IMPACT</b> Did it work? Expected impact plus dated observations of what really happened.</li>
            </ul>
          </div>
        </div>
      </div>
    </section>
  );
}

const STEPS = [
  { n: "01", title: "Finish and verify", body: "Your coding agent completes a feature, runs the relevant checks, and confirms the work is ready." },
  { n: "02", title: "Publish the story", body: "Before replying, the agent calls Updater over MCP and sends the what, why, how, impact, tradeoffs, files, branch, commit, and pull request." },
  { n: "03", title: "Search the ship log", body: "The update appears in a focused workspace where you can browse by repository, search instantly, add notes, and keep related questions attached." },
  { n: "04", title: "Learn over time", body: "Record observed impact, revisit decisions, or ask the connected agent for focused code context without giving the app full repository access." },
];
const PIPE = [
  { t: "Coding agent", s: "verifies work" },
  { t: "MCP", s: "structured payload" },
  { t: "Updater", s: "ship log" },
  { t: "Future question", s: "answered with context" },
];
function How() {
  const [active, setActive] = useState(0);
  const refs = useRef<Array<HTMLDivElement | null>>([]);
  useEffect(() => {
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((e) => {
          if (e.isIntersecting) {
            const idx = Number((e.target as HTMLElement).dataset.idx);
            setActive(idx);
          }
        });
      },
      { rootMargin: "-38% 0px -52% 0px", threshold: 0 }
    );
    refs.current.forEach((el) => el && io.observe(el));
    return () => io.disconnect();
  }, []);
  return (
    <section id="how" className="mk-section" aria-labelledby="how-h">
      <div className="mk-wrap">
        <p className="mk-label">FROM VERIFIED CODE TO SHARED MEMORY</p>
        <h2 id="how-h" className="mk-h2">Ship once. Understand it later.</h2>
        <div className="mk-how-grid">
          <div className="mk-pipeline" aria-label="Pipeline: coding agent to MCP to Updater to future question">
            <div style={{ fontFamily: "var(--mk-mono)", fontSize: 11, letterSpacing: ".14em", fontWeight: 800, color: "var(--mk-muted)" }}>LIVE PIPELINE</div>
            <div className="mk-pipe-track">
              <div className="mk-pipe-progress" style={{ height: `calc(${(active + 1) * 25}% - 8px)` }} />
              {PIPE.map((p, i) => (
                <div key={p.t} className={i <= active ? "mk-pipe-node active" : "mk-pipe-node"}>
                  <strong>{p.t}</strong><span>{p.s}</span>
                </div>
              ))}
            </div>
            <div className="mk-terminal" style={{ marginTop: 18, maxWidth: "100%" }} aria-label="Terminal event sequence">
              <div><span className="dim">$</span> feature verified</div>
              <div><span className="ok">✓</span> publish_feature</div>
              <div><span className="ok">✓</span> update saved</div>
              <div><span className="ok">✓</span> context available later</div>
            </div>
          </div>
          <div className="mk-steps">
            {STEPS.map((s, i) => (
              <div key={s.n} ref={(el) => { refs.current[i] = el; }} data-idx={i} className={i === active ? "mk-step active" : "mk-step"}>
                <div className="mk-step-num">{s.n}</div>
                <div><h3>{s.title}</h3><p>{s.body}</p></div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
function Demo() {
  const videoRef = useRef<HTMLVideoElement>(null);
  useEffect(() => {
    const el = videoRef.current;
    if (!el) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let played = false;
    const io = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.intersectionRatio >= 0.4 && !played) {
            played = true;
            el.play().catch(() => {});
          } else if (!entry.isIntersecting && !el.paused) {
            el.pause();
          }
        });
      },
      { threshold: [0, 0.4] }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);
  return (
    <section id="demo" className="mk-section" aria-labelledby="demo-h">
      <div className="mk-wrap">
        <p className="mk-label">REAL RECORDING · NO MOCKUPS</p>
        <h2 id="demo-h" className="mk-h2">Watch a feature go from verified to remembered.</h2>
        <p className="mk-sub">
          A raw 29-second screen recording: the agent implements and verifies the Kanban board feature in the terminal, publishes it over MCP, and the update lands at the top of Updater's ship log — 25 features shipped, including this one.
        </p>
        <figure className="mk-demo">
          <div className="mk-shot-bar">
            <span className="mk-traffic" aria-hidden="true"><i style={{ background: "#FF5F57" }} /><i style={{ background: "#FEBC2E" }} /><i style={{ background: "#28C840" }} /></span>
            <span className="url">updater — agent terminal + ship log</span>
            <span className="mk-rec"><i aria-hidden="true" />REC · 00:29</span>
          </div>
          <video
            ref={videoRef}
            controls
            muted
            loop
            playsInline
            preload="metadata"
            poster="/media/updater-demo-poster.jpg"
            width={1920}
            height={1080}
            aria-label="Screen recording: an agent implements and verifies the Kanban board feature, publishes it to Updater over MCP, and the ship log picks up the new update"
          >
            <source src="/media/updater-demo.mp4" type="video/mp4" />
            <a href="/media/updater-demo.mp4">Watch the demo recording (MP4)</a>
          </video>
          <figcaption className="mk-demo-note">
            Left: the agent working through the implementation and its checks. Right: the same feature appearing in the ship log, with why, how, impact, files, and tags attached.
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function ShipLog() {
  return (
    <section className="mk-section" aria-labelledby="log-h">
      <div className="mk-wrap">
        <p className="mk-label">THE SHIP LOG</p>
        <h2 id="log-h" className="mk-h2">Every shipped feature, with its reasoning intact.</h2>
        <p className="mk-sub">Search across titles, summaries, repositories, tags, and file paths. Open an update to see why it was built, how it works, expected impact, tradeoffs, learning notes, files, branch, commit, and pull request—all in one place.</p>
        <figure className="mk-figure" style={{ marginTop: 32 }}>
          <div className="mk-hscroll">
            <img src="/screenshots/app-overview.png" alt="Full Updater ship log: repository sidebar on the left, searchable update list in the middle, and detail pane on the right with why, how, impact and files" loading="lazy" decoding="async" style={{ minWidth: 640 }} />
          </div>
          <figcaption className="mk-callouts">
            <div><b><i>1</i> SEARCH HISTORY</b><p>Search across the full history by title, tag, repo, or file path.</p></div>
            <div><b><i>2</i> INTENT + CODE</b><p>Keep implementation and intent together in one readable record.</p></div>
            <div><b><i>3</i> FOLLOW-UPS</b><p>Attach impact notes and follow-up questions where they belong.</p></div>
          </figcaption>
        </figure>
      </div>
    </section>
  );
}

function Features() {
  return (
    <section id="features" className="mk-section" aria-labelledby="feat-h">
      <div className="mk-wrap">
        <p className="mk-label">MEMORY THAT KEEPS WORKING</p>
        <h2 id="feat-h" className="mk-h2">More useful than a changelog.</h2>
        <div style={{ marginTop: 12 }}>
          <div className="mk-feat-row">
            <div><div className="mk-feat-num">01</div><h3>Structured feature updates</h3><p>Capture the reason, implementation, expected impact, tradeoffs, learning notes, files, tags, branch, commit, pull request, and shipping date.</p><div><span className="mk-tag">why</span><span className="mk-tag">how</span><span className="mk-tag">impact</span><span className="mk-tag">tradeoffs</span><span className="mk-tag">files</span></div></div>
            <div className="mk-feat-visual"><div className="mk-line-ill"><svg width="72" height="56" viewBox="0 0 72 56" aria-hidden="true"><rect x="2" y="2" width="68" height="52" rx="8" fill="none" stroke="#22241F" strokeWidth="2" /><line x1="12" y1="16" x2="60" y2="16" stroke="#B8F34A" strokeWidth="5" strokeLinecap="round" /><line x1="12" y1="28" x2="48" y2="28" stroke="#DFE1D8" strokeWidth="4" strokeLinecap="round" /><line x1="12" y1="38" x2="54" y2="38" stroke="#DFE1D8" strokeWidth="4" strokeLinecap="round" /></svg><span>what · why · how · impact<br />tradeoffs · files · branch · PR</span></div></div>
          </div>
          <div className="mk-feat-row flip">
            <div><div className="mk-feat-num">02</div><h3>Instant search</h3><p>Find old decisions by title, summary, repository, tag, or code path as you type.</p></div>
            <div className="mk-feat-visual"><img src="/screenshots/search-in-action.png" alt="Instant search filtering the ship log as the user types across titles, summaries, tags and file paths" loading="lazy" decoding="async" /></div>
          </div>
          <div className="mk-feat-row">
            <div><div className="mk-feat-num">03</div><h3>Impact over time</h3><p>Add dated observations after release, so expected outcomes and real outcomes live together.</p></div>
            <div className="mk-feat-visual"><div className="mk-line-ill"><svg width="120" height="48" viewBox="0 0 120 48" aria-hidden="true"><polyline points="4,38 32,30 58,32 84,14 116,10" fill="none" stroke="#22241F" strokeWidth="2.5" /><circle cx="84" cy="14" r="5" fill="#B8F34A" stroke="#22241F" strokeWidth="2" /><circle cx="116" cy="10" r="5" fill="#22241F" /></svg><span>expected → observed<br />dated notes, side by side</span></div></div>
          </div>
          <div className="mk-feat-row flip">
            <div><div className="mk-feat-num">04</div><h3>Questions that stay attached</h3><p>Ask questions inside an update. Answers remain connected to the feature instead of disappearing into another chat.</p></div>
            <div className="mk-feat-visual"><img src="/screenshots/update-detail.png" alt="Update detail with question thread attached to the feature, alongside impact, tradeoffs and files" loading="lazy" decoding="async" /></div>
          </div>
          <div className="mk-feat-row">
            <div><div className="mk-feat-num">05</div><h3>Tech-debt inbox</h3><p>Run <code style={{ fontFamily: "var(--mk-mono)", background: "#EDEFE3", padding: "2px 7px", borderRadius: 6 }}>/tech-depth</code> from an agent checkout to capture rushed decisions with scope, urgency, impact, mitigation, and current coverage.</p></div>
            <div className="mk-feat-visual"><div className="mk-line-ill"><svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true"><rect x="6" y="12" width="44" height="32" rx="6" fill="none" stroke="#22241F" strokeWidth="2" /><path d="M18 24l-4 4 4 4M38 24l4 4-4 4" stroke="#7BA428" strokeWidth="2.5" fill="none" strokeLinecap="round" /></svg><span>scope · urgency · impact<br />mitigation · coverage</span></div></div>
          </div>
          <div className="mk-feat-row flip">
            <div><div className="mk-feat-num">06</div><h3>Quick notes</h3><p>Keep lightweight follow-ups, reminders, and ideas beside the shipping history without turning the workspace into a project-management suite.</p></div>
            <div className="mk-feat-visual"><div className="mk-line-ill"><svg width="56" height="56" viewBox="0 0 56 56" aria-hidden="true"><rect x="10" y="8" width="36" height="40" rx="6" fill="#B8F34A" stroke="#22241F" strokeWidth="2" /><line x1="18" y1="20" x2="38" y2="20" stroke="#22241F" strokeWidth="2.5" strokeLinecap="round" /><line x1="18" y1="28" x2="38" y2="28" stroke="#22241F" strokeWidth="2.5" strokeLinecap="round" /></svg><span>reminders · ideas · follow-ups<br />color-tagged, out of the way</span></div></div>
          </div>
        </div>
      </div>
    </section>
  );
}

function Agents() {
  return (
    <section id="connect" className="mk-section mk-dark-section" aria-labelledby="agents-h">
      <div className="mk-wrap">
        <p className="mk-label">WORKS WHERE YOUR AGENT WORKS</p>
        <h2 id="agents-h" className="mk-h2">One command. Your whole coding crew.</h2>
        <p className="mk-sub">The installer connects MCP and adds the Updater commands for Codex, Claude Code, Cursor, and OpenCode. Choose one agent or configure them all.</p>
        <div className="mk-rail" aria-label="Supported agents: Codex, Claude Code, Cursor, OpenCode">
          <span>Codex <em>/</em></span><span>Claude Code <em>/</em></span><span>Cursor <em>/</em></span><span>OpenCode</span>
        </div>
        <div className="mk-dark-grid">
          <div>
            <CommandBlock caption="Prompts for API key, then lets you pick agents. No manual MCP JSON editing." dark />
            <ul className="mk-cmd-list" aria-label="Available agent commands">
              <li><code>/updater</code><span>route common shipping and context tasks</span></li>
              <li><code>/updater-ship</code><span>publish a verified feature</span></li>
              <li><code>/updater-check</code><span>fulfill pending code-context requests</span></li>
              <li><code>/updater-impact</code><span>add a real-world impact observation</span></li>
              <li><code>/tech-depth</code><span>scan for tech debt and rushed decisions</span></li>
            </ul>
            <p className="mk-tech-line">MCP over Streamable HTTP, with a stdio fallback for local workflows.</p>
          </div>
          <div className="mk-shot-dark">
            <img src="/screenshots/connect-agent.png" alt="Connect an agent dialog with copyable MCP setup for OpenCode, Codex and Claude Code" loading="lazy" decoding="async" />
          </div>
        </div>
      </div>
    </section>
  );
}
function Context() {
  return (
    <section className="mk-section" aria-labelledby="ctx-h">
      <div className="mk-wrap">
        <p className="mk-label">YOUR REPO STAYS YOURS</p>
        <h2 id="ctx-h" className="mk-h2">Ask for code context without handing over the codebase.</h2>
        <p className="mk-sub">Updater never clones your repository and never needs full file access. When a question requires code detail, your connected agent reads the local files and sends only a few focused excerpts back to the update.</p>
        <div className="mk-diagram" aria-label="Diagram: your local repo to your coding agent to focused excerpts to Updater">
          <div className="node"><span className="pill">◈</span>Your local repo<small>stays on your machine</small></div>
          <div className="arrow" aria-hidden="true">→</div>
          <div className="node"><span className="pill">✦</span>Your coding agent<small>reads locally</small></div>
          <div className="arrow" aria-hidden="true">→</div>
          <div className="node"><span className="pill">≡</span>Focused excerpts<small>only relevant snippets</small></div>
          <div className="arrow" aria-hidden="true">→</div>
          <div className="node hl"><span className="pill">✓</span>Updater<small>attached to the update</small></div>
        </div>
        <div className="mk-figure">
          <div className="mk-hscroll"><img src="/screenshots/code-context.png" alt="Code context request fulfilled with focused excerpts attached to the update, without cloning the repository" loading="lazy" decoding="async" style={{ minWidth: 640 }} /></div>
        </div>
        <div className="mk-points">
          <div><strong>Private stays private.</strong><p>Private repositories remain private. No cloning, no broad read access.</p></div>
          <div><strong>Agent picks snippets.</strong><p>The agent chooses the relevant snippets from files it already sees.</p></div>
          <div><strong>Stays attached.</strong><p>Context stays attached to the feature that requested it.</p></div>
        </div>
      </div>
    </section>
  );
}

function OpenSource() {
  return (
    <section id="open-source" className="mk-section" aria-labelledby="os-h">
      <div className="mk-wrap">
        <p className="mk-label">OPEN BY DESIGN</p>
        <div className="mk-open-grid">
          <div>
            <h2 id="os-h" className="mk-h2">Fork it. Host it. Improve it.</h2>
            <p className="mk-sub">Updater is MIT licensed and built in the open. Run it locally with SQLite, deploy it with PostgreSQL, connect your own agents, and shape the workflow around your team.</p>
            <div className="mk-stack"><b>stack</b> · React 19 · TypeScript · Vite · FastAPI · SQLAlchemy · PostgreSQL / SQLite · MCP</div>
            <div className="mk-actions">
              <a className="mk-btn mk-btn-primary" href={LINKS.github} target="_blank" rel="noreferrer"><Github size={16} /> View the source</a>
              <a className="mk-btn mk-btn-ghost" href={LINKS.docs} target="_blank" rel="noreferrer">Read the API docs</a>
              <a className="mk-btn mk-btn-ghost" href={LINKS.mit} target="_blank" rel="noreferrer">MIT license</a>
            </div>
            <p className="mk-sub" style={{ fontSize: 15 }}>Issues and pull requests are welcome. For larger changes, open an issue first so the direction can be discussed together.</p>
          </div>
          <div className="mk-manifest" aria-label="Repository layout preview">
            <header><span>UPDATER — OPEN SOURCE MANIFEST</span><span>MIT</span></header>
            <ul>
              <li><span>▸</span> frontend/ — ship-log workspace (React 19)</li>
              <li><span>▸</span> backend/ — FastAPI + MCP server</li>
              <li><span>▸</span> commands/ — /updater-ship, /tech-depth…</li>
              <li><span>▸</span> docs/ — real screenshots, no mockups</li>
              <li><span>▸</span> compose.dokploy.yml — self-host ready</li>
              <li><span>▸</span> LICENSE — MIT, fork freely</li>
            </ul>
            <div style={{ padding: "0 18px 18px" }}>
              <a className="mk-link-arrow" href={LINKS.github} target="_blank" rel="noreferrer">Star the repo, then ship your first memory <ArrowUpRight size={16} /></a>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}

function FinalCTA() {
  return (
    <section className="mk-section mk-cta-lime" aria-labelledby="cta-h">
      <div className="mk-wrap">
        <p className="mk-label" style={{ color: "#33400F" }}>GET STARTED</p>
        <h2 id="cta-h" className="mk-h2">Give your shipped code a memory.</h2>
        <p className="mk-sub">Connect an agent, verify a feature, and let Updater keep the story.</p>
        <div style={{ marginTop: 26 }}><CommandBlock caption="Works with Codex, Claude Code, Cursor, and OpenCode." /></div>
        <div className="mk-actions">
          <a className="mk-btn" style={{ background: "var(--mk-ink)", color: "#fff" }} href="#connect">Copy command</a>
          <a className="mk-btn mk-btn-ghost" style={{ background: "transparent", borderColor: "var(--mk-ink)" }} href={LINKS.github} target="_blank" rel="noreferrer"><Github size={16} /> View on GitHub</a>
          <a className="mk-btn mk-btn-ghost" style={{ borderColor: "var(--mk-ink)" }} href={LINKS.app}>Open workspace <ArrowRight size={16} /></a>
        </div>
        <p className="mk-trust" style={{ color: "#33400F" }}>Open source. MIT licensed. Self-hostable. Built for Codex, Claude Code, Cursor, and OpenCode.</p>
      </div>
    </section>
  );
}

function Footer() {
  return (
    <footer className="mk-footer" aria-label="Footer">
      <div className="mk-wrap">
        <div className="mk-foot-grid">
          <div>
            <div className="mk-foot-brand"><img src="/icon.svg" alt="Updater logo" />Updater.</div>
            <p className="mk-foot-tag">Your open-source shipping memory.</p>
          </div>
          <div className="mk-foot-links">
            <div><h4>PROJECT</h4><a href={LINKS.github} target="_blank" rel="noreferrer">GitHub</a><a href={LINKS.mit} target="_blank" rel="noreferrer">MIT license</a><a href="#how">How it works</a><a href="#connect">Connect an agent</a></div>
            <div><h4>API</h4><a href={LINKS.docs} target="_blank" rel="noreferrer">API docs</a><a href={LINKS.mcp} target="_blank" rel="noreferrer">MCP endpoint</a><a href={LINKS.api} target="_blank" rel="noreferrer">Live API</a></div>
            <div><h4>WORKSPACE</h4><a href={LINKS.app}>Open workspace</a><a href="#features">Features</a><a href="#why">Why Updater</a></div>
          </div>
        </div>
        <div className="mk-foot-bottom">
          <span>Built for developers shipping with agents.</span>
          <span className="mk-mcp-pill"><i />MCP ENDPOINT · https://updaterapi.blitzgo.io/mcp</span>
        </div>
      </div>
    </footer>
  );
}

export default function Homepage() {
  useEffect(() => {
    document.title = "Updater — your open-source shipping memory";
  }, []);
  return (
    <div className="mk-page" id="top">
      <a className="mk-skip-link" href="#main">Skip to content</a>
      <Nav />
      <main id="main">
        <Hero />
        <Problem />
        <Origin />
        <How />
        <Demo />
        <ShipLog />
        <Features />
        <Agents />
        <Context />
        <OpenSource />
        <FinalCTA />
      </main>
      <Footer />
    </div>
  );
}
