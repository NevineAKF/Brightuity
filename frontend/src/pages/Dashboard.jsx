import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";

const C = {
  bg:"#050D1A", navy:"#0A1A2F", navyLight:"#0F2340", border:"#1A3A5C",
  gold:"#E8A93D", goldLight:"#F0C75E", cyan:"#4FC3F7", green:"#4CAF50",
  amber:"#FF9800", white:"#F0F4FF", muted:"#6B8CAE",
};

function Flag({ code, w=20 }) {
  const h = Math.round(w*0.67);
  const f = {
    DE:<g><rect width="90" height="20" fill="#000"/><rect y="20" width="90" height="20" fill="#D00"/><rect y="40" width="90" height="20" fill="#FFCE00"/></g>,
    BG:<g><rect width="90" height="20" fill="#fff"/><rect y="20" width="90" height="20" fill="#00966E"/><rect y="40" width="90" height="20" fill="#D62612"/></g>,
    IT:<g><rect width="30" height="60" fill="#009246"/><rect x="30" width="30" height="60" fill="#fff"/><rect x="60" width="30" height="60" fill="#CE2B37"/></g>,
    IE:<g><rect width="30" height="60" fill="#169B62"/><rect x="30" width="30" height="60" fill="#fff"/><rect x="60" width="30" height="60" fill="#FF883E"/></g>,
    FR:<g><rect width="30" height="60" fill="#0055A4"/><rect x="30" width="30" height="60" fill="#fff"/><rect x="60" width="30" height="60" fill="#EF4135"/></g>,
    GR:<g><rect width="90" height="60" fill="#0D5EAF"/><rect y="6.7" width="90" height="6.7" fill="#fff"/><rect y="20" width="90" height="6.7" fill="#fff"/><rect y="33.3" width="90" height="6.7" fill="#fff"/><rect y="46.7" width="90" height="6.7" fill="#fff"/><rect width="33.3" height="33.3" fill="#0D5EAF"/><rect x="13.3" width="6.7" height="33.3" fill="#fff"/><rect y="13.3" width="33.3" height="6.7" fill="#fff"/></g>,
  };
  return <svg viewBox="0 0 90 60" width={w} height={h} style={{ borderRadius:2, flexShrink:0, verticalAlign:"middle", border:"1px solid rgba(255,255,255,0.15)" }}>{f[code]||null}</svg>;
}

const REQUESTS = [
  { id:"REQ-2041", name:"Marcus Weber",   flagCode:"DE", nationality:"German",    asset:"Commercial Real Estate", detail:"Grade A office, Frankfurt", assetFlagCode:"DE", assetLoc:"Frankfurt, Germany", jurisdiction:"EU · MiCA", value:2500000, docId:"EVP-DOC-3F2A9C4E", priority:"High",   submitted:"Today, 09:14" },
  { id:"REQ-2042", name:"Sofia Andreou",  flagCode:"GR", nationality:"Greek",     asset:"Residential Property",   detail:"Luxury apartment, Athens",  assetFlagCode:"GR", assetLoc:"Athens, Greece",   jurisdiction:"EU · MiCA", value:850000,  docId:"EVP-DOC-7B1D5E8A", priority:"Low",    submitted:"Today, 08:52" },
  { id:"REQ-2043", name:"Viktor Petrov",  flagCode:"BG", nationality:"Bulgarian", asset:"Gold Reserve",           detail:"1,200 troy oz bullion",    assetFlagCode:"BG", assetLoc:"Sofia, Bulgaria",  jurisdiction:"EU · MiCA", value:1200000, docId:"EVP-DOC-2C8F1A3D", priority:"High",   submitted:"Today, 10:31" },
  { id:"REQ-2044", name:"Isabella Rossi", flagCode:"IT", nationality:"Italian",   asset:"Commercial Real Estate", detail:"Mixed-use complex, Milan", assetFlagCode:"IT", assetLoc:"Milan, Italy",     jurisdiction:"EU · MiCA", value:4200000, docId:"EVP-DOC-9A4C7E2B", priority:"High",   submitted:"Yesterday, 17:20" },
  { id:"REQ-2045", name:"Liam O'Brien",   flagCode:"IE", nationality:"Irish",     asset:"Government Bond Portfolio", detail:"EU sovereign bonds, AAA", assetFlagCode:"IE", assetLoc:"Dublin, Ireland", jurisdiction:"EU · MiCA", value:5750000, docId:"EVP-DOC-4D3B6F1C", priority:"Medium", submitted:"Yesterday, 14:05" },
  { id:"REQ-2046", name:"Amélie Dupont",  flagCode:"FR", nationality:"French",    asset:"Fine Art Collection",    detail:"12 provenance-verified",   assetFlagCode:"FR", assetLoc:"Paris, France",    jurisdiction:"EU · MiCA", value:3100000, docId:"EVP-DOC-6E9A2C5D", priority:"Medium", submitted:"Yesterday, 11:48" },
];

