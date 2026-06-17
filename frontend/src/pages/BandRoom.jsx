import { useState, useEffect, useCallback, useRef } from "react";
import { useParams, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";
import { getCases, runCase, getCaseStatus, getBandMessages } from "../api/client.js";

const C = {
  bg:"#050D1A", navy:"#0A1A2F", navyLight:"#0F2340", border:"#1A3A5C",
  gold:"#E8A93D", goldLight:"#F0C75E", cyan:"#4FC3F7", green:"#4CAF50",
  amber:"#FF9800", red:"#EF5350", purple:"#A78BFA", white:"#F0F4FF", muted:"#6B8CAE",
};

const AGENTS = {
  orchestrator: { name:"Orchestrator",         icon:"🎯", color:C.gold   },
  doc:          { name:"Doc Auditor",           icon:"📄", color:C.cyan   },
  kyc:          { name:"KYC Guardian",          icon:"🛡️", color:C.green  },
  compliance:   { name:"Dynamic Compliance",    icon:"⚖️", color:C.gold   },
  risk:         { name:"Stress-Test Simulator", icon:"📈", color:C.amber  },
  tokenizer:    { name:"Asset Tokenizer",       icon:"🪙", color:C.purple },
  signer:       { name:"Consensus Signer",      icon:"🔐", color:C.red    },
  governance:   { name:"Governance & Audit",    icon:"📋", color:C.purple },
};

// Maps real Band agent UUIDs → AGENTS keys
const UUID_TO_AGENT = {
  "3913dc8a-7079-40b1-a6c6-88d2c71f4c5f": "orchestrator",
  "18cb4fe5-7d9d-4821-b4d3-c948eda44c37": "orchestrator",
  "876c3314-5b74-4910-ba87-dde416c1afd2": "doc",
  "716387a1-b475-4952-a4d8-e6a9f152cf36": "kyc",
  "350eb730-f181-45ff-967e-8f63032e55f4": "compliance",
  "59cd0497-e378-450b-91ba-bd385a173e09": "risk",
  "de1b18f1-1eb7-4d78-85bd-449778066e83": "tokenizer",
  "5577199a-4394-40f0-afdc-6cd27df29078": "signer",
  "fda304ba-3c6d-4aa3-9151-02cc06f045da": "governance",
};

// Backend status → sidebar dot style
function sidebarStatus(s) {
  if (s === "halted" || s === "rejected" || s === "blocked_gate" || s === "error")
    return { color: C.red,   label: "halted",   glow: false };
  if (s === "awaiting_decision" || s === "authorized" || s === "approved")
    return { color: C.green, label: "complete", glow: false };
  if (s === "processing")
    return { color: C.green, label: "running…", glow: true  };
  return   { color: C.muted, label: "queued",   glow: false };
}

const TERMINAL_STATUSES = new Set([
  "awaiting_decision", "authorized", "rejected", "halted", "blocked_gate", "error",
]);

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Resolve @[[uuid]] mention syntax → @Name using metadata.mentions or UUID_TO_AGENT fallback.
// This is the ONLY text transformation applied to raw Band messages.
function resolveMentions(content, mentions) {
  const map = {};
  for (const m of (mentions || [])) {
    if (m.id) {
      // Prefer m.name (clean display name e.g. "Orchestrator", "Doc Auditor") over
      // m.handle which carries the full "user/agent-slug" prefix from Band.
      const label = m.name ? m.name.replace(/\s+/g, "_") : null;
      if (label) map[m.id] = label;
    }
  }
  return content.replace(/@\[\[([^\]]+)\]\]/g, (_, uuid) => {
    if (map[uuid]) return `@${map[uuid]}`;
    const agentKey = UUID_TO_AGENT[uuid];
    if (agentKey && AGENTS[agentKey]) return `@${AGENTS[agentKey].name.replace(/\s+/g, "_")}`;
    return "";
  });
}

