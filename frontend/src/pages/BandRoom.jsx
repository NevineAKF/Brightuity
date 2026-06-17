import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";
import { runCase, getCaseStatus, getEvidencePackage } from "../api/client.js";

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

// Maps package agent_name → AGENTS key
const AGENT_KEY_MAP = {
  doc_auditor:        "doc",
  kyc_guardian:       "kyc",
  dynamic_compliance: "compliance",
  stress_test:        "risk",
  asset_tokenizer:    "tokenizer",
  consensus_signer:   "signer",
  governance_audit:   "governance",
};

// Orchestrator routing prompt for each agent (keyed by the agent being routed TO)
const ORCH_ROUTES = {
  kyc_guardian:       "Documentation cleared. @KYC_Guardian run identity and AML screening.",
  dynamic_compliance: "Identity check complete. @Dynamic_Compliance assess regulatory compliance.",
  stress_test:        "Compliance reviewed. @Stress_Test_Simulator run valuation and risk scenarios.",
  asset_tokenizer:    "All Stage 1 gates cleared. @Asset_Tokenizer structure the token parameters.",
  consensus_signer:   "Token structured. @Consensus_Signer seal the evidence record.",
};

const SIDEBAR_ORDER = [
  { id:"REQ-2041", name:"Marcus Weber",   status:"running" },
  { id:"REQ-2042", name:"Sofia Andreou",  status:"queued"  },
  { id:"REQ-2043", name:"Viktor Petrov",  status:"halted"  },
  { id:"REQ-2044", name:"Isabella Rossi", status:"queued"  },
  { id:"REQ-2045", name:"Liam O'Brien",   status:"queued"  },
  { id:"REQ-2046", name:"Amélie Dupont",  status:"queued"  },
];

const STATUS = {
  running: { color:C.green, label:"running…", glow:true  },
  halted:  { color:C.red,   label:"halted",   glow:false },
  queued:  { color:C.muted, label:"queued",   glow:false },
};

const TERMINAL_STATUSES = new Set([
  "awaiting_decision", "authorized", "rejected", "halted", "blocked_gate", "error",
]);

const sleep = ms => new Promise(r => setTimeout(r, ms));

