import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";

const C = {
  bg: "#050D1A", navy: "#0A1A2F", navyLight: "#0F2340", border: "#1A3A5C",
  gold: "#E8A93D", goldLight: "#F0C75E", cyan: "#4FC3F7", white: "#F0F4FF", muted: "#6B8CAE",
};

export default function Login() {
  const navigate = useNavigate();
  const { login } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [focused, setFocused] = useState(null);
  const [mounted, setMounted] = useState(false);
  const [unlocking, setUnlocking] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  function handleSignIn() {
    if (unlocking) return;
    setUnlocking(true);
    setTimeout(() => {
      login("Nevine AKF", "Head of Digital Assets");
      navigate("/dashboard");
    }, 700);
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: `radial-gradient(ellipse at 50% 0%, ${C.navyLight} 0%, ${C.bg} 70%)`,
      display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
      fontFamily: "'Montserrat', system-ui, sans-serif", position: "relative", overflow: "hidden", padding: 20,
    }}>
      <div style={{
        position: "absolute", inset: 0,
        backgroundImage: `linear-gradient(${C.border}22 1px, transparent 1px), linear-gradient(90deg, ${C.border}22 1px, transparent 1px)`,
        backgroundSize: "48px 48px",
        maskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
        WebkitMaskImage: "radial-gradient(ellipse at center, black 30%, transparent 75%)",
      }} />

      {[...Array(20)].map((_, i) => (
        <div key={i} style={{
          position: "absolute", width: 3, height: 3, borderRadius: "50%",
          background: i % 3 === 0 ? C.gold : C.cyan, opacity: 0.4,
          left: `${(i * 53) % 100}%`, top: `${(i * 37) % 100}%`,
          boxShadow: `0 0 8px ${i % 3 === 0 ? C.gold : C.cyan}`,
          animation: `float${i % 3} ${6 + (i % 4)}s ease-in-out infinite`,
          animationDelay: `${i * 0.3}s`,
        }} />
      ))}

      <div style={{
        position: "relative", width: "100%", maxWidth: 420,
        background: `linear-gradient(160deg, ${C.navy}F0, ${C.bg}F0)`,
        border: `1px solid ${C.border}`, borderRadius: 20, padding: "48px 40px",
        boxShadow: `0 30px 80px rgba(0,0,0,0.6), 0 0 60px ${C.gold}0A, inset 0 1px 0 ${C.gold}22`,
        backdropFilter: "blur(20px)",
        opacity: mounted ? 1 : 0, transform: mounted ? "translateY(0)" : "translateY(20px)",
        transition: "all 0.8s cubic-bezier(0.22, 1, 0.36, 1)",
      }}>
        <div style={{
          position: "absolute", top: 0, left: "50%", transform: "translateX(-50%)",
          width: 80, height: 2, background: `linear-gradient(90deg, transparent, ${C.gold}, transparent)`,
        }} />

        <div style={{ display: "flex", flexDirection: "column", alignItems: "center", marginBottom: 36 }}>
          <div style={{ width: 64, height: 64, display: "flex", alignItems: "center", justifyContent: "center", marginBottom: 20 }}>
            <svg width="64" height="64" viewBox="0 0 64 64" fill="none">
              <polygon points="32,4 56,18 56,46 32,60 8,46 8,18" fill="none" stroke={C.gold} strokeWidth="1.5" opacity="0.9" />
              <g style={{ transformOrigin: "32px 28px", transform: unlocking ? "translateY(-9px) rotate(-12deg)" : "none", transition: "transform 0.7s cubic-bezier(.34,1.56,.64,1)" }}>
                <path d="M25 30 V25 A7 7 0 0 1 39 25 V30" fill="none" stroke={C.cyan} strokeWidth="2.2" strokeLinecap="round" opacity="0.85" />
              </g>
              <rect x="23" y="30" width="18" height="15" rx="3" fill={C.navy} stroke={C.gold} strokeWidth="1.5" />
              <g style={{ transformOrigin: "32px 36px", transform: unlocking ? "rotate(90deg)" : "rotate(0deg)", transition: "transform 0.7s cubic-bezier(.34,1.56,.64,1)" }}>
                <circle cx="32" cy="36" r="2.6" fill={C.gold} />
                <rect x="30.7" y="36" width="2.6" height="6" rx="1.3" fill={C.gold} />
              </g>
            </svg>
          </div>
          <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, letterSpacing: 6, color: C.white, textTransform: "uppercase" }}>
            BRIGHT<span style={{ color: C.gold }}>UITY</span>
          </h1>
          <p style={{ margin: "10px 0 0", fontSize: 10, letterSpacing: 1.5, color: C.muted, textAlign: "center", textTransform: "uppercase" }}>
            RWA Tokenization Intelligence
          </p>
        </div>

        <div style={{ textAlign: "center", marginBottom: 28 }}>
          <h2 style={{ margin: 0, fontSize: 16, fontWeight: 600, color: C.white }}>Welcome back</h2>
          <p style={{ margin: "6px 0 0", fontSize: 12, color: C.muted }}>Digital Assets &amp; Tokenization Division</p>
        </div>

        <div style={{ marginBottom: 18 }}>
          <label style={{ fontSize: 10, letterSpacing: 1, color: C.muted, textTransform: "uppercase", display: "block", marginBottom: 8 }}>Username</label>
          <input value={username} onChange={e => setUsername(e.target.value)} onFocus={() => setFocused("user")} onBlur={() => setFocused(null)} placeholder="head.digitalassets"
            style={{ width: "100%", boxSizing: "border-box", padding: "13px 16px", background: C.bg, border: `1px solid ${focused === "user" ? C.gold : C.border}`, borderRadius: 10, color: C.white, fontSize: 14, outline: "none", transition: "all 0.3s", boxShadow: focused === "user" ? `0 0 0 3px ${C.gold}1A` : "none", fontFamily: "inherit" }} />
        </div>

        <div style={{ marginBottom: 28 }}>
          <label style={{ fontSize: 10, letterSpacing: 1, color: C.muted, textTransform: "uppercase", display: "block", marginBottom: 8 }}>Password</label>
          <input type="password" value={password} onChange={e => setPassword(e.target.value)} onFocus={() => setFocused("pass")} onBlur={() => setFocused(null)} placeholder="••••••••••"
            style={{ width: "100%", boxSizing: "border-box", padding: "13px 16px", background: C.bg, border: `1px solid ${focused === "pass" ? C.gold : C.border}`, borderRadius: 10, color: C.white, fontSize: 14, outline: "none", transition: "all 0.3s", boxShadow: focused === "pass" ? `0 0 0 3px ${C.gold}1A` : "none", fontFamily: "inherit" }} />
        </div>

        <button onClick={handleSignIn} disabled={unlocking}
          style={{ width: "100%", padding: "14px", background: `linear-gradient(135deg, ${C.goldLight}, ${C.gold})`, border: "none", borderRadius: 10, color: C.navy, fontSize: 14, fontWeight: 800, letterSpacing: 1, textTransform: "uppercase", cursor: unlocking ? "default" : "pointer", transition: "all 0.3s", boxShadow: `0 8px 24px ${C.gold}33`, fontFamily: "inherit" }}
          onMouseEnter={e => { if (!unlocking) { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = `0 12px 32px ${C.gold}55`; } }}
          onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = `0 8px 24px ${C.gold}33`; }}>
          {unlocking ? "Unlocking…" : "Sign In"}
        </button>

        <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 6, marginTop: 24 }}>
          <span style={{ fontSize: 11 }}>🔒</span>
          <span style={{ fontSize: 10, color: C.muted, letterSpacing: 0.5 }}>Secured · On-Premise Deployment · Isolated Environment</span>
        </div>
      </div>

      <p style={{ margin: "30px 0 0", fontSize: 12, letterSpacing: 2, color: C.gold, fontWeight: 600, textAlign: "center", position: "relative", zIndex: 1 }}>
        Tokenize the Real World. Unlock Infinite Liquidity.
      </p>

      <style>{`
        @keyframes float0 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(10px,-15px)} }
        @keyframes float1 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(-12px,-10px)} }
        @keyframes float2 { 0%,100%{transform:translate(0,0)} 50%{transform:translate(8px,12px)} }
        input::placeholder { color: ${C.muted}88; }
      `}</style>
    </div>
  );
}