// Convert a raw Band message to a display bubble.
// Drops: brightuity_terminal plumbing, unknown sender UUIDs, empty content.
// Transforms: only @[[uuid]] mention resolution — everything else verbatim.
// Optional verdict chip: scans raw content for verdict marker, no reformatting.
function rawToBubble(raw) {
  const content = raw.content || "";
  if (content.includes("brightuity_terminal:")) return null;
  const agentKey = UUID_TO_AGENT[raw.sender_id];
  if (!agentKey) return null;
  const mentions = raw.metadata?.mentions || [];
  const text = resolveMentions(content, mentions);
  if (!text.trim()) return null;

  // Light verdict chip detection — does not modify text
  let verdict = null;
  if (/— PASS\b/.test(content) || /\*\*PASS\*\*/.test(content))      verdict = { status: "pass", label: "PASS" };
  else if (/— HALT\b/.test(content) || /\*\*HALT\*\*/.test(content)) verdict = { status: "halt", label: "HALT" };
  else if (/— FAIL\b/.test(content) || /\*\*FAIL\*\*/.test(content)) verdict = { status: "fail", label: "FAIL" };

  // Timestamp: Band may include created_at in the raw item or its metadata
  const ts = raw.timestamp || raw.created_at || raw.metadata?.created_at || null;

  return { from: agentKey, text, verdict, ts };
}

// ── UI components ──────────────────────────────────────────────────────────────

function Identicon({ seed, size=30 }) {
  let h = 5381;
  for (let i=0;i<seed.length;i++) h = (((h<<5)+h)+seed.charCodeAt(i))|0;
  h = Math.abs(h);
  const ACC = [C.cyan, C.gold, C.muted];
  const accent = ACC[h % 3];
  const pad=5, n=5, cell=(size-pad*2)/n, filled=[];
  for (let r=0;r<n;r++) for (let col=0;col<n;col++){ const m=col<3?col:4-col; if ((h>>(r*3+m))&1) filled.push({r,col}); }
  return (
    <svg width={size} height={size} style={{ flexShrink:0 }}>
      <rect width={size} height={size} rx={8} fill={C.navyLight} stroke={`${C.cyan}44`}/>
      {filled.map(({r,col})=> <rect key={`${r}-${col}`} x={pad+col*cell} y={pad+r*cell} width={cell-1} height={cell-1} rx={1.5} fill={accent} opacity={0.82}/>)}
    </svg>
  );
}

function highlight(text) {
  return text.split(/(@[A-Za-z_]+)/g).map((p,i) =>
    p.startsWith("@")
      ? <span key={i} style={{ color:C.gold, fontWeight:700 }}>{p}</span>
      : <span key={i}>{p}</span>
  );
}