const DONE = 2;
const TOTAL = REQUESTS.length;
const fmtEur = v => "€" + (v >= 1000000 ? (v/1000000).toFixed(2)+"M" : (v/1000).toFixed(0)+"K");
const PRI = {
  High:   { color:C.amber, bg:"#FF980018", border:"#FF980055", bar:C.amber },
  Medium: { color:C.cyan,  bg:"#4FC3F718", border:"#4FC3F755", bar:C.cyan  },
  Low:    { color:C.muted, bg:"#6B8CAE18", border:"#6B8CAE55", bar:C.muted },
};

function Identicon({ seed, size=46 }) {
  let h = 5381;
  for (let i=0;i<seed.length;i++) h = (((h<<5)+h)+seed.charCodeAt(i))|0;
  h = Math.abs(h);
  const ACCENTS = [C.cyan, C.gold, C.muted];
  const accent = ACCENTS[h % 3];
  const pad = 6, n = 5, cell = (size - pad*2)/n;
  const filled = [];
  for (let r=0;r<n;r++) for (let col=0;col<n;col++){
    const m = col<3 ? col : 4-col;
    if ((h >> (r*3+m)) & 1) filled.push({r,col});
  }
  return (
    <div style={{ position:"relative", flexShrink:0, width:size, height:size }}>
      <svg width={size} height={size}>
        <rect width={size} height={size} rx={12} fill={C.navyLight} stroke={`${C.cyan}44`} strokeWidth="1"/>
        {filled.map(({r,col}) => (
          <rect key={`${r}-${col}`} x={pad+col*cell+0.5} y={pad+r*cell+0.5} width={cell-1} height={cell-1} rx={2} fill={accent} opacity={0.82}/>
        ))}
      </svg>
      <div style={{ position:"absolute", bottom:-2, right:-2, width:15, height:15, borderRadius:"50%", background:C.green, border:`2px solid ${C.bg}`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:7, color:"#fff", fontWeight:900 }}>✓</div>
    </div>
  );
}