// Strip leading header line ([PASS]/[FAIL]/[HALT]/🚨) and trailing model attribution
function cleanSummary(text) {
  if (!text) return "";
  // Strip markdown bold (**) and backticks
  let t = text.replace(/\*\*/g, "").replace(/`/g, "");
  const paras = t.split(/\n\n+/);
  const first = (paras[0] || "").trim();
  const isHeader = /^\[(?:PASS|FAIL|HALT)\]/.test(first) || /^🚨/.test(first);
  const last = (paras[paras.length - 1] || "").trim();
  const isModelLine = /^[\*]?Model:/.test(last);
  const start = isHeader ? 1 : 0;
  const end = isModelLine ? paras.length - 1 : paras.length;
  return paras.slice(start, end).join("\n\n").trim();
}

// Build the animated message array from a real evidence package
function buildMessages(pkg) {
  const agents = pkg.agent_evidence || [];
  const seal   = pkg.consensus_seal  || {};
  const explain = pkg.explainability || {};
  const cs     = pkg.case_summary    || {};

  const val = (cs.asset_value_eur || 0) >= 1e6
    ? `€${((cs.asset_value_eur || 0) / 1e6).toFixed(1)}M`
    : `€${((cs.asset_value_eur || 0) / 1e3).toFixed(0)}K`;

  const msgs = [];

  // Opening orchestrator message
  msgs.push({
    from:  "orchestrator",
    text:  `Case ${cs.request_id || ""} opened — ${cs.asset_type || ""} ${val}. @Doc_Auditor please verify the submitted documentation and title records.`,
    delay: 700,
    lat:   null,
  });

  for (let i = 0; i < agents.length; i++) {
    const agent = agents[i];
    const key   = AGENT_KEY_MAP[agent.agent_name];
    if (!key) continue;

    // Real agent bubble
    msgs.push({
      from:    key,
      text:    cleanSummary(agent.summary) || agent.summary || "(no summary available)",
      delay:   agent.latency_ms > 0 ? Math.min(agent.latency_ms, 1700) : 1000,
      lat:     agent.latency_ms > 0 ? parseFloat((agent.latency_ms / 1000).toFixed(1)) : null,
      verdict: {
        status: agent.verdict,
        label:  agent.verdict === "pass" ? "PASS" : agent.verdict === "halt" ? "HALT" : "FAIL",
      },
    });

    // Orchestrator routing to next agent (if there is one)
    const next = agents[i + 1];
    if (next && ORCH_ROUTES[next.agent_name]) {
      msgs.push({
        from:  "orchestrator",
        text:  ORCH_ROUTES[next.agent_name],
        delay: 650,
        lat:   null,
      });
    }
  }

  // Final orchestrator recommendation
  const isHalted = pkg.governance_gate?.gate_outcome === "halt";
  const sealChip = seal.status === "sealed"
    ? `SEALED · ${(seal.canonical_hash || "").slice(0, 22)}…`
    : seal.status === "blocked"
    ? `HALTED · gate: ${seal.failed_gate || "unknown"}`
    : null;

  msgs.push({
    from:     "orchestrator",
    text:     explain.recommendation || explain.headline || "Analysis complete. Handing to Head of Digital Assets for final decision.",
    delay:    1100,
    lat:      null,
    final:    true,
    halted:   isHalted,
    sealChip,
  });

  return msgs;
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
  const isPass    = m.verdict?.status === "pass";
  const vColor    = isPass ? C.green : C.red;
  const chipColor = m.sealChip?.startsWith("SEALED") ? C.cyan : C.red;
  return (
    <div style={{ display:"flex", gap:9, maxWidth:"82%" }}>
      <span style={{ width:30, height:30, borderRadius:"50%", background:`${a.color}22`, border:`1px solid ${a.color}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, flexShrink:0 }}>{a.icon}</span>
      <div style={{ minWidth:0 }}>
        <div style={{ display:"flex", alignItems:"baseline", gap:7, marginBottom:3 }}>
          <span style={{ fontSize:10.5, fontWeight:800, color:a.color }}>{a.name}</span>
          {m.lat != null && <span style={{ fontSize:8, color:C.muted }}>{m.lat}s</span>}
        </div>
        <div style={{ background:C.navyLight, border:`1px solid ${m.final ? (m.halted ? C.red : C.gold)+"66" : C.border}`, borderRadius:"3px 12px 12px 12px", padding:"9px 12px", fontSize:11.5, lineHeight:1.5, color:C.white, whiteSpace:"pre-wrap" }}>
          {highlight(m.text)}
        </div>
        <div style={{ display:"flex", gap:6, flexWrap:"wrap", marginTop:6 }}>
          {m.verdict && (
            <span style={{ display:"inline-flex", alignItems:"center", gap:5, fontSize:9, fontWeight:700, color:vColor, background:`${vColor}1A`, border:`1px solid ${vColor}44`, padding:"3px 10px", borderRadius:20 }}>
              {isPass ? "✓" : "✕"} {m.verdict.label}
            </span>
          )}
          {m.sealChip && (
            <span style={{ display:"inline-flex", alignItems:"center", gap:5, fontSize:9, fontWeight:700, color:chipColor, background:`${chipColor}1A`, border:`1px solid ${chipColor}44`, padding:"3px 10px", borderRadius:20 }}>
              🔐 {m.sealChip}
            </span>
          )}
        </div>
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
  const { id }    = useParams();
  const navigate  = useNavigate();
  const { user }  = useSession();

  const caseId       = id || "REQ-2041";
  const sidebarEntry = SIDEBAR_ORDER.find(s => s.id === caseId);
  const displayName  = sidebarEntry?.name ?? caseId;

  // Fetch phase: "loading" | "ready" | "error"
  const [phase,    setPhase]    = useState("loading");
  const [pkg,      setPkg]      = useState(null);
  const [messages, setMessages] = useState([]);
  const [errorMsg, setErrorMsg] = useState(null);

  // Animation state
  const [shown,  setShown]  = useState([]);
  const [typing, setTyping] = useState(null);
  const [done,   setDone]   = useState(false);
  const scrollRef = useRef(null);

  // ── Fetch / poll for evidence package ────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    setPhase("loading");
    setPkg(null);
    setMessages([]);
    setShown([]);
    setTyping(null);
    setDone(false);
    setErrorMsg(null);

    async function loadPackage() {
      let p = null;

      // 1. Try fetching package directly (case may already be processed)
      try {
        const raw = await getEvidencePackage(caseId);
        // A real package has package_metadata; a 202 "not ready" response has detail
        if (raw?.package_metadata) p = raw;
      } catch (_) {
        // 404 or network error — fall through to trigger run
      }

      if (!p) {
        // 2. Trigger pipeline (ignore 409 = already running or terminal state)
        try {
          await runCase(caseId, { force: false });
        } catch (e) {
          if (e.status !== 409) {
            if (!cancelled) {
              setErrorMsg("Couldn't start the pipeline — " + (e.message || "unknown error"));
              setPhase("error");
            }
            return;
          }
        }

        // 3. Poll status until a terminal state is reached (max ~60 s)
        for (let i = 0; i < 20; i++) {
          await sleep(3000);
          if (cancelled) return;
          try {
            const st = await getCaseStatus(caseId);
            if (TERMINAL_STATUSES.has(st.status)) break;
          } catch (_) {}
        }

        // 4. Fetch package now that pipeline is done
        if (cancelled) return;
        try {
          const raw = await getEvidencePackage(caseId);
          if (raw?.package_metadata) p = raw;
        } catch (_) {}
      }

      if (!p) {
        if (!cancelled) {
          setErrorMsg("Couldn't load the analysis — backend may still be processing.");
          setPhase("error");
        }
        return;
      }

      if (!cancelled) {
        setPkg(p);
        setMessages(buildMessages(p));
        setPhase("ready");
      }
    }

    loadPackage();
    return () => { cancelled = true; };
  }, [caseId]);

  // ── Animation tick loop — runs once messages are available ────────────────────
  useEffect(() => {
    if (phase !== "ready" || messages.length === 0) return;
    let cancelled = false;
    setShown([]);
    setTyping(null);
    setDone(false);
    let i = 0;

    const tick = () => {
      if (cancelled) return;
      if (i >= messages.length) { setTyping(null); setDone(true); return; }
      const m = messages[i];
      setTyping(m.from);
      const wait = Math.min(m.delay || 900, 1700);
      setTimeout(() => {
        if (cancelled) return;
        setTyping(null);
        setShown(prev => [...prev, m]);
        i++;
        setTimeout(tick, 450);
      }, wait);
    };

    const start = setTimeout(tick, 700);
    return () => { cancelled = true; clearTimeout(start); };
  }, [phase, messages]);

  // Auto-scroll
  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [shown, typing]);

  // Derive display values from package
  const isHalted  = pkg?.governance_gate?.gate_outcome === "halt";
  const headline  = pkg?.explainability?.headline || "";
  const badgeColor = done ? (isHalted ? C.red : C.green) : C.amber;
  const badgeLabel = phase === "loading"
    ? "LOADING"
    : done ? (isHalted ? "HALTED" : "COMPLETE") : "LIVE";

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
          {SIDEBAR_ORDER.map(ch => {
            const active = ch.id === caseId;
            const cst    = STATUS[ch.status];
            return (
              <div key={ch.id} onClick={() => navigate(`/room/${ch.id}`)}
                style={{ display:"flex", alignItems:"center", gap:10, padding:"9px 14px", cursor:"pointer", background:active ? `linear-gradient(90deg, ${C.gold}18, transparent)` : "none", borderLeft:active ? `3px solid ${C.gold}` : "3px solid transparent", opacity:ch.status === "queued" ? 0.55 : 1 }}>
                <Identicon seed={ch.id} size={30}/>
                <div style={{ flex:1, minWidth:0 }}>
                  <span style={{ fontSize:11.5, fontWeight:active ? 700 : 600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis", display:"block" }}>{ch.name}</span>
                  <div style={{ fontSize:9, color:cst.color, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{ch.id} · {cst.label}</div>
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

          {/* Ready: animated bubbles */}
          {phase === "ready" && (
            <>
              {shown.map((m, i) => <Bubble key={i} m={m}/>)}
              {typing && <Typing who={typing}/>}
              {done && (
                <div style={{ textAlign:"center", marginTop:6 }}>
                  <span style={{ fontSize:8.5, color:isHalted ? C.red : C.green, background:`${isHalted ? C.red : C.green}1A`, border:`1px solid ${isHalted ? C.red : C.green}44`, padding:"4px 14px", borderRadius:20, fontWeight:700, letterSpacing:"0.5px" }}>
                    {headline || (isHalted ? "ANALYSIS COMPLETE · RECOMMENDATION: HALT" : "ANALYSIS COMPLETE · RECOMMENDATION: APPROVE")}
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