function Bubble({ m }) {
  const a = AGENTS[m.from];
  if (!a) return null;
  const isPass  = m.verdict?.status === "pass";
  const vColor  = isPass ? C.green : C.red;
  const tsLabel = m.ts
    ? new Date(m.ts).toLocaleTimeString([], { hour:"2-digit", minute:"2-digit", second:"2-digit" })
    : null;
  return (
    <div style={{ display:"flex", gap:9, maxWidth:"82%" }}>
      <span style={{ width:30, height:30, borderRadius:"50%", background:`${a.color}22`, border:`1px solid ${a.color}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, flexShrink:0 }}>{a.icon}</span>
      <div style={{ minWidth:0 }}>
        <div style={{ display:"flex", alignItems:"baseline", gap:7, marginBottom:3 }}>
          <span style={{ fontSize:10.5, fontWeight:800, color:a.color }}>{a.name}</span>
          {tsLabel && <span style={{ fontSize:8, color:C.muted }}>{tsLabel}</span>}
        </div>
        <div style={{ background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:"3px 12px 12px 12px", padding:"9px 12px", fontSize:11.5, lineHeight:1.5, color:C.white, whiteSpace:"pre-wrap" }}>
          {highlight(m.text)}
        </div>
        {m.verdict && (
          <div style={{ marginTop:6 }}>
            <span style={{ display:"inline-flex", alignItems:"center", gap:5, fontSize:9, fontWeight:700, color:vColor, background:`${vColor}1A`, border:`1px solid ${vColor}44`, padding:"3px 10px", borderRadius:20 }}>
              {isPass ? "✓" : "✕"} {m.verdict.label}
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

function Typing({ who }) {
  const a = AGENTS[who] || AGENTS.orchestrator;
  return (
    <div style={{ display:"flex", gap:9, alignItems:"center" }}>
      <span style={{ width:30, height:30, borderRadius:"50%", background:`${a.color}22`, border:`1px solid ${a.color}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, flexShrink:0 }}>{a.icon}</span>
      <div style={{ background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:"3px 12px 12px 12px", padding:"11px 14px", display:"flex", gap:4, alignItems:"center" }}>
        <span className="bdot" style={{ animationDelay:"0s" }}/><span className="bdot" style={{ animationDelay:"0.2s" }}/><span className="bdot" style={{ animationDelay:"0.4s" }}/>
        <span style={{ fontSize:9, color:C.muted, marginLeft:5 }}>{a.name} is working…</span>
      </div>
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────

export default function BandRoom() {
  const { id }   = useParams();
  const navigate = useNavigate();
  const { user } = useSession();
  const [searchParams] = useSearchParams();

  const caseId         = id || "REQ-2041";
  // Captured once at mount — intentionally NOT in effect deps to avoid re-run on URL strip
  const shouldRunFresh = searchParams.get("run") === "1";

  // Sidebar: real cases from API
  const [sidebarCases, setSidebarCases] = useState([]);

  // phase: "loading" | "live" | "done" | "idle" | "error"
  const [phase,          setPhase]          = useState("loading");
  const [terminalStatus, setTerminalStatus] = useState(null);
  const [errorMsg,       setErrorMsg]       = useState(null);

  // Feed state — raw bubbles accumulated in real time, never rebuilt
  const [shown,  setShown]  = useState([]);
  const [typing, setTyping] = useState(null);
  const [done,   setDone]   = useState(false);
  const scrollRef = useRef(null);

  // Load sidebar: pending cases + always include the currently-open case.
  // Extracted into a stable callback so it can run on mount AND when done flips.
  const loadSidebar = useCallback(() => {
    getCases("pending").then(async pending => {
      const hasActive = pending.some(c => c.request_id === caseId);
      if (hasActive) { setSidebarCases(pending); return; }
      // Active case no longer pending — fetch its current status and prepend it
      let activeEntry = { request_id: caseId, full_name: caseId, status: "awaiting_decision" };
      try {
        const st = await getCaseStatus(caseId);
        activeEntry = { request_id: caseId, full_name: caseId, status: st.status };
      } catch (_) {}
      setSidebarCases([activeEntry, ...pending]);
    }).catch(() => {});
  }, [caseId]);

  // Load sidebar on mount and whenever caseId changes
  useEffect(() => { loadSidebar(); }, [loadSidebar]);

  // Re-load sidebar when the run completes so the dot updates from running→complete/halted
  useEffect(() => { if (done) loadSidebar(); }, [done, loadSidebar]);

  // Derive display name from live cases
  const sidebarEntry = sidebarCases.find(c => c.request_id === caseId);
  const displayName  = sidebarEntry?.full_name ?? caseId;

  // ── Live mirror: raw Band room messages, in order, verbatim ──────────────────
  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setShown([]);
    setTyping(null);
    setDone(false);
    setErrorMsg(null);
    setTerminalStatus(null);

    // Poll getBandMessages every 3s. Feed = raw messages in arrival order.
    // No package fetch, no reordering, no rebuilding.
    async function pollRoom() {
      let seenCount  = 0;
      let isTerminal = false;

      for (let poll = 0; poll < 40 && !cancelled && !isTerminal; poll++) {
        if (!cancelled) setTyping("orchestrator");
        await sleep(poll === 0 ? 800 : 3000);
        if (cancelled) return;
        setTyping(null);

        let resp;
        try {
          resp = await getBandMessages(caseId);
        } catch (_) {
          continue; // transient network error or room not yet created
        }
        if (cancelled) return;
        if (resp.status === "error") continue;

        const rawMsgs = resp.messages || [];
        const newRaw  = rawMsgs.slice(seenCount);
        seenCount     = rawMsgs.length;

        for (const raw of newRaw) {
          if (cancelled) return;
          if ((raw.content || "").includes("brightuity_terminal:")) {
            isTerminal = true;
            break;
          }
          const bubble = rawToBubble(raw);
          if (bubble) {
            setShown(prev => [...prev, bubble]);
            await sleep(250);
            if (cancelled) return;
          }
        }

        if (!isTerminal) {
          try {
            const st = await getCaseStatus(caseId);
            if (TERMINAL_STATUSES.has(st.status)) {
              if (!cancelled) setTerminalStatus(st.status);
              isTerminal = true;
            }
          } catch (_) {}
        }
      }

      if (cancelled) return;
      setTyping(null);

      // Final status fetch for badge and headline
      try {
        const st = await getCaseStatus(caseId);
        if (!cancelled) setTerminalStatus(st.status);
      } catch (_) {}

      if (!cancelled) {
        setDone(true);
        setPhase("done");
      }
    }

    async function loadMirror() {
      if (shouldRunFresh) {
        // Strip ?run=1 from URL immediately so a page refresh won't re-trigger a fresh run
        navigate(`/room/${caseId}`, { replace: true });

        // Force a brand-new Band session
        try {
          await runCase(caseId, { force: true });
        } catch (e) {
          if (e.status !== 409) {
            if (!cancelled) {
              setErrorMsg("Couldn't start the pipeline — " + (e.message || "unknown error"));
              setPhase("error");
            }
            return;
          }
          // 409 = already processing — proceed to poll
        }

        if (!cancelled) setPhase("live");
        await pollRoom();

      } else {
        // Plain view: show existing result only — do NOT auto-run
        let firstResp = null;
        try {
          firstResp = await getBandMessages(caseId);
        } catch (e) {
          if (!cancelled) {
            if (e.status === 404) {
              setErrorMsg("Not yet processed — start it from the dashboard.");
              setPhase("idle");
            } else {
              setErrorMsg("Backend unreachable: " + (e.message || "unknown error"));
              setPhase("error");
            }
          }
          return;
        }

        if (firstResp.status === "no_room_yet" || !(firstResp.messages?.length)) {
          if (!cancelled) {
            setErrorMsg("Not yet processed — start it from the dashboard.");
            setPhase("idle");
          }
          return;
        }

        // Existing room with messages — mirror it
        if (!cancelled) setPhase("live");
        await pollRoom();
      }
    }

    loadMirror();
    return () => { cancelled = true; };
  }, [caseId]); // shouldRunFresh intentionally omitted — captured at mount, URL stripped immediately

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [shown, typing]);

  // Derived display values
  const isHalted   = terminalStatus === "halted" || terminalStatus === "blocked_gate" || terminalStatus === "halted_kyc";
  const badgeColor = done ? (isHalted ? C.red : C.green) : C.amber;
  const badgeLabel = phase === "loading"
    ? "LOADING"
    : done ? (isHalted ? "HALTED" : "COMPLETE")
    : "LIVE";

  return (
    <div style={{ minHeight:"100vh", background:C.bg, fontFamily:"'Montserrat', system-ui, sans-serif", color:C.white, display:"flex" }}>
      <style>{`@keyframes bdot{0%,60%,100%{transform:translateY(0);opacity:0.4}30%{transform:translateY(-4px);opacity:1}} .bdot{width:6px;height:6px;border-radius:50%;background:${C.muted};display:inline-block;animation:bdot 1.2s infinite}`}</style>

      {/* ── SIDEBAR ── */}
      <div style={{ width:256, flexShrink:0, background:C.navy, borderRight:`1px solid ${C.border}`, display:"flex", flexDirection:"column", height:"100vh", position:"sticky", top:0 }}>
        <div onClick={() => navigate("/dashboard")} style={{ padding:"15px 16px", borderBottom:`1px solid ${C.border}`, display:"flex", alignItems:"center", gap:9, cursor:"pointer" }}>
          <svg width="22" height="22" viewBox="0 0 64 64"><polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="none" stroke={C.gold} strokeWidth="2"/><text x="32" y="42" textAnchor="middle" fill={C.gold} fontSize="24" fontWeight="800">B</text></svg>
          <div style={{ minWidth:0 }}>
            <div style={{ fontSize:12, fontWeight:800, letterSpacing:"1px" }}>CASE ROOMS</div>
            <div style={{ fontSize:8, color:C.muted, letterSpacing:"0.5px" }}>BAND COORDINATION</div>
          </div>
        </div>
        <div style={{ fontSize:8.5, color:C.muted, letterSpacing:"1.5px", padding:"12px 16px 8px" }}>CHANNELS</div>
        <div style={{ flex:1, overflowY:"auto" }}>
          {sidebarCases.map(ch => {
            const active = ch.request_id === caseId;
            const cst    = sidebarStatus(ch.status);
            return (
              <div key={ch.request_id} onClick={() => navigate(`/room/${ch.request_id}`)}
                style={{ display:"flex", alignItems:"center", gap:10, padding:"9px 14px", cursor:"pointer", background:active ? `linear-gradient(90deg, ${C.gold}18, transparent)` : "none", borderLeft:active ? `3px solid ${C.gold}` : "3px solid transparent", opacity:cst.label === "queued" ? 0.55 : 1 }}>
                <Identicon seed={ch.request_id} size={30}/>
                <div style={{ flex:1, minWidth:0 }}>
                  <span style={{ fontSize:11.5, fontWeight:active ? 700 : 600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis", display:"block" }}>{ch.full_name || ch.request_id}</span>
                  <div style={{ fontSize:9, color:cst.color, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{ch.request_id} · {cst.label}</div>
                </div>
                <span style={{ width:7, height:7, borderRadius:"50%", background:cst.color, flexShrink:0, boxShadow:cst.glow ? `0 0 7px ${cst.color}` : "none" }}/>
              </div>
            );
          })}
        </div>
        <div style={{ padding:"12px 14px", borderTop:`1px solid ${C.border}`, display:"flex", alignItems:"center", gap:8 }}>
          <div style={{ width:26, height:26, borderRadius:"50%", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, display:"flex", alignItems:"center", justifyContent:"center", color:C.navy, fontWeight:800, fontSize:9, flexShrink:0 }}>
            {(user?.name ?? "Nevine AKF").split(" ").map(w => w[0]).join("")}
          </div>
          <div style={{ minWidth:0 }}>
            <div style={{ fontSize:10, fontWeight:600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{user?.name ?? "Nevine AKF"}</div>
            <div style={{ fontSize:8, color:C.muted }}>Observer</div>
          </div>
        </div>
      </div>

      {/* ── MAIN ── */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", minWidth:0, height:"100vh" }}>

        {/* Header */}
        <div style={{ padding:"12px 18px", borderBottom:`1px solid ${C.border}`, background:C.navy, display:"flex", alignItems:"center", gap:12 }}>
          <div style={{ minWidth:0, flex:1 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <span style={{ fontSize:13, fontWeight:800, whiteSpace:"nowrap" }}>{displayName}</span>
              <span style={{ fontSize:9, color:C.muted, fontFamily:"monospace" }}>{caseId}</span>
              <span style={{ fontSize:8, fontWeight:700, color:badgeColor, background:`${badgeColor}1A`, border:`1px solid ${badgeColor}44`, padding:"2px 8px", borderRadius:20, whiteSpace:"nowrap" }}>● {badgeLabel}</span>
            </div>
            <div style={{ fontSize:9.5, color:C.muted, marginTop:2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>Band Chat Room</div>
          </div>
        </div>

        {/* Message feed */}
        <div ref={scrollRef} style={{ flex:1, overflowY:"auto", padding:"16px 18px", display:"flex", flexDirection:"column", gap:13, background:"linear-gradient(180deg, #050D1A, #07101f)" }}>

          <div style={{ textAlign:"center" }}>
            <span style={{ fontSize:8.5, color:C.muted, background:C.navyLight, border:`1px solid ${C.border}`, padding:"3px 12px", borderRadius:20 }}>
              🔒 Band Room opened · agents coordinate autonomously · you are observing
            </span>
          </div>

          {/* Loading state */}
          {phase === "loading" && (
            <div style={{ display:"flex", flexDirection:"column", gap:12, marginTop:8 }}>
              <div style={{ textAlign:"center", fontSize:10.5, color:C.muted }}>
                Agents coordinating through Band…
              </div>
              <Typing who="orchestrator"/>
            </div>
          )}

          {/* Error state */}
          {phase === "error" && (
            <div style={{ textAlign:"center", padding:"48px 0", color:"#EF5350", fontSize:12 }}>
              {errorMsg || "Couldn't load the analysis — backend may still be processing."}
            </div>
          )}

          {/* Idle state — case not yet processed, plain view */}
          {phase === "idle" && (
            <div style={{ textAlign:"center", padding:"48px 0", color:C.muted, fontSize:12 }}>
              {errorMsg || "Not yet processed — start it from the dashboard."}
            </div>
          )}

          {/* Live mirror — raw Band room messages in order */}
          {(phase === "live" || phase === "done") && (
            <>
              {shown.map((m, i) => <Bubble key={i} m={m}/>)}
              {typing && <Typing who={typing}/>}
              {done && (
                <div style={{ textAlign:"center", marginTop:6 }}>
                  <span style={{ fontSize:8.5, color:isHalted ? C.red : C.green, background:`${isHalted ? C.red : C.green}1A`, border:`1px solid ${isHalted ? C.red : C.green}44`, padding:"4px 14px", borderRadius:20, fontWeight:700, letterSpacing:"0.5px" }}>
                    {isHalted ? "ANALYSIS COMPLETE · RECOMMENDATION: HALT" : "ANALYSIS COMPLETE · RECOMMENDATION: APPROVE"}
                  </span>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding:"12px 18px", borderTop:`1px solid ${C.border}`, background:C.navy, display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 }}>
          <span style={{ fontSize:9.5, color:C.muted, display:"flex", alignItems:"center", gap:6, minWidth:0 }}>
            <span style={{ width:6, height:6, borderRadius:"50%", background:done ? C.gold : C.green, flexShrink:0 }}/>
            <span style={{ whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>Observing — agents coordinate autonomously</span>
          </span>
          <button
            onClick={() => done && navigate(`/review/${caseId}`)}
            disabled={!done}
            style={{ background:done ? `linear-gradient(135deg, ${C.goldLight}, ${C.gold})` : C.navyLight, border:done ? "none" : `1px solid ${C.border}`, borderRadius:9, padding:"9px 16px", color:done ? C.navy : C.muted, fontSize:11, fontWeight:800, fontFamily:"inherit", cursor:done ? "pointer" : "not-allowed", whiteSpace:"nowrap", flexShrink:0, transition:"all 0.3s" }}>
            Open Decision Evidence Package →
          </button>
        </div>
      </div>
    </div>
  );
}
