import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useSession } from "../context/SessionContext.jsx";

/* ── Palette (exact spec values) ────────────────────────────────────── */
const C = {
  bg:        "#050D1A",
  navy:      "#0A1A2F",
  navyLight: "#0F2340",
  border:    "#1A3A5C",
  gold:      "#E8A93D",
  goldLight: "#F0C75E",
  cyan:      "#4FC3F7",
  green:     "#4CAF50",
  amber:     "#FF9800",
  white:     "#F0F4FF",
  muted:     "#6B8CAE",
};

/* ── Case data (existing values preserved exactly) ───────────────────── */
const REQUESTS = [
  { id: "REQ-2041", name: "Marcus Weber",   flag: "🇩🇪", nationality: "German",
    asset: "Commercial Real Estate",    detail: "Grade A office, Frankfurt CBD",
    value: 2_500_000, docId: "EVP-DOC-3F2A9C4E",
    priority: "High",   submitted: "Today, 09:14",   status: "pending" },
  { id: "REQ-2042", name: "Sofia Andreou",  flag: "🇬🇷", nationality: "Greek",
    asset: "Residential Property",      detail: "Luxury apartment, Athens Riviera",
    value: 850_000,   docId: "EVP-DOC-7B1D5E8A",
    priority: "Low",    submitted: "Today, 08:52",   status: "pending" },
  { id: "REQ-2043", name: "Viktor Petrov",  flag: "🇧🇬", nationality: "Bulgarian",
    asset: "Gold Reserve",              detail: "1,200 troy oz verified bullion",
    value: 1_200_000, docId: "EVP-DOC-2C8F1A3D",
    priority: "High",   submitted: "Today, 10:31",   status: "pending" },
  { id: "REQ-2044", name: "Isabella Rossi", flag: "🇮🇹", nationality: "Italian",
    asset: "Commercial Real Estate",    detail: "Mixed-use complex, Milan",
    value: 4_200_000, docId: "EVP-DOC-9A4C7E2B",
    priority: "High",   submitted: "Yesterday, 17:20", status: "pending" },
  { id: "REQ-2045", name: "Liam O'Brien",   flag: "🇮🇪", nationality: "Irish",
    asset: "Government Bond Portfolio", detail: "EU sovereign bonds, AAA-rated",
    value: 5_750_000, docId: "EVP-DOC-4D3B6F1C",
    priority: "Medium", submitted: "Yesterday, 14:05", status: "pending" },
  { id: "REQ-2046", name: "Amélie Dupont",  flag: "🇫🇷", nationality: "French",
    asset: "Fine Art Collection",       detail: "12 provenance-verified works",
    value: 3_100_000, docId: "EVP-DOC-6E9A2C5D",
    priority: "Medium", submitted: "Yesterday, 11:48", status: "pending" },
];

const DONE  = 2;
const TOTAL = REQUESTS.length; // 6

/* ── Helpers ─────────────────────────────────────────────────────────── */
function fmtEur(v) {
  return "€" + (v >= 1_000_000
    ? (v / 1_000_000).toFixed(2) + "M"
    : (v / 1_000).toFixed(0) + "K");
}

const PRIORITY_CFG = {
  High:   { color: C.amber, bg: "#FF980018", border: "#FF980055", barColor: C.amber },
  Medium: { color: C.cyan,  bg: "#4FC3F718", border: "#4FC3F755", barColor: C.cyan  },
  Low:    { color: C.muted, bg: "#6B8CAE18", border: "#6B8CAE55", barColor: C.muted },
};

