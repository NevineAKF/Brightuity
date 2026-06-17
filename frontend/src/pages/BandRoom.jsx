import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";

const C = {
  bg:"#050D1A", navy:"#0A1A2F", navyLight:"#0F2340", border:"#1A3A5C",
  gold:"#E8A93D", goldLight:"#F0C75E", cyan:"#4FC3F7", green:"#4CAF50",
  amber:"#FF9800", red:"#EF5350", purple:"#A78BFA", white:"#F0F4FF", muted:"#6B8CAE",
};

const AGENTS = {
  orchestrator:{ name:"Orchestrator", icon:"🎯", color:C.gold },
  doc:{ name:"Doc Auditor", icon:"📄", color:C.cyan },
  kyc:{ name:"KYC Guardian", icon:"🛡️", color:C.green },
  compliance:{ name:"Dynamic Compliance", icon:"⚖️", color:C.gold },
  risk:{ name:"Stress-Test Simulator", icon:"📈", color:C.amber },
  tokenizer:{ name:"Asset Tokenizer", icon:"🪙", color:C.purple },
  signer:{ name:"Consensus Signer", icon:"🔐", color:C.red },
};

const CASES = {
  "REQ-2041": {
    name:"Marcus Weber", flagCode:"DE", asset:"Commercial Real Estate", value:"€2.50M",
    loc:"Frankfurt, Germany", status:"running", recommendation:"APPROVE",
    conversation:[
      { from:"orchestrator", text:"New case EVP-DOC-3F2A. @Doc_Auditor verify ownership documents and title deed.", delay:900, lat:0.6 },
      { from:"doc", text:"@Orchestrator Documents verified. Title deed authentic, ownership confirmed, no liens. Property value €2.5M confirmed.", delay:1700, lat:1.8, verdict:{ status:"pass", label:"Documents Verified" } },
      { from:"orchestrator", text:"Docs cleared. @KYC_Guardian run identity & AML check.", delay:1000, lat:0.5 },
      { from:"kyc", text:"@Orchestrator Identity verified. No sanctions match, no PEP flag. Source of funds legitimate. Risk profile: LOW.", delay:1800, lat:2.1, verdict:{ status:"pass", label:"Identity Cleared" } },
      { from:"orchestrator", text:"@Dynamic_Compliance check against EU MiCA & German property law.", delay:1000, lat:0.5 },
      { from:"compliance", text:"@Orchestrator Fully compliant with MiCA Art. 4, AMLD5, and BGB property law. No regulatory blockers. Sources cited in report.", delay:1800, lat:2.3, verdict:{ status:"pass", label:"Compliant (MiCA)" } },
      { from:"orchestrator", text:"@Stress_Test_Simulator run valuation & risk scenarios.", delay:1000, lat:0.4 },
      { from:"risk", text:"@Orchestrator Stress tests complete. Fair value €2.5M ±3%. Risk score 24/100 (LOW). Stable under downturn scenarios.", delay:1800, lat:2.0, verdict:{ status:"pass", label:"Risk: Low (24/100)" } },
      { from:"orchestrator", text:"All gates cleared. @Asset_Tokenizer structure the token.", delay:1000, lat:0.4 },
      { from:"tokenizer", text:"@Orchestrator Token structured: 2,500 tokens @ €1,000 each. ERC-3643 class, KYC-gated transfers, governance encoded.", delay:1800, lat:1.9, verdict:{ status:"pass", label:"Token Structured" } },
      { from:"orchestrator", text:"@Consensus_Signer seal the record.", delay:1000, lat:0.3 },
      { from:"signer", text:"@Orchestrator Consensus verified across all gates. Deterministic Gateway Proof issued: DGP-7F3A-2041. Record sealed. ✅", delay:1700, lat:0.9, verdict:{ status:"pass", label:"Proof Issued" } },
      { from:"orchestrator", text:"Analysis complete. All 6 gates cleared. Recommendation: APPROVE. Handing to Head of Digital Assets for final decision.", delay:1200, lat:0.7, final:true },
    ],
  },
  "REQ-2043": {
    name:"Viktor Petrov", flagCode:"BG", asset:"Gold Reserve", value:"€1.20M",
    loc:"Sofia, Bulgaria", status:"halted", recommendation:"REJECT",
    conversation:[
      { from:"orchestrator", text:"New case EVP-DOC-2C8F. @Doc_Auditor verify custody documents and assay certificate.", delay:900, lat:0.6 },
      { from:"doc", text:"@Orchestrator Documents verified. Assay certificate authentic, 1,200 troy oz confirmed, custody chain intact. Value €1.2M consistent with spot price.", delay:1700, lat:1.7, verdict:{ status:"pass", label:"Documents Verified" } },
      { from:"orchestrator", text:"Docs cleared. @KYC_Guardian run identity & AML check.", delay:1000, lat:0.5 },
      { from:"kyc", text:"@Orchestrator ⚠️ ALERT — PEP match confirmed. Subject linked to politically exposed network. Source of funds: unverifiable offshore structures. Risk profile: CRITICAL.", delay:1900, lat:2.4, verdict:{ status:"fail", label:"PEP Match — CRITICAL" } },
      { from:"orchestrator", text:"Governance gate triggered: KYC failure is a hard stop. Halting pipeline — Compliance, Risk, and Tokenization will not execute. Recommendation: REJECT. Escalating to Head of Digital Assets.", delay:1400, lat:0.8, final:true, halted:true },
    ],
  },
};