function CaseCard({ c, onReview, onProcess }) {
  const [hov, setHov] = useState(false);
  const p = PRI[c.priority] ?? PRI.Low;
  return (
    <div onMouseEnter={()=>setHov(true)} onMouseLeave={()=>setHov(false)}
      style={{ background:`linear-gradient(135deg, ${C.navy}, ${C.bg})`, borderTop:`1px solid ${C.border}`, borderRight:`1px solid ${C.border}`, borderBottom:`1px solid ${C.border}`, borderLeft:`4px solid ${p.bar}`, borderRadius:16, display:"flex", flexDirection:"column", overflow:"hidden", transition:"all 0.2s", transform:hov?"translateY(-3px)":"none", boxShadow:hov?`0 14px 40px rgba(0,0,0,0.55)`:"0 2px 12px rgba(0,0,0,0.35)" }}>
      <div style={{ display:"flex", alignItems:"center", gap:11, padding:"15px 15px 11px" }}>
        <Identicon seed={c.id} size={46}/>
        <div style={{ flex:1, minWidth:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:7, marginBottom:4 }}>
            <span style={{ fontSize:14, fontWeight:700, minWidth:0, overflow:"hidden", whiteSpace:"nowrap", textOverflow:"ellipsis" }}>{c.name}</span>
            <Flag code={c.flagCode} w={18}/>
            <span style={{ marginLeft:"auto", flexShrink:0, fontSize:8.5, fontWeight:700, letterSpacing:"0.5px", color:p.color, background:p.bg, border:`1px solid ${p.border}`, padding:"2px 8px", borderRadius:10 }}>{c.priority.toUpperCase()}</span>
          </div>
          <div style={{ fontSize:9.5, color:C.muted, fontFamily:"monospace", whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{c.id} · 🔒 {c.docId.slice(0,12)}</div>
        </div>
      </div>
      <div style={{ display:"flex", justifyContent:"space-between", gap:10, padding:"10px 15px", borderTop:`1px solid ${C.border}`, borderBottom:`1px solid ${C.border}` }}>
        <div style={{ minWidth:0 }}>
          <div style={{ fontSize:9, color:C.muted, letterSpacing:"1px", marginBottom:2 }}>ASSET</div>
          <div style={{ fontSize:12, fontWeight:600, whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{c.asset}</div>
          <div style={{ display:"flex", alignItems:"center", gap:5, fontSize:10, color:C.muted, marginTop:3, minWidth:0 }}>
            <Flag code={c.assetFlagCode} w={15}/>
            <span style={{ whiteSpace:"nowrap", overflow:"hidden", textOverflow:"ellipsis" }}>{c.assetLoc}</span>
          </div>
        </div>
        <div style={{ textAlign:"right", flexShrink:0 }}>
          <div style={{ fontSize:9, color:C.muted, letterSpacing:"1px", marginBottom:2 }}>VALUE</div>
          <div style={{ fontSize:16, fontWeight:800, color:C.gold }}>{fmtEur(c.value)}</div>
          <div style={{ fontSize:9, color:C.muted, marginTop:2 }}>{c.submitted}</div>
        </div>
      </div>
      <div style={{ display:"flex", gap:8, padding:"12px 15px" }}>
        <button onClick={()=>onReview(c)} style={{ flex:1, padding:"9px 0", background:"#1A3A5C33", border:`1px solid ${C.cyan}55`, borderRadius:8, color:C.cyan, fontSize:11, fontWeight:700, cursor:"pointer", fontFamily:"inherit" }}>Review Case</button>
        <button onClick={()=>onProcess(c.id)} style={{ flex:1, padding:"9px 0", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, border:"none", borderRadius:8, color:C.navy, fontSize:11, fontWeight:800, cursor:"pointer", fontFamily:"inherit" }}>▶ Start Processing</button>
      </div>
    </div>
  );
}

function Row({ label, value, mono, vStyle }) {
  return (
    <div style={{ display:"flex", alignItems:"center", gap:10, padding:"8px 12px", background:C.navyLight, borderRadius:8, border:`1px solid ${C.border}` }}>
      <span style={{ fontSize:10, color:C.muted, minWidth:130, flexShrink:0 }}>{label}</span>
      <span style={{ fontSize:12, color:C.white, fontFamily:mono?"monospace":"inherit", display:"flex", alignItems:"center", gap:7, ...(vStyle||{}) }}>{value}</span>
    </div>
  );
}

function Dossier({ c, onClose, onProcess }) {
  if (!c) return null;
  const p = PRI[c.priority] ?? PRI.Low;
  return (
    <div onMouseDown={onClose} style={{ position:"fixed", inset:0, zIndex:1000, background:"rgba(5,13,26,0.72)", display:"flex", alignItems:"center", justifyContent:"center", padding:20, backdropFilter:"blur(5px)" }}>
      <div onMouseDown={e=>e.stopPropagation()} style={{ position:"relative", width:"100%", maxWidth:520, background:`linear-gradient(160deg, ${C.navy}, ${C.bg})`, border:`1px solid ${C.gold}44`, borderRadius:18, padding:"34px 30px", maxHeight:"90vh", overflowY:"auto", boxShadow:`0 40px 100px rgba(0,0,0,0.7)` }}>
        <div style={{ position:"absolute", top:0, left:"50%", transform:"translateX(-50%)", width:100, height:2, background:`linear-gradient(90deg, transparent, ${C.gold}, transparent)` }}/>
        <button onClick={onClose} style={{ position:"absolute", top:14, right:14, width:28, height:28, borderRadius:"50%", background:C.navyLight, border:`1px solid ${C.border}`, color:C.muted, fontSize:15, cursor:"pointer", fontFamily:"inherit" }}>×</button>
        <div style={{ display:"flex", alignItems:"center", gap:13, marginBottom:22 }}>
          <Identicon seed={c.id} size={54}/>
          <div>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <span style={{ fontSize:17, fontWeight:800, color:C.white }}>{c.name}</span>
              <Flag code={c.flagCode} w={22}/>
            </div>
            <div style={{ fontSize:10.5, color:C.muted, marginTop:3 }}>Client Dossier · {c.id}</div>
            <span style={{ display:"inline-block", marginTop:7, fontSize:8.5, fontWeight:700, letterSpacing:"0.5px", color:C.green, background:"#4CAF501A", border:"1px solid #4CAF5044", padding:"3px 8px", borderRadius:20 }}>✓ DOCUMENTS ON FILE</span>
          </div>
        </div>
        <div style={{ fontSize:9, color:C.gold, letterSpacing:"1px", fontWeight:600, marginBottom:8 }}>CLIENT</div>
        <div style={{ display:"flex", flexDirection:"column", gap:7, marginBottom:18 }}>
          <Row label="Full Name" value={c.name}/>
          <Row label="Citizenship" value={<><Flag code={c.flagCode} w={20}/> {c.nationality}</>}/>
          <Row label="Encrypted Doc ID" value={`🔒 ${c.docId}`} mono vStyle={{ color:C.cyan }}/>
        </div>
        <div style={{ fontSize:9, color:C.gold, letterSpacing:"1px", fontWeight:600, marginBottom:8 }}>ASSET</div>
        <div style={{ display:"flex", flexDirection:"column", gap:7, marginBottom:24 }}>
          <Row label="Asset Type" value={c.asset} vStyle={{ fontWeight:600 }}/>
          <Row label="Description" value={c.detail}/>
          <Row label="Asset Location" value={<><Flag code={c.assetFlagCode} w={20}/> {c.assetLoc}</>}/>
          <Row label="Jurisdiction" value={c.jurisdiction}/>
          <Row label="Declared Value" value={fmtEur(c.value)} vStyle={{ color:C.gold, fontWeight:800, fontSize:15 }}/>
          <Row label="Submitted" value={c.submitted}/>
          <Row label="Priority" value={c.priority} vStyle={{ color:p.color, fontWeight:700 }}/>
        </div>
        <div style={{ display:"flex", gap:10 }}>
          <button onClick={onClose} style={{ flex:1, padding:"11px", background:"none", border:`1px solid ${C.border}`, borderRadius:10, color:C.muted, fontSize:12, fontWeight:600, cursor:"pointer", fontFamily:"inherit" }}>Close</button>
          <button onClick={()=>onProcess(c.id)} style={{ flex:2, padding:"11px", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, border:"none", borderRadius:10, color:C.navy, fontSize:12, fontWeight:800, cursor:"pointer", fontFamily:"inherit" }}>▶ Start Processing</button>
        </div>
      </div>
    </div>
  );
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { user, logout } = useSession();
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const today = new Date().toLocaleDateString("en-US", { weekday:"long", year:"numeric", month:"long", day:"numeric" });
  const firstName = user?.name?.split(" ")[0] ?? "Nevine";
  const handleProcess = id => navigate(`/room/${id}`);
  const filtered = search ? REQUESTS.filter(r => (r.name+r.id+r.asset).toLowerCase().includes(search.toLowerCase())) : REQUESTS;

  return (
    <div style={{ minHeight:"100vh", background:C.bg, fontFamily:"'Montserrat', system-ui, sans-serif" }}>
      <nav style={{ height:62, background:C.navyLight, borderBottom:`1px solid ${C.border}`, display:"flex", alignItems:"center", justifyContent:"space-between", padding:"0 24px", position:"sticky", top:0, zIndex:50 }}>
        <div style={{ display:"flex", alignItems:"center", gap:10, flexShrink:0 }}>
          <svg width="26" height="26" viewBox="0 0 64 64" fill="none"><polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="none" stroke={C.gold} strokeWidth="1.5"/><text x="32" y="41" textAnchor="middle" fill={C.gold} fontSize="22" fontWeight="800" fontFamily="Montserrat">B</text></svg>
          <div>
            <div style={{ fontSize:14, fontWeight:800, letterSpacing:"0.2em", color:C.white, lineHeight:1 }}>BRIGHT<span style={{ color:C.gold }}>UITY</span></div>
            <div style={{ fontSize:8, color:C.muted, letterSpacing:"0.12em" }}>RWA TOKENIZATION INTELLIGENCE</div>
          </div>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:18, flexShrink:0 }}>
          <div style={{ display:"flex", alignItems:"center", gap:10, flexShrink:0 }}>
            <div style={{ textAlign:"right", whiteSpace:"nowrap", flexShrink:0 }}>
              <div style={{ fontSize:12, fontWeight:600, color:C.white }}>{user?.name ?? "Nevine AKF"}</div>
              <div style={{ fontSize:9.5, color:C.muted }}>{user?.role ?? "Head of Digital Assets"}</div>
            </div>
            <div style={{ width:34, height:34, borderRadius:"50%", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, display:"flex", alignItems:"center", justifyContent:"center", fontSize:12, fontWeight:800, color:C.navy, flexShrink:0 }}>
              {(user?.name ?? "Nevine AKF").split(" ").map(w=>w[0]).join("")}
            </div>
          </div>
          <button onClick={()=>{ logout(); navigate("/login"); }} style={{ background:"none", border:`1px solid ${C.border}`, borderRadius:6, padding:"6px 12px", color:C.muted, fontSize:10, fontFamily:"inherit", cursor:"pointer", letterSpacing:"0.08em", whiteSpace:"nowrap", flexShrink:0 }}>SIGN OUT</button>
        </div>
      </nav>

      <main style={{ maxWidth:1280, margin:"0 auto", padding:"2rem 2rem 4rem" }}>
        <div style={{ fontSize:11, color:C.gold, marginBottom:8 }}>📅 {today}</div>
        <h1 style={{ margin:0, fontSize:22, fontWeight:800, color:C.white }}>Welcome, {firstName}</h1>
        <p style={{ margin:"4px 0 0", fontSize:12, color:C.muted }}>Head of Digital Assets &amp; Tokenization Division</p>
        <div style={{ display:"flex", gap:10, marginTop:18 }}>
          <div style={{ padding:"10px 20px", borderRadius:10, background:`${C.gold}12`, border:`1px solid ${C.gold}44`, display:"flex", alignItems:"baseline", gap:8 }}>
            <span style={{ fontSize:18, fontWeight:800, color:C.gold }}>{DONE}/{TOTAL}</span><span style={{ fontSize:10.5, color:C.muted }}>done today</span>
          </div>
          <div style={{ padding:"10px 20px", borderRadius:10, background:`${C.amber}12`, border:`1px solid ${C.amber}44`, display:"flex", alignItems:"baseline", gap:8 }}>
            <span style={{ fontSize:18, fontWeight:800, color:C.amber }}>{TOTAL - DONE}</span><span style={{ fontSize:10.5, color:C.muted }}>pending</span>
          </div>
        </div>
        <div style={{ marginTop:22, marginBottom:18, maxWidth:440, position:"relative" }}>
          <span style={{ position:"absolute", left:12, top:"50%", transform:"translateY(-50%)", color:C.muted, fontSize:14 }}>🔍</span>
          <input value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search by name, ID, or asset type…" style={{ width:"100%", boxSizing:"border-box", padding:"11px 14px 11px 36px", background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:10, color:C.white, fontSize:13, outline:"none", fontFamily:"inherit" }}/>
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:12, marginBottom:14 }}>
          <span style={{ fontSize:10.5, fontWeight:700, color:C.muted, letterSpacing:"0.14em", whiteSpace:"nowrap" }}>PENDING REQUESTS</span>
          <div style={{ flex:1, height:1, background:C.border }}/>
        </div>
        <div style={{ display:"grid", gridTemplateColumns:"repeat(auto-fill, minmax(320px, 1fr))", gap:15 }}>
          {filtered.map(c => <CaseCard key={c.id} c={c} onReview={setSelected} onProcess={handleProcess}/>)}
        </div>
      </main>

      {selected && <Dossier c={selected} onClose={()=>setSelected(null)} onProcess={id=>{ setSelected(null); handleProcess(id); }}/>}
    </div>
  );
}