/* ── CHANGE 1: Identicon — deterministic geometric SVG, no network images ─ */
function Identicon({ seed, size = 48 }) {
  // djb2 hash — same seed always produces the same pattern
  let h = 5381;
  for (let i = 0; i < seed.length; i++) {
    h = (((h << 5) + h) + seed.charCodeAt(i)) | 0;
  }
  h = Math.abs(h);

  const ACCENTS = [C.cyan, C.gold, C.muted];
  const accent  = ACCENTS[h % 3];
  const pad     = 6;
  const n       = 5;
  const cell    = (size - pad * 2) / n;

  // 5×5 grid mirrored left-right (col 3 = col 1, col 4 = col 0)
  const filled = [];
  for (let row = 0; row < n; row++) {
    for (let col = 0; col < n; col++) {
      const mirrorCol = col < 3 ? col : 4 - col;
      if ((h >> (row * 3 + mirrorCol)) & 1) filled.push({ row, col });
    }
  }

  return (
    <div style={{ position: "relative", flexShrink: 0, width: size, height: size }}>
      <svg width={size} height={size}>
        <rect width={size} height={size} rx={12} fill={C.navyLight} stroke={`${C.cyan}44`} strokeWidth="1" />
        {filled.map(({ row, col }) => (
          <rect
            key={`${row}-${col}`}
            x={pad + col * cell + 0.5}
            y={pad + row * cell + 0.5}
            width={cell - 1}
            height={cell - 1}
            rx={2}
            fill={accent}
            opacity={0.82}
          />
        ))}
      </svg>
      {/* Verified tick badge */}
      <div style={{
        position: "absolute", bottom: -2, right: -2,
        width: 15, height: 15, borderRadius: "50%",
        background: C.green, border: `2px solid ${C.bg}`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 7, color: "white", fontWeight: 900,
      }}>✓</div>
    </div>
  );
}

/* ── CHANGE 5: Case card ─────────────────────────────────────────────── */
function CaseCard({ c, onReview, onProcess }) {
  const [hov, setHov] = useState(false);
  const p = PRIORITY_CFG[c.priority] ?? PRIORITY_CFG.Low;

  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: `linear-gradient(135deg, ${C.navy}, ${C.bg})`,
        borderTop:    `1px solid ${C.border}`,
        borderRight:  `1px solid ${C.border}`,
        borderBottom: `1px solid ${C.border}`,
        borderLeft:   `4px solid ${p.barColor}`,
        borderRadius: 16,
        display: "flex", flexDirection: "column",
        transition: "all 0.2s",
        transform:  hov ? "translateY(-3px)" : "none",
        boxShadow:  hov
          ? `0 14px 40px rgba(0,0,0,0.55), 0 0 0 1px ${p.barColor}33`
          : "0 2px 12px rgba(0,0,0,0.35)",
        overflow: "hidden",
      }}
    >
      {/* Header row: identicon + name + priority pill */}
      <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "16px 16px 12px" }}>
        <Identicon seed={c.id} size={48} />
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <span style={{
              fontSize: 14, fontWeight: 700, color: C.white,
              whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis",
              minWidth: 0,
            }}>
              {c.name}
            </span>
            <span style={{ flexShrink: 0 }}>{c.flag}</span>
            <span style={{
              fontSize: 9, fontWeight: 700, letterSpacing: "0.08em",
              padding: "2px 7px", borderRadius: 10, flexShrink: 0,
              marginLeft: "auto",
              background: p.bg, color: p.color, border: `1px solid ${p.border}`,
            }}>{c.priority}</span>
          </div>
          <div style={{ fontSize: 10, color: C.muted, fontFamily: "monospace" }}>
            {c.id} · 🔒 {c.docId.slice(0, 12)}…
          </div>
        </div>
      </div>

      {/* Middle row: asset + value */}
      <div style={{
        display: "flex", justifyContent: "space-between", alignItems: "flex-start",
        padding: "10px 16px", gap: 10,
        borderTop: `1px solid ${C.border}`, borderBottom: `1px solid ${C.border}`,
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 9, color: C.muted, letterSpacing: "0.1em", marginBottom: 3 }}>ASSET TYPE</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: C.white, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.asset}</div>
          <div style={{ fontSize: 10.5, color: C.muted, marginTop: 2, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{c.detail}</div>
        </div>
        <div style={{ textAlign: "right", flexShrink: 0 }}>
          <div style={{ fontSize: 9, color: C.muted, letterSpacing: "0.1em", marginBottom: 3 }}>VALUE</div>
          <div style={{ fontSize: 17, fontWeight: 800, color: C.gold }}>{fmtEur(c.value)}</div>
          <div style={{ fontSize: 9.5, color: C.muted, marginTop: 2 }}>{c.submitted}</div>
        </div>
      </div>

      {/* Two action buttons */}
      <div style={{ display: "flex", gap: 8, padding: "12px 16px" }}>
        {/* Review Case — secondary cyan */}
        <button
          onClick={() => onReview(c)}
          style={{
            flex: 1, padding: "9px 0",
            background: "#1A3A5C33", border: `1px solid ${C.cyan}55`,
            borderRadius: 8, color: C.cyan, fontSize: 11, fontWeight: 700,
            letterSpacing: "0.05em", cursor: "pointer", fontFamily: "inherit",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
            transition: "all 0.2s",
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background  = `${C.cyan}15`;
            e.currentTarget.style.borderColor = C.cyan;
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background  = "#1A3A5C33";
            e.currentTarget.style.borderColor = `${C.cyan}55`;
          }}
        >
          <span style={{ fontSize: 13 }}>👁</span> Review Case
        </button>

        {/* Start Processing — primary gold gradient; navigates to /room/:id */}
        <button
          onClick={() => onProcess(c.id)}
          style={{
            flex: 1, padding: "9px 0",
            background: `linear-gradient(135deg, ${C.goldLight}, ${C.gold})`,
            border: "none", borderRadius: 8,
            color: C.navy, fontSize: 11, fontWeight: 800,
            letterSpacing: "0.05em", cursor: "pointer", fontFamily: "inherit",
            display: "flex", alignItems: "center", justifyContent: "center", gap: 5,
            transition: "all 0.2s",
            boxShadow: `0 4px 12px ${C.gold}33`,
          }}
          onMouseEnter={e => {
            e.currentTarget.style.transform  = "translateY(-1px)";
            e.currentTarget.style.boxShadow  = `0 6px 20px ${C.gold}55`;
          }}
          onMouseLeave={e => {
            e.currentTarget.style.transform  = "none";
            e.currentTarget.style.boxShadow  = `0 4px 12px ${C.gold}33`;
          }}
        >
          <span style={{ fontSize: 11 }}>▶</span> Start Processing
        </button>
      </div>
    </div>
  );
}

