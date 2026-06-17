import { useState, useEffect, useRef } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";
import { evidencePdfUrl } from "../api/client.js";
import * as THREE from "three";

const C = {
  bg:"#050D1A", navy:"#0A1A2F", navyLight:"#0F2340", border:"#1A3A5C",
  gold:"#E8A93D", goldLight:"#F0C75E", cyan:"#4FC3F7", green:"#4CAF50",
  amber:"#FF9800", red:"#EF5350", purple:"#A78BFA", white:"#F0F4FF", muted:"#6B8CAE",
};

const CASES = {
  "REQ-2041": {
    name:"Marcus Weber", flagCode:"DE", asset:"Commercial Real Estate", value:"€2.50M",
    recommendation:"APPROVE", proof:"DGP-7F3A-2041",
    report:[
      { key:"doc",   icon:"📄", color:C.cyan,   name:"Doc Auditor",          status:"PASS",     text:"Title deed authentic, ownership confirmed, no liens. Value €2.5M confirmed against registry." },
      { key:"kyc",   icon:"🛡️", color:C.green,  name:"KYC Guardian",         status:"PASS",     text:"Identity verified. No sanctions, no PEP flag. Source of funds legitimate. Risk: LOW." },
      { key:"comp",  icon:"⚖️", color:C.gold,   name:"Dynamic Compliance",   status:"PASS",     text:"Compliant with MiCA Art. 4, AMLD5, BGB property law. No blockers. Sources cited." },
      { key:"risk",  icon:"📈", color:C.amber,  name:"Stress-Test Simulator",status:"PASS",     text:"Fair value €2.5M ±3%. Risk score 24/100 (LOW). Stable under downturn scenarios." },
      { key:"tok",   icon:"🪙", color:C.purple, name:"Asset Tokenizer",      status:"PASS",     text:"2,500 tokens @ €1,000. ERC-3643, KYC-gated transfers, governance encoded." },
      { key:"sign",  icon:"🔐", color:C.red,    name:"Consensus Signer",     status:"SEALED",   text:"Consensus verified across all gates. Proof DGP-7F3A-2041 issued. Record sealed." },
      { key:"gov",   icon:"📋", color:C.muted,  name:"Governance & Audit",   status:"ASSEMBLED",text:"All verdicts, proofs and audit trail bound into the Decision Evidence Package. Ready for authorization." },
    ],
    orchestrator:"All eight agents reported; every mandatory gate cleared with no exceptions and the record is cryptographically sealed. I recommend APPROVE, subject to your authorization as Head of Digital Assets.",
  },
  "REQ-2043": {
    name:"Viktor Petrov", flagCode:"BG", asset:"Gold Reserve", value:"€1.20M",
    recommendation:"DECLINE", proof:"—",
    report:[
      { key:"doc", icon:"📄", color:C.cyan,  name:"Doc Auditor",   status:"PASS", text:"Assay certificate authentic, 1,200 troy oz confirmed, custody chain intact. Value €1.2M consistent with spot price." },
      { key:"kyc", icon:"🛡️", color:C.red,   name:"KYC Guardian",  status:"FAIL", text:"⚠️ PEP match confirmed. Subject linked to politically exposed network. Source of funds: unverifiable offshore structures. Risk: CRITICAL." },
      { key:"gov", icon:"📋", color:C.muted, name:"Governance & Audit", status:"HALTED", text:"KYC failure is a hard stop. Pipeline halted — Compliance, Risk and Tokenization did not execute. Halt recorded in audit trail." },
    ],
    orchestrator:"Governance gate triggered: a KYC failure is a hard stop. The pipeline was halted and downstream agents did not execute. I recommend DECLINE, subject to your authorization as Head of Digital Assets.",
  },
};

function Identicon({ seed, size=36, rounded=9 }) {
  let h=5381; for (let i=0;i<seed.length;i++) h=(((h<<5)+h)+seed.charCodeAt(i))|0; h=Math.abs(h);
  const ACC=[C.cyan,C.gold,C.muted], accent=ACC[h%3], pad=6, n=5, cell=(size-pad*2)/n, filled=[];
  for (let r=0;r<n;r++) for (let col=0;col<n;col++){ const m=col<3?col:4-col; if ((h>>(r*3+m))&1) filled.push({r,col}); }
  return (
    <svg width={size} height={size} style={{ flexShrink:0 }}>
      <rect width={size} height={size} rx={rounded} fill={C.navyLight} stroke={`${C.gold}55`}/>
      {filled.map(({r,col})=> <rect key={`${r}-${col}`} x={pad+col*cell} y={pad+r*cell} width={cell-1} height={cell-1} rx={1.5} fill={accent} opacity={0.85}/>)}
    </svg>
  );
}