const SIDEBAR_ORDER = [
  { id:"REQ-2041", name:"Marcus Weber",   flagCode:"DE", status:"running" },
  { id:"REQ-2042", name:"Sofia Andreou",  flagCode:"GR", status:"queued"  },
  { id:"REQ-2043", name:"Viktor Petrov",  flagCode:"BG", status:"halted"  },
  { id:"REQ-2044", name:"Isabella Rossi", flagCode:"IT", status:"queued"  },
  { id:"REQ-2045", name:"Liam O'Brien",   flagCode:"IE", status:"queued"  },
  { id:"REQ-2046", name:"Amélie Dupont",  flagCode:"FR", status:"queued"  },
];

const STATUS = {
  running:{ color:C.green, label:"running…", glow:true },
  halted:{ color:C.red, label:"halted", glow:false },
  queued:{ color:C.muted, label:"queued", glow:false },
};

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

function highlight(text){
  return text.split(/(@[A-Za-z_]+)/g).map((p,i)=> p.startsWith("@")
    ? <span key={i} style={{ color:C.gold, fontWeight:700 }}>{p}</span>
    : <span key={i}>{p}</span>);
}

function Bubble({ m }){
  const a = AGENTS[m.from];
  const vColor = m.verdict?.status==="fail" ? C.red : C.green;
  return (
    <div style={{ display:"flex", gap:9, maxWidth:"82%" }}>
      <span style={{ width:30, height:30, borderRadius:"50%", background:`${a.color}22`, border:`1px solid ${a.color}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:13, flexShrink:0 }}>{a.icon}</span>
      <div style={{ minWidth:0 }}>
        <div style={{ display:"flex", alignItems:"baseline", gap:7, marginBottom:3 }}>
          <span style={{ fontSize:10.5, fontWeight:800, color:a.color }}>{a.name}</span>
          {m.lat!=null && <span style={{ fontSize:8, color:C.muted }}>{m.lat}s</span>}
        </div>
        <div style={{ background:C.navyLight, border:`1px solid ${m.final?(m.halted?C.red:C.gold)+"66":C.border}`, borderRadius:"3px 12px 12px 12px", padding:"9px 12px", fontSize:11.5, lineHeight:1.5, color:C.white }}>{highlight(m.text)}</div>
        {m.verdict && (
          <span style={{ display:"inline-flex", alignItems:"center", gap:5, marginTop:6, fontSize:9, fontWeight:700, color:vColor, background:`${vColor}1A`, border:`1px solid ${vColor}44`, padding:"3px 10px", borderRadius:20 }}>
            {m.verdict.status==="fail" ? "✕" : "✓"} {m.verdict.label}
          </span>
        )}
      </div>
    </div>
  );
}

function Typing({ who }){
  const a = AGENTS[who];
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

export default function BandRoom(){
  const { id } = useParams();
  const navigate = useNavigate();
  const { user } = useSession();
  const caseId = CASES[id] ? id : "REQ-2041";
  const data = CASES[caseId];
  const convo = data.conversation;
  const [shown, setShown] = useState([]);
  const [typing, setTyping] = useState(null);
  const [done, setDone] = useState(false);
  const scrollRef = useRef(null);

  useEffect(()=>{
    let cancelled = false;
    setShown([]); setTyping(null); setDone(false);
    let i = 0;
    const tick = ()=>{
      if (cancelled) return;
      if (i >= convo.length){ setTyping(null); setDone(true); return; }
      const m = convo[i];
      setTyping(m.from);
      const wait = Math.min(m.delay, 1700);
      setTimeout(()=>{
        if (cancelled) return;
        setTyping(null);
        setShown(prev=>[...prev, m]);
        i++;
        setTimeout(tick, 450);
      }, wait);
    };
    const start = setTimeout(tick, 700);
    return ()=>{ cancelled = true; clearTimeout(start); };
  }, [caseId]);

  useEffect(()=>{ if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight; }, [shown, typing]);

  const st = STATUS[data.status];

  return (
    <div style={{ minHeight:"100vh", background:C.bg, fontFamily:"'Montserrat', system-ui, sans-serif", color:C.white, display:"flex" }}>
      <style>{`@keyframes bdot{0%,60%,100%{transform:translateY(0);opacity:0.4}30%{transform:translateY(-4px);opacity:1}} .bdot{width:6px;height:6px;border-radius:50%;background:${C.muted};display:inline-block;animation:bdot 1.2s infinite}`}</style>

      {/* SIDEBAR */}
      <div style={{ width:256, flexShrink:0, background:C.navy, borderRight:`1px solid ${C.border}`, display:"flex", flexDirection:"column", height:"100vh", position:"sticky", top:0 }}>
        <div onClick={()=>navigate("/dashboard")} style={{ padding:"15px 16px", borderBottom:`1px solid ${C.border}`, display:"flex", alignItems:"center", gap:9, cursor:"pointer" }}>
          <svg width="22" height="22" viewBox="0 0 64 64"><polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="none" stroke={C.gold} strokeWidth="2"/><text x="32" y="42" textAnchor="middle" fill={C.gold} fontSize="24" fontWeight="800">B</text></svg>
          <div style={{ minWidth:0 }}><div style={{ fontSize:12, fontWeight:800, letterSpacing:"1px" }}>CASE ROOMS</div><div style={{ fontSize:8, color:C.muted, letterSpacing:"0.5px" }}>BAND COORDINATION</div></div>
        </div>
        <div style={{ fontSize:8.5, color:C.muted, letterSpacing:"1.5px", padding:"12px 16px 8px" }}>CHANNELS</div>
        <div style={{ flex:1, overflowY:"auto" }}>
          {SIDEBAR_ORDER.map(ch=>{
            const active = ch.id===caseId;
            const cst = STATUS[ch.status];
            return (
              <div key={ch.id} onClick={()=>navigate(`/room/${ch.id}`)} style={{ display:"flex", alignItems:"center", gap:10, padding:"9px 14px", cursor:"pointer", background:active?`linear-gradient(90deg, ${C.gold}18, transparent)`:"none", borderLeft:active?`3px solid ${C.gold}`:"3px solid transparent", opacity:ch.status==="queued"?0.55:1 }}>
                <Identicon seed={ch.id} size={30}/>
                <div style={{ flex:1, minWidth:0 }}>
                  <span style={{ fontSize:11.5, fontWeight:active?700:600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis", display:"block" }}>{ch.name}</span>
                  <div style={{ fontSize:9, color:cst.color, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{ch.id} · {cst.label}</div>
                </div>
                <span style={{ width:7, height:7, borderRadius:"50%", background:cst.color, flexShrink:0, boxShadow:cst.glow?`0 0 7px ${cst.color}`:"none" }}/>
              </div>
            );
          })}
        </div>
        <div style={{ padding:"12px 14px", borderTop:`1px solid ${C.border}`, display:"flex", alignItems:"center", gap:8 }}>
          <div style={{ width:26, height:26, borderRadius:"50%", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, display:"flex", alignItems:"center", justifyContent:"center", color:C.navy, fontWeight:800, fontSize:9, flexShrink:0 }}>{(user?.name??"Nevine AKF").split(" ").map(w=>w[0]).join("")}</div>
          <div style={{ minWidth:0 }}><div style={{ fontSize:10, fontWeight:600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{user?.name??"Nevine AKF"}</div><div style={{ fontSize:8, color:C.muted }}>Observer</div></div>
        </div>
      </div>

      {/* MAIN */}
      <div style={{ flex:1, display:"flex", flexDirection:"column", minWidth:0, height:"100vh" }}>
        <div style={{ padding:"12px 18px", borderBottom:`1px solid ${C.border}`, background:C.navy, display:"flex", alignItems:"center", gap:12 }}>
          <div style={{ minWidth:0, flex:1 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <span style={{ fontSize:13, fontWeight:800, whiteSpace:"nowrap" }}>{data.name}</span>
              <span style={{ fontSize:9, color:C.muted, fontFamily:"monospace" }}>{caseId}</span>
              <span style={{ fontSize:8, fontWeight:700, color:st.color, background:`${st.color}1A`, border:`1px solid ${st.color}44`, padding:"2px 8px", borderRadius:20, whiteSpace:"nowrap" }}>● {data.status==="halted"?"HALTED":done?"COMPLETE":"LIVE"}</span>
            </div>
            <div style={{ fontSize:9.5, color:C.muted, marginTop:2, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{data.asset} · {data.value} · 7 agents coordinating through Band</div>
          </div>
        </div>

        <div ref={scrollRef} style={{ flex:1, overflowY:"auto", padding:"16px 18px", display:"flex", flexDirection:"column", gap:13, background:"linear-gradient(180deg, #050D1A, #07101f)" }}>
          <div style={{ textAlign:"center" }}><span style={{ fontSize:8.5, color:C.muted, background:C.navyLight, border:`1px solid ${C.border}`, padding:"3px 12px", borderRadius:20 }}>🔒 Band Room opened · agents coordinate autonomously · you are observing</span></div>
          {shown.map((m,i)=><Bubble key={i} m={m}/>)}
          {typing && <Typing who={typing}/>}
          {done && (
            <div style={{ textAlign:"center", marginTop:6 }}>
              <span style={{ fontSize:8.5, color:data.recommendation==="APPROVE"?C.green:C.red, background:`${data.recommendation==="APPROVE"?C.green:C.red}1A`, border:`1px solid ${data.recommendation==="APPROVE"?C.green:C.red}44`, padding:"4px 14px", borderRadius:20, fontWeight:700, letterSpacing:"0.5px" }}>
                ANALYSIS COMPLETE · RECOMMENDATION: {data.recommendation}
              </span>
            </div>
          )}
        </div>

        <div style={{ padding:"12px 18px", borderTop:`1px solid ${C.border}`, background:C.navy, display:"flex", alignItems:"center", justifyContent:"space-between", gap:12 }}>
          <span style={{ fontSize:9.5, color:C.muted, display:"flex", alignItems:"center", gap:6, minWidth:0 }}>
            <span style={{ width:6, height:6, borderRadius:"50%", background:done?C.gold:C.green, flexShrink:0 }}/>
            <span style={{ whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>You are observing — agents coordinate autonomously. No human input in this room.</span>
          </span>
          <button onClick={()=>done&&navigate(`/review/${caseId}`)} disabled={!done} style={{ background:done?`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`:C.navyLight, border:done?"none":`1px solid ${C.border}`, borderRadius:9, padding:"9px 16px", color:done?C.navy:C.muted, fontSize:11, fontWeight:800, fontFamily:"inherit", cursor:done?"pointer":"not-allowed", whiteSpace:"nowrap", flexShrink:0, transition:"all 0.3s" }}>Open Decision Evidence Package →</button>
        </div>
      </div>
    </div>
  );
}