/* ── CHANGE 6: Dossier modal ─────────────────────────────────────────── */
function DossierModal({ c, onClose, onProcess }) {
  if (!c) return null;
  const p = PRIORITY_CFG[c.priority] ?? PRIORITY_CFG.Low;

  function InfoRow({ label, value, mono = false, valueStyle = {} }) {
    return (
      <div style={{
        display: "flex", alignItems: "baseline", gap: 8,
        padding: "8px 12px",
        background: C.navyLight, borderRadius: 8, border: `1px solid ${C.border}`,
      }}>
        <span style={{ fontSize: 10, color: C.muted, minWidth: 140, flexShrink: 0 }}>{label}</span>
        <span style={{
          fontSize: 12, color: C.white,
          fontFamily: mono ? "'JetBrains Mono', monospace" : "inherit",
          ...valueStyle,
        }}>{value}</span>
      </div>
    );
  }

  return (
    /* Backdrop — click to close */
    <div
      style={{
        position: "fixed", inset: 0, zIndex: 1000,
        background: "rgba(5,13,26,0.72)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 20, backdropFilter: "blur(5px)",
      }}
      onMouseDown={onClose}
    >
      {/* Card — stop propagation so clicking inside doesn't close */}
      <div
        onMouseDown={e => e.stopPropagation()}
        style={{
          position: "relative", width: "100%", maxWidth: 520,
          background: `linear-gradient(160deg, ${C.navy}, ${C.bg})`,
          border: `1px solid ${C.gold}44`,
          borderRadius: 18, padding: "36px 32px",
          boxShadow: `0 40px 100px rgba(0,0,0,0.7), 0 0 0 1px ${C.gold}18`,
          maxHeight: "90vh", overflowY: "auto",
        }}
      >
        {/* Top gold accent line */}
        <div style={{
          position: "absolute", top: 0, left: "50%", transform: "translateX(-50%)",
          width: 100, height: 2,
          background: `linear-gradient(90deg, transparent, ${C.gold}, transparent)`,
        }} />

        {/* Close ✕ */}
        <button
          onClick={onClose}
          style={{
            position: "absolute", top: 14, right: 14,
            width: 28, height: 28, borderRadius: "50%",
            background: C.navyLight, border: `1px solid ${C.border}`,
            color: C.muted, fontSize: 15, cursor: "pointer",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "inherit",
          }}
        >×</button>

        {/* Modal header */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, marginBottom: 26 }}>
          <Identicon seed={c.id} size={56} />
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 17, fontWeight: 800, color: C.white }}>{c.name}</span>
              <span style={{ fontSize: 16 }}>{c.flag}</span>
            </div>
            <div style={{ fontSize: 11, color: C.muted, marginBottom: 7 }}>
              Client Dossier · {c.id}
            </div>
            <span style={{
              fontSize: 9.5, fontWeight: 700, letterSpacing: "0.1em",
              padding: "3px 9px", borderRadius: 4,
              background: "#4CAF5020", color: C.green, border: `1px solid #4CAF5055`,
            }}>
              ✓ IDENTITY VERIFIED
            </span>
          </div>
        </div>

        {/* CLIENT INFORMATION */}
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.14em", color: C.muted, marginBottom: 10 }}>
            CLIENT INFORMATION
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <InfoRow label="Full Name"       value={c.name} />
            <InfoRow label="Nationality"     value={`${c.flag} ${c.nationality}`} />
            <InfoRow label="Encrypted Doc ID" value={`🔒 ${c.docId}`} mono
              valueStyle={{ color: C.cyan }} />
            <InfoRow label="KYC Status"      value="Cleared — no PEP, no sanctions"
              valueStyle={{ color: C.green }} />
          </div>
        </div>

        {/* ASSET DETAILS */}
        <div style={{ marginBottom: 26 }}>
          <div style={{ fontSize: 9.5, fontWeight: 700, letterSpacing: "0.14em", color: C.muted, marginBottom: 10 }}>
            ASSET DETAILS
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 7 }}>
            <InfoRow label="Asset Type"    value={c.asset}       valueStyle={{ fontWeight: 600 }} />
            <InfoRow label="Description"   value={c.detail} />
            <InfoRow label="Declared Value" value={fmtEur(c.value)}
              valueStyle={{ color: C.gold, fontWeight: 800, fontSize: 15 }} />
            <InfoRow label="Submitted"     value={c.submitted} />
            <InfoRow label="Priority"      value={c.priority}
              valueStyle={{ color: p.color, fontWeight: 700 }} />
          </div>
        </div>

        {/* Footer buttons */}
        <div style={{ display: "flex", gap: 10 }}>
          <button
            onClick={onClose}
            style={{
              flex: 1, padding: "11px",
              background: "none", border: `1px solid ${C.border}`,
              borderRadius: 10, color: C.muted, fontSize: 12, fontWeight: 600,
              cursor: "pointer", fontFamily: "inherit", transition: "all 0.2s",
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = C.muted; e.currentTarget.style.color = C.white; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.color = C.muted; }}
          >
            Close
          </button>
          <button
            onClick={() => onProcess(c.id)}
            style={{
              flex: 2, padding: "11px",
              background: `linear-gradient(135deg, ${C.goldLight}, ${C.gold})`,
              border: "none", borderRadius: 10,
              color: C.navy, fontSize: 12, fontWeight: 800, letterSpacing: "0.06em",
              cursor: "pointer", fontFamily: "inherit",
              boxShadow: `0 4px 16px ${C.gold}33`,
            }}
          >
            ▶ Start Processing
          </button>
        </div>
      </div>
    </div>
  );
}