function Token3D({ state }) {
  const mountRef = useRef(null);
  const stateRef = useRef(state);
  useEffect(()=>{ stateRef.current = state; }, [state]);
  useEffect(()=>{
    const mount = mountRef.current; if (!mount) return;
    const W = mount.clientWidth || 320, H = 210;
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(40, W/H, 0.1, 100); camera.position.set(0,0.5,5);
    const renderer = new THREE.WebGLRenderer({ antialias:true, alpha:true });
    renderer.setSize(W,H); renderer.setPixelRatio(Math.min(window.devicePixelRatio,2));
    mount.appendChild(renderer.domElement);
    const group = new THREE.Group(); scene.add(group);
    const coinGeo = new THREE.CylinderGeometry(1.3,1.3,0.22,6);
    const coinMat = new THREE.MeshStandardMaterial({ color:0x8a93a6, metalness:0.95, roughness:0.28 });
    const coin = new THREE.Mesh(coinGeo, coinMat); coin.rotation.x = Math.PI/2; group.add(coin);
    const emblemGeo = new THREE.CylinderGeometry(0.55,0.55,0.27,6);
    const emblemMat = new THREE.MeshStandardMaterial({ color:0x4fc3f7, emissive:0x0d2c40, metalness:0.7, roughness:0.35 });
    const emblem = new THREE.Mesh(emblemGeo, emblemMat); emblem.rotation.x = Math.PI/2; group.add(emblem);
    const edges = new THREE.LineSegments(new THREE.EdgesGeometry(coinGeo), new THREE.LineBasicMaterial({ color:0xe8a93d, transparent:true, opacity:0.55 }));
    edges.rotation.x = Math.PI/2; group.add(edges);
    const pCount=90, positions=new Float32Array(pCount*3);
    for (let i=0;i<pCount;i++){ const a=Math.random()*Math.PI*2, r=1.9+Math.random()*1.3; positions[i*3]=Math.cos(a)*r; positions[i*3+1]=(Math.random()-0.5)*2.4; positions[i*3+2]=Math.sin(a)*r; }
    const pGeo = new THREE.BufferGeometry(); pGeo.setAttribute("position", new THREE.BufferAttribute(positions,3));
    const pMat = new THREE.PointsMaterial({ color:0xe8a93d, size:0.035, transparent:true, opacity:0.5 });
    const particles = new THREE.Points(pGeo, pMat); scene.add(particles);
    scene.add(new THREE.AmbientLight(0x223349,1.1));
    const key = new THREE.DirectionalLight(0xffffff,1.1); key.position.set(3,4,5); scene.add(key);
    const goldLight = new THREE.PointLight(0xe8a93d,1.5,12); goldLight.position.set(-3,1.5,3); scene.add(goldLight);
    const cyanLight = new THREE.PointLight(0x4fc3f7,1.0,12); cyanLight.position.set(3,-2,2); scene.add(cyanLight);
    let mx=0,my=0;
    const onMove = e=>{ const r=mount.getBoundingClientRect(); mx=((e.clientX-r.left)/r.width-0.5)*2; my=((e.clientY-r.top)/r.height-0.5)*2; };
    mount.addEventListener("mousemove", onMove);
    const cTarget=new THREE.Color(), eTarget=new THREE.Color(); let t=0, raf;
    const animate = ()=>{
      raf = requestAnimationFrame(animate); t+=0.016; const s=stateRef.current;
      const speed = s==="halted"?0.0015 : s==="done"?0.014 : 0.006;
      group.rotation.y += speed; group.position.y = Math.sin(t*1.2)*0.12;
      group.rotation.x = THREE.MathUtils.lerp(group.rotation.x, my*0.28, 0.05);
      group.rotation.z = THREE.MathUtils.lerp(group.rotation.z, -mx*0.18, 0.05);
      particles.rotation.y -= 0.0016;
      cTarget.set(s==="done"?0xe8a93d : s==="halted"?0x6b2433 : 0x8a93a6); coinMat.color.lerp(cTarget,0.045);
      eTarget.set(s==="done"?0x6e4408 : s==="halted"?0x33060f : 0x0e1c2a); coinMat.emissive.lerp(eTarget,0.045);
      pMat.opacity = THREE.MathUtils.lerp(pMat.opacity, s==="done"?0.95 : s==="halted"?0.15 : 0.5, 0.04);
      goldLight.intensity = THREE.MathUtils.lerp(goldLight.intensity, s==="done"?2.4:1.5, 0.04);
      renderer.render(scene, camera);
    };
    animate();
    const onResize = ()=>{ const w=mount.clientWidth||W; camera.aspect=w/H; camera.updateProjectionMatrix(); renderer.setSize(w,H); };
    window.addEventListener("resize", onResize);
    return ()=>{ cancelAnimationFrame(raf); mount.removeEventListener("mousemove", onMove); window.removeEventListener("resize", onResize); if (renderer.domElement.parentNode===mount) mount.removeChild(renderer.domElement); renderer.dispose(); coinGeo.dispose(); emblemGeo.dispose(); pGeo.dispose(); coinMat.dispose(); emblemMat.dispose(); pMat.dispose(); };
  }, []);
  return <div ref={mountRef} style={{ width:"100%", height:210, cursor:"grab" }} />;
}