/* ── CHANGE 4: Bell pill with pending count ──────────────────────────── */
function BellPill() {
  const count = TOTAL - DONE;
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: 6, flexShrink: 0,
      padding: "5px 10px 5px 8px", borderRadius: 20,
      background: `${C.gold}12`, border: `1px solid ${C.gold}33`,
      cursor: "pointer",
    }}>
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none"
        stroke={C.gold} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
        <path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9" />
        <path d="M13.73 21a2 2 0 0 1-3.46 0" />
      </svg>
      <span style={{ fontSize: 10, fontWeight: 700, color: C.gold, whiteSpace: "nowrap" }}>
        {count} pending
      </span>
    </div>
  );
}

/* ── Navbar ───────────────────────────────────────────────────────────── */
function Navbar({ user, onLogout }) {
  return (
    <nav style={{
      height: 62, background: C.navyLight, borderBottom: `1px solid ${C.border}`,
      display: "flex", alignItems: "center", paddingInline: "2rem", gap: "1rem",
      position: "sticky", top: 0, zIndex: 50,
      boxShadow: `0 1px 0 ${C.gold}0A`,
    }}>
      {/* Hex logo */}
      <svg width="26" height="26" viewBox="0 0 64 64" fill="none" style={{ flexShrink: 0 }}>
        <polygon points="32,4 56,18 56,46 32,60 8,46 8,18"
          fill="none" stroke={C.gold} strokeWidth="1.5" opacity="0.9" />
        <text x="32" y="41" textAnchor="middle"
          fill={C.gold} fontSize="22" fontWeight="800" fontFamily="Montserrat,sans-serif">B</text>
      </svg>
      <div>
        <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: "0.2em", color: C.white, lineHeight: 1 }}>
          BRIGHT<span style={{ color: C.gold }}>UITY</span>
        </div>
        <div style={{ fontSize: 8.5, color: C.muted, letterSpacing: "0.12em" }}>
          RWA TOKENIZATION INTELLIGENCE
        </div>
      </div>

      <div style={{ flex: 1 }} />

      {/* Right-side group: bell pill | name+avatar | sign-out — 18px gap between each */}
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        <BellPill />

        {user && (
          <>
            {/* name + avatar in their own sub-group — text can never run into avatar */}
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontSize: 11, fontWeight: 600, color: C.white, whiteSpace: "nowrap" }}>{user.name}</div>
                <div style={{ fontSize: 9, color: C.muted, whiteSpace: "nowrap" }}>{user.role}</div>
              </div>
              <div style={{
                width: 34, height: 34, borderRadius: "50%",
                background: `linear-gradient(135deg, ${C.goldLight}, ${C.gold})`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 12, fontWeight: 800, color: C.navy, flexShrink: 0,
              }}>
                {user.name.split(" ").map(w => w[0]).join("")}
              </div>
            </div>

            <button
              onClick={onLogout}
              style={{
                background: "none", border: `1px solid ${C.border}`, borderRadius: 6,
                padding: "5px 11px", color: C.muted, fontSize: 10,
                fontFamily: "inherit", cursor: "pointer",
                letterSpacing: "0.08em", transition: "all 0.2s",
                whiteSpace: "nowrap", flexShrink: 0,
              }}
              onMouseEnter={e => { e.currentTarget.style.borderColor = C.gold; e.currentTarget.style.color = C.gold; }}
              onMouseLeave={e => { e.currentTarget.style.borderColor = C.border; e.currentTarget.style.color = C.muted; }}
            >
              SIGN OUT
            </button>
          </>
        )}
      </div>
    </nav>
  );
}

/* ── Dashboard page ───────────────────────────────────────────────────── */
export default function Dashboard() {
  const navigate        = useNavigate();
  const { user, logout } = useSession();
  const [search,   setSearch]   = useState("");
  const [selected, setSelected] = useState(null);

  // CHANGE 2: live date string
  const today = new Date().toLocaleDateString("en-US", {
    weekday: "long", year: "numeric", month: "long", day: "numeric",
  });

  // Name from session (fall back to "Nevine")
  const firstName = user?.name?.split(" ")[0] ?? "Nevine";

  function handleLogout() {
    logout();
    navigate("/login");
  }

  // Start Processing navigates to /room/:id — Band room built separately
  function handleProcess(id) {
    navigate(`/room/${id}`);
  }

  // Search filter across name, id, and asset type
  const filtered = search
    ? REQUESTS.filter(r =>
        r.name.toLowerCase().includes(search.toLowerCase()) ||
        r.id.toLowerCase().includes(search.toLowerCase()) ||
        r.asset.toLowerCase().includes(search.toLowerCase())
      )
    : REQUESTS;

  return (
    <div style={{ minHeight: "100vh", background: C.bg, fontFamily: "'Montserrat', system-ui, sans-serif" }}>
      <Navbar user={user} onLogout={handleLogout} />

      <main style={{ maxWidth: 1280, margin: "0 auto", padding: "2rem 2rem 4rem" }}>

        {/* CHANGE 2: Welcome header with live date + CHANGE 3: stat tiles */}
        <div style={{ marginBottom: "2rem" }}>
          {/* Live date */}
          <div style={{ fontSize: 11, color: C.gold, marginBottom: 8, display: "flex", alignItems: "center", gap: 6 }}>
            <span>📅</span>
            <span>{today}</span>
          </div>

          {/* Welcome heading — color explicitly set to #F0F4FF (was invisible before) */}
          <h1 style={{ margin: 0, fontSize: 22, fontWeight: 800, color: C.white, marginBottom: 4 }}>
            Welcome, {firstName}
          </h1>
          <p style={{ margin: 0, fontSize: 12, color: C.muted }}>
            Head of Digital Assets &amp; Tokenization Division
          </p>

          {/* CHANGE 3: daily activity stat tiles */}
          <div style={{ display: "flex", gap: 10, marginTop: 18 }}>
            <div style={{
              padding: "10px 20px", borderRadius: 10,
              background: `${C.gold}12`, border: `1px solid ${C.gold}44`,
              display: "flex", alignItems: "baseline", gap: 8,
            }}>
              <span style={{ fontSize: 18, fontWeight: 800, color: C.gold }}>{DONE}/{TOTAL}</span>
              <span style={{ fontSize: 10.5, color: C.muted }}>done today</span>
            </div>
            <div style={{
              padding: "10px 20px", borderRadius: 10,
              background: `${C.amber}12`, border: `1px solid ${C.amber}44`,
              display: "flex", alignItems: "baseline", gap: 8,
            }}>
              <span style={{ fontSize: 18, fontWeight: 800, color: C.amber }}>{TOTAL - DONE}</span>
              <span style={{ fontSize: 10.5, color: C.muted }}>pending</span>
            </div>
          </div>
        </div>

        {/* Search bar */}
        <div style={{ marginBottom: "1.5rem", maxWidth: 440 }}>
          <div style={{ position: "relative" }}>
            <span style={{
              position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)",
              color: C.muted, fontSize: 14, pointerEvents: "none", lineHeight: 1,
            }}>🔍</span>
            <input
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Search by name, ID, or asset type…"
              style={{
                width: "100%", boxSizing: "border-box",
                paddingLeft: 36, paddingRight: 14, paddingBlock: 11,
                background: C.navyLight, border: `1px solid ${C.border}`,
                borderRadius: 10, color: C.white, fontSize: 13, outline: "none",
                fontFamily: "inherit", transition: "border-color 0.2s",
              }}
              onFocus={e => { e.target.style.borderColor = C.gold; }}
              onBlur={e  => { e.target.style.borderColor = C.border; }}
            />
          </div>
        </div>

        {/* Section label */}
        <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: "1rem" }}>
          <span style={{ fontSize: 10.5, fontWeight: 700, color: C.muted, letterSpacing: "0.14em", whiteSpace: "nowrap" }}>
            PENDING REQUESTS — {filtered.length}
          </span>
          <div style={{ flex: 1, height: 1, background: C.border }} />
        </div>

        {/* CHANGE 5: case cards grid */}
        {filtered.length > 0 ? (
          <div style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))",
            gap: 15,
          }}>
            {filtered.map(c => (
              <CaseCard
                key={c.id}
                c={c}
                onReview={setSelected}      /* Review Case → opens dossier modal */
                onProcess={handleProcess}   /* Start Processing → navigate /room/:id */
              />
            ))}
          </div>
        ) : (
          <div style={{ textAlign: "center", padding: "3rem", color: C.muted, fontSize: 13 }}>
            No requests match your search.
          </div>
        )}
      </main>

      {/* CHANGE 6: dossier modal — rendered in-tree with fixed positioning */}
      {selected && (
        <DossierModal
          c={selected}
          onClose={() => setSelected(null)}
          onProcess={(id) => { setSelected(null); handleProcess(id); }}
        />
      )}
    </div>
  );
}