export default function Review() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { user, logout } = useSession();
  const caseId = CASES[id] ? id : "REQ-2041";
  const data = CASES[caseId];
  const tokenState = data.recommendation === "APPROVE" ? "done" : "halted";

  const [decision, setDecision] = useState(null);
  const [notes, setNotes] = useState("");
  const [reason, setReason] = useState("");
  const [forward, setForward] = useState("");
  const [signed, setSigned] = useState(false);

  const canSign = decision && reason.trim().length > 0;

  const openReport = () => window.open(evidencePdfUrl(caseId), "_blank");
  const exportPdf  = () => window.open(evidencePdfUrl(caseId, true), "_blank");

  return (
    <div style={{ minHeight:"100vh", background:C.bg, fontFamily:"'Montserrat', system-ui, sans-serif", color:C.white }}>
      <style>{`@keyframes sigReveal{from{opacity:0;transform:translateX(-10px)}to{opacity:1;transform:translateX(0)}}`}</style>
      {/* top bar */}
      <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", gap:12, padding:"12px 22px", borderBottom:`1px solid ${C.border}`, background:C.navy, position:"sticky", top:0, zIndex:50 }}>
        <div style={{ display:"flex", alignItems:"center", gap:11, minWidth:0 }}>
          <Identicon seed={caseId} size={36}/>
          <div style={{ minWidth:0 }}>
            <div style={{ display:"flex", alignItems:"center", gap:8 }}>
              <span style={{ fontSize:14, fontWeight:800, whiteSpace:"nowrap" }}>{data.name}</span>
              <span style={{ fontSize:9, color:C.muted, fontFamily:"monospace" }}>{caseId}</span>
            </div>
            <div style={{ fontSize:8, color:C.green, marginTop:1 }}>● Biometric ID verified</div>
          </div>
          {data.recommendation==="APPROVE" && <span style={{ fontSize:8, fontWeight:700, color:C.green, background:`${C.green}1A`, border:`1px solid ${C.green}44`, padding:"2px 9px", borderRadius:20, whiteSpace:"nowrap", marginLeft:4 }}>✓ SEALED · {data.proof}</span>}
          {data.recommendation==="DECLINE" && <span style={{ fontSize:8, fontWeight:700, color:C.red, background:`${C.red}1A`, border:`1px solid ${C.red}44`, padding:"2px 9px", borderRadius:20, whiteSpace:"nowrap", marginLeft:4 }}>● PIPELINE HALTED</span>}
        </div>
        <div style={{ display:"flex", alignItems:"center", gap:8, flexShrink:0 }}>
          <button onClick={() => navigate("/dashboard")} style={{ background:`${C.cyan}14`, border:`1px solid ${C.cyan}55`, borderRadius:7, padding:"6px 12px", color:C.cyan, fontSize:10, fontWeight:700, fontFamily:"inherit", cursor:"pointer", whiteSpace:"nowrap" }}>Next Case →</button>
          <button onClick={()=>{ logout(); navigate("/login"); }} style={{ background:"none", border:`1px solid ${C.border}`, borderRadius:7, padding:"6px 12px", color:C.muted, fontSize:10, fontFamily:"inherit", cursor:"pointer", whiteSpace:"nowrap" }}>Log Out</button>
        </div>
      </div>

      <div style={{ display:"flex", maxWidth:1180, margin:"0 auto" }}>
        {/* LEFT */}
        <div style={{ flex:1.15, padding:20, borderRight:`1px solid ${C.border}`, minWidth:0 }}>
          <div style={{ position:"relative", height:210, background:`radial-gradient(circle at 50% 50%, ${C.navyLight}55, ${C.bg})`, border:`1px solid ${C.border}`, borderRadius:14, overflow:"hidden" }}>
            <Token3D state={tokenState}/>
          </div>

          <div style={{ marginTop:16, background:`linear-gradient(160deg, ${C.navy}, ${C.bg})`, border:`1px solid ${C.border}`, borderRadius:14, padding:15 }}>
            <div style={{ display:"flex", alignItems:"center", justifyContent:"space-between", marginBottom:13 }}>
              <span style={{ fontSize:12, fontWeight:700 }}>Compliance Report</span>
              <span style={{ fontSize:9, color:data.recommendation==="APPROVE"?C.green:C.red, background:`${data.recommendation==="APPROVE"?C.green:C.red}1A`, border:`1px solid ${data.recommendation==="APPROVE"?C.green:C.red}44`, padding:"3px 9px", borderRadius:20, fontWeight:700 }}>{data.recommendation==="APPROVE"?"ALL GATES CLEARED":"GATE FAILURE — HALTED"}</span>
            </div>
            <div style={{ display:"flex", flexDirection:"column", gap:9 }}>
              {data.report.map(r=>{
                const sc = r.status==="FAIL"||r.status==="HALTED" ? C.red : C.green;
                return (
                  <div key={r.key} style={{ background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:9, padding:"10px 12px" }}>
                    <div style={{ display:"flex", alignItems:"center", gap:8, marginBottom:4 }}>
                      <span style={{ fontSize:12 }}>{r.icon}</span>
                      <span style={{ fontSize:11, fontWeight:700, color:r.color }}>{r.name}</span>
                      <span style={{ marginLeft:"auto", fontSize:8.5, color:sc, fontWeight:700 }}>{r.status}</span>
                    </div>
                    <div style={{ fontSize:10, color:"#B8C9DD", lineHeight:1.5 }}>{r.text}</div>
                  </div>
                );
              })}
            </div>
            <div style={{ marginTop:13, padding:"12px 14px", background:`linear-gradient(135deg, ${C.gold}14, ${C.green}10)`, border:`1px solid ${C.gold}44`, borderRadius:10 }}>
              <div style={{ display:"flex", alignItems:"center", gap:7, marginBottom:6 }}><span style={{ fontSize:12 }}>🎯</span><span style={{ fontSize:9, color:C.gold, letterSpacing:"1px", fontWeight:700 }}>ORCHESTRATOR — RECOMMENDATION</span></div>
              <div style={{ fontSize:10.5, color:C.white, lineHeight:1.55 }}>{data.orchestrator}</div>
            </div>
            <button onClick={openReport} style={{ width:"100%", marginTop:11, padding:11, background:`${C.gold}14`, border:`1px solid ${C.gold}55`, borderRadius:9, color:C.gold, fontSize:11, fontWeight:700, fontFamily:"inherit", cursor:"pointer" }}>📄 Open Full Report (PDF)</button>
          </div>
        </div>

        {/* RIGHT */}
        <div style={{ flex:1, padding:20, minWidth:0, display:"flex", flexDirection:"column", gap:14 }}>
          {signed ? (
            <div style={{ background:`${C.green}12`, border:`1px solid ${C.green}55`, borderRadius:12, padding:"16px", textAlign:"center" }}>
              <div style={{ fontSize:14, fontWeight:800, color:decision==="approve"?C.green:C.red }}>{decision==="approve"?"✓ APPROVED & SEALED":"✕ DECLINED & SEALED"}</div>
              <div style={{ fontSize:9.5, color:C.muted, marginTop:5 }}>Authorized by {user?.name??"Nevine AKF"} · cryptographically-bound authorization record</div>
            </div>
          ) : (
          <div>
            <div style={{ fontSize:10, color:C.muted, marginBottom:7, fontWeight:600, letterSpacing:"0.5px" }}>YOUR DECISION</div>
            <div style={{ display:"flex", gap:10 }}>
              <button onClick={()=>setDecision("approve")} style={{ flex:1, padding:14, background:decision==="approve"?`${C.green}26`:`${C.green}10`, border:`${decision==="approve"?1.5:1}px solid ${decision==="approve"?C.green:C.border}`, borderRadius:10, color:C.green, fontSize:13, fontWeight:800, fontFamily:"inherit", cursor:"pointer" }}>✓ APPROVE</button>
              <button onClick={()=>setDecision("decline")} style={{ flex:1, padding:14, background:decision==="decline"?`${C.red}26`:"none", border:`${decision==="decline"?1.5:1}px solid ${decision==="decline"?C.red:C.border}`, borderRadius:10, color:C.red, fontSize:13, fontWeight:800, fontFamily:"inherit", cursor:"pointer" }}>✕ DECLINE</button>
            </div>
          </div>
          )}

          <div>
            <div style={{ fontSize:10, color:C.muted, marginBottom:6, fontWeight:600 }}>NOTES</div>
            <textarea value={notes} onChange={e=>setNotes(e.target.value)} disabled={signed} placeholder="Add internal notes…" style={{ width:"100%", boxSizing:"border-box", background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:9, padding:10, fontSize:11, color:C.white, fontFamily:"inherit", minHeight:42, resize:"vertical", outline:"none" }}/>
          </div>

          <div>
            <div style={{ fontSize:10, color:C.muted, marginBottom:6, fontWeight:600 }}>REASON FOR DECISION <span style={{ color:C.red }}>*</span></div>
            <textarea value={reason} onChange={e=>setReason(e.target.value)} disabled={signed} placeholder="Required — why are you approving or declining?" style={{ width:"100%", boxSizing:"border-box", background:C.navyLight, border:`1px solid ${reason.trim()?C.border:C.red+"55"}`, borderRadius:9, padding:10, fontSize:11, color:C.white, fontFamily:"inherit", minHeight:50, resize:"vertical", outline:"none" }}/>
          </div>

          <div>
            <div style={{ fontSize:10, color:C.muted, marginBottom:6, fontWeight:600 }}>AUTHORIZED SIGNATURE</div>
            <div style={{ background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:9, padding:12 }}>
              <div style={{ display:"flex", alignItems:"center", gap:9, marginBottom:10 }}>
                <div style={{ width:30, height:30, borderRadius:"50%", background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, display:"flex", alignItems:"center", justifyContent:"center", color:C.navy, fontWeight:800, fontSize:10, flexShrink:0 }}>{(user?.name??"Nevine AKF").split(" ").map(w=>w[0]).join("")}</div>
                <div style={{ flex:1, minWidth:0 }}><div style={{ fontSize:11.5, fontWeight:700 }}>{user?.name??"Nevine AKF"}</div><div style={{ fontSize:8.5, color:C.muted }}>{user?.role??"Head of Digital Assets"}</div></div>
              </div>
              <div style={{ background:C.bg, border:`1px dashed ${signed?C.green:C.gold}55`, borderRadius:8, padding:"10px 13px", display:"flex", alignItems:"center", justifyContent:"space-between", gap:10 }}>
                {signed
                  ? <span style={{ fontSize:18, fontStyle:"italic", color:C.green, fontFamily:"Georgia, serif", animation:"sigReveal 0.6s ease-out both" }}>{user?.name??"Nevine AKF"}</span>
                  : <span style={{ fontSize:13, fontStyle:"italic", color:C.muted, fontFamily:"Georgia, serif", opacity:0.45 }}>Signature appears on sign</span>}
                {signed
                  ? <span style={{ fontSize:9, color:C.green, fontWeight:700, whiteSpace:"nowrap", flexShrink:0 }}>● SIGNED & SEALED</span>
                  : <button onClick={()=>canSign&&setSigned(true)} disabled={!canSign} style={{ background:canSign?`${C.gold}14`:C.navy, border:`1px solid ${canSign?C.gold+"55":C.border}`, borderRadius:7, padding:"6px 12px", color:canSign?C.gold:C.muted, fontSize:10, fontWeight:700, fontFamily:"inherit", cursor:canSign?"pointer":"not-allowed", whiteSpace:"nowrap", flexShrink:0 }}>Sign & Seal</button>}
              </div>
              {!canSign && !signed && <div style={{ fontSize:8.5, color:C.muted, marginTop:6 }}>Select a decision and enter a reason to enable signing.</div>}
            </div>
          </div>

          <div>
            <div style={{ fontSize:10, color:C.muted, marginBottom:6, fontWeight:600 }}>FORWARD TO</div>
            <select value={forward} onChange={e=>setForward(e.target.value)} style={{ width:"100%", boxSizing:"border-box", background:C.navyLight, border:`1px solid ${C.border}`, borderRadius:9, padding:"10px 13px", fontSize:11, color:forward?C.white:C.muted, fontFamily:"inherit", outline:"none", cursor:"pointer" }}>
              <option value="">Select recipient…</option>
              <option value="ceo">Chief Executive Officer</option>
              <option value="legal">Legal Division</option>
              <option value="risk">Risk &amp; Compliance Division</option>
              <option value="ops">Operations Division</option>
              <option value="other">Other Division</option>
            </select>
          </div>

          <button onClick={exportPdf} style={{ padding:13, background:`linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, border:"none", borderRadius:10, color:C.navy, fontSize:12, fontWeight:800, fontFamily:"inherit", cursor:"pointer", marginTop:2 }}>📄 Export PDF</button>
        </div>
      </div>
    </div>
  );
}
