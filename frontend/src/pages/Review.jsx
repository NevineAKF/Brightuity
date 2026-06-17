/**
 * Review.jsx — L4 Human Authorization layer.
 *
 * Three-panel layout:
 *   LEFT   — Band coordination chat (agent @mentions, audit proof of coordination)
 *   CENTER — 3D hexagonal token visual (CSS hex; Three.js replaces it in next step)
 *   RIGHT  — Six verdict cards with latency + Export PDF + Forward dropdown
 *   BOTTOM — Human decision zone (Approve/Reject + rationale + e-signature)
 *
 * Data is hardcoded for REQ-2041 (Marcus Weber, approve) and REQ-2043
 * (Viktor Petrov, PEP rejection). Real backend wiring is the next step.
 */
import React, { useState, useEffect, useRef } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSession } from '../context/SessionContext.jsx'
import { evidencePdfUrl } from '../api/client.js'

/* ── Design tokens ──────────────────────────────────────────────────── */
const NAVY       = '#0A1A2F'
const NAVY_MID   = '#0F2340'
const NAVY_PANEL = '#0C1D35'
const BORDER     = '#1E3A5F'
const GOLD       = '#E8A93D'
const GOLD_DRK   = '#C4891A'
const TEXT       = '#E2E8F0'
const TEXT_DIM   = '#8BA3C1'
const GREEN      = '#1B7F4B'
const GREEN_LT   = '#34D399'
const RED        = '#B3261E'
const RED_LT     = '#F87171'

/* ── Hardcoded case data ─────────────────────────────────────────────── */
const CASE_DATA = {
  'REQ-2041': {
    name: 'Marcus Weber', flag: '🇩🇪', nationality: 'German',
    asset: 'Commercial Real Estate', detail: 'Grade A office, Frankfurt CBD — 2,400 m²',
    value: '€2,500,000', tokens: '2,500,000 × ERC-3643 T-REX @ €1.00',
    recommendation: 'APPROVE', rec_color: GREEN_LT, rec_bg: `${GREEN}20`,
    photo: 'https://randomuser.me/api/portraits/men/42.jpg',
    verdicts: [
      { agent: 'Doc Auditor',           role: 'Document Verification',       verdict: 'pass',   summary: 'All documents verified. Deed, valuation, and registry filings complete. No issues found.',  latency: 3180, model: 'Qwen 3.6' },
      { agent: 'KYC Guardian',          role: 'KYC & AML Compliance',        verdict: 'pass',   summary: 'No sanctions match. No PEP flags. Source of funds verified: documented business income.',    latency: 8420, model: 'Claude Opus 4.8' },
      { agent: 'Dynamic Compliance',    role: 'Regulatory Analysis',         verdict: 'pass',   summary: 'Germany/MiCA Article 68 compliant. ERC-3643 permissible. No cross-border restrictions.',     latency: 12140, model: 'Gemini 3.1 Pro' },
      { agent: 'Stress-Test Simulator', role: 'Market & Liquidity Risk',     verdict: 'pass',   summary: 'Risk score 28/100 (Low). Rate shock -8.2%: value maintained. Liquidity stress: adequate.',   latency: 6730, model: 'DeepSeek-V4-Pro' },
      { agent: 'Asset Tokenizer',       role: 'Token Structuring',           verdict: 'pass',   summary: 'ERC-3643 T-REX: 2.5M tokens @ €1.00. 12-month lock-up. Quarterly redemption windows.',      latency: 7190, model: 'Kimi-K2.6' },
      { agent: 'Consensus Signer',      role: 'Cryptographic Seal',          verdict: 'sealed', summary: 'All governance gates cleared. ECDSA-P256 canonical signature committed to audit record.',    latency: 38, model: 'Deterministic (no LLM)' },
    ],
    chat: [
      { agent: 'Orchestrator',        msg: '@Doc Auditor begin document review for case REQ-2041.' },
      { agent: 'Doc Auditor',         msg: '@Orchestrator PASS — all documents verified. Encrypted ref: EVP-DOC-3F2A' },
      { agent: 'Orchestrator',        msg: '@KYC Guardian proceed with identity and AML screening.' },
      { agent: 'KYC Guardian',        msg: '@Orchestrator PASS — no sanctions, no PEP. Source of funds verified. Ref: EVP-KYC-7B4C' },
      { agent: 'Orchestrator',        msg: '@Dynamic_Compliance map case to applicable jurisdiction and regulations.' },
      { agent: 'Dynamic Compliance',  msg: '@Orchestrator PASS — Germany/MiCA Art. 68 compliant. ERC-3643 permitted. Ref: EVP-COMP-2D8E' },
      { agent: 'Orchestrator',        msg: '@Stress_Test run fair-value and scenario analysis.' },
      { agent: 'Stress-Test Simulator', msg: '@Orchestrator PASS — risk score 28/100. All stress scenarios within tolerance. Ref: EVP-RISK-5A1F' },
      { agent: 'Orchestrator',        msg: '@Asset_Tokenizer design token structure.' },
      { agent: 'Asset Tokenizer',     msg: '@Orchestrator PASS — ERC-3643 T-REX: 2.5M tokens @ €1.00. 12mo lock-up. Ref: EVP-TOK-3C9D' },
      { agent: 'Consensus Signer',    msg: '@Orchestrator SEALED — all gates cleared. ECDSA: 3045...A9B2. Package: EVP-REQ-2041-20260613' },
      { agent: 'Orchestrator',        msg: '@Head_of_Digital_Assets pipeline complete. Recommendation: APPROVE. Package sealed and ready for your review.' },
    ],
  },
  'REQ-2043': {
    name: 'Viktor Petrov', flag: '🇧🇬', nationality: 'Bulgarian',
    asset: 'Gold Reserve', detail: '1,200 troy oz verified bullion',
    value: '€1,200,000', tokens: '—',
    recommendation: 'HALT', rec_color: RED_LT, rec_bg: `${RED}20`,
    photo: 'https://randomuser.me/api/portraits/men/77.jpg',
    verdicts: [
      { agent: 'Doc Auditor',           role: 'Document Verification',       verdict: 'pass',   summary: 'Custody certificates and provenance documents verified. Gold assay certificates valid.',      latency: 2940, model: 'Qwen 3.6' },
      { agent: 'KYC Guardian',          role: 'KYC & AML Compliance',        verdict: 'halt',   summary: 'PEP STATUS CONFIRMED — Viktor Petrov matches EU sanctions list entry. Hard governance halt.', latency: 9810, model: 'Claude Opus 4.8' },
      { agent: 'Dynamic Compliance',    role: 'Regulatory Analysis',         verdict: 'skipped', summary: 'Skipped — KYC hard halt prevents further pipeline execution.',                                latency: 0,    model: '—' },
      { agent: 'Stress-Test Simulator', role: 'Market & Liquidity Risk',     verdict: 'skipped', summary: 'Skipped — KYC hard halt prevents further pipeline execution.',                                latency: 0,    model: '—' },
      { agent: 'Asset Tokenizer',       role: 'Token Structuring',           verdict: 'skipped', summary: 'Skipped — KYC hard halt prevents further pipeline execution.',                                latency: 0,    model: '—' },
      { agent: 'Consensus Signer',      role: 'Cryptographic Seal',          verdict: 'blocked', summary: 'Gate blocked — KYC mandatory gate not cleared. No token may be issued. Audit record sealed.', latency: 35,   model: 'Deterministic (no LLM)' },
    ],
    chat: [
      { agent: 'Orchestrator',     msg: '@Doc Auditor begin document review for case REQ-2043.' },
      { agent: 'Doc Auditor',      msg: '@Orchestrator PASS — documents verified. Ref: EVP-DOC-2C8F' },
      { agent: 'Orchestrator',     msg: '@KYC Guardian proceed with identity and AML screening.' },
      { agent: 'KYC Guardian',     msg: '@Orchestrator HALT — PEP match confirmed. Viktor Petrov appears on EU Regulation 2022/328 consolidated sanctions list. Hard halt invoked. No further agents may proceed. Ref: EVP-KYC-HALT-REQ-2043' },
      { agent: 'Orchestrator',     msg: '@Head_of_Digital_Assets GOVERNANCE HALT — mandatory KYC gate failed. Pipeline stopped. Case REQ-2043 requires compliance investigation before any review can proceed.' },
      { agent: 'Consensus Signer', msg: '@Orchestrator GATE BLOCKED — KYC gate not cleared. Token issuance BLOCKED. Audit record of halt committed with ECDSA signature.' },
    ],
  },
}

/* ── Agent color mapping ─────────────────────────────────────────────── */
const AGENT_COLORS = {
  'Orchestrator':          GOLD,
  'Doc Auditor':           '#60A5FA',
  'KYC Guardian':          '#A78BFA',
  'Dynamic Compliance':    '#34D399',
  'Stress-Test Simulator': '#F97316',
  'Asset Tokenizer':       '#22D3EE',
  'Consensus Signer':      '#FDE68A',
}

/* ── Verdict chip ────────────────────────────────────────────────────── */
function VerdictChip({ verdict }) {
  const cfg = {
    pass:    { label: 'PASS',    bg: `${GREEN}22`,   color: GREEN_LT, border: `${GREEN}55` },
    halt:    { label: 'HALT',    bg: `${RED}22`,     color: RED_LT,   border: `${RED}55` },
    blocked: { label: 'BLOCKED', bg: `${RED}18`,     color: RED_LT,   border: `${RED}44` },
    sealed:  { label: 'SEALED',  bg: `${GOLD}18`,    color: GOLD,     border: `${GOLD}44` },
    skipped: { label: 'SKIPPED', bg: `${BORDER}`,    color: TEXT_DIM, border: BORDER },
  }
  const c = cfg[verdict] ?? cfg.skipped
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: '0.1em',
      padding: '3px 8px', borderRadius: 4,
      background: c.bg, color: c.color, border: `1px solid ${c.border}`,
    }}>{c.label}</span>
  )
}

/* ── Verdict card ────────────────────────────────────────────────────── */
function VerdictCard({ v, index }) {
  const [expanded, setExpanded] = useState(false)
  const isActive = v.verdict !== 'skipped'
  const borderColor = v.verdict === 'pass' ? `${GREEN}50`
    : v.verdict === 'halt'    ? `${RED}60`
    : v.verdict === 'blocked' ? `${RED}50`
    : v.verdict === 'sealed'  ? `${GOLD}50`
    : BORDER

  return (
    <div
      style={{
        background: NAVY_PANEL, border: `1px solid ${borderColor}`, borderRadius: 10,
        padding: '0.875rem', cursor: isActive ? 'pointer' : 'default',
        transition: 'all 0.2s', animation: `slideUp 0.4s ease ${index * 0.06}s both`,
        opacity: isActive ? 1 : 0.45,
      }}
      onClick={() => isActive && setExpanded(e => !e)}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: expanded ? 8 : 0 }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: TEXT, marginBottom: 2 }}>{v.agent}</div>
          <div style={{ fontSize: 9.5, color: TEXT_DIM }}>{v.role}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 4 }}>
          <VerdictChip verdict={v.verdict} />
          {v.latency > 0 && (
            <span style={{ fontSize: 9, color: TEXT_DIM, fontFamily: "'JetBrains Mono',monospace" }}>
              {v.latency >= 1000 ? (v.latency / 1000).toFixed(1) + 's' : v.latency + 'ms'}
            </span>
          )}
        </div>
      </div>
      {expanded && (
        <div style={{ marginTop: 8, borderTop: `1px solid ${BORDER}`, paddingTop: 8, animation: 'fadeIn 0.2s ease' }}>
          <div style={{ fontSize: 11.5, color: TEXT_DIM, lineHeight: 1.55, marginBottom: 6 }}>{v.summary}</div>
          <div style={{ fontSize: 9.5, color: TEXT_DIM }}>Model: <span style={{ color: TEXT }}>{v.model}</span></div>
        </div>
      )}
    </div>
  )
}

/* ── CSS Hex token — placeholder for Three.js 3D token ─────────────── */
function HexToken({ verdict }) {
  const color = verdict === 'APPROVE' ? '#C9A227'
    : verdict === 'HALT' ? '#8B1E1E'
    : '#9AA3B2'
  const glow = verdict === 'APPROVE' ? `0 0 40px ${GOLD}60, 0 0 80px ${GOLD}20`
    : verdict === 'HALT' ? `0 0 40px ${RED}60`
    : `0 0 20px #9AA3B222`
  const label = verdict === 'APPROVE' ? 'APPROVED'
    : verdict === 'HALT' ? 'HALTED'
    : 'PROCESSING'

  return (
    <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '1.5rem', padding: '1.5rem 0' }}>
      {/* Hex shape */}
      <div style={{ position: 'relative' }}>
        <svg viewBox="0 0 200 230" width="160" height="184" style={{ filter: `drop-shadow(${glow.split(',')[0]})`, animation: verdict === 'APPROVE' ? 'goldGlow 2.5s ease-in-out infinite' : 'none' }}>
          <defs>
            <linearGradient id="hexGrad" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stopColor={color} stopOpacity="0.9" />
              <stop offset="60%" stopColor={color} stopOpacity="0.6" />
              <stop offset="100%" stopColor={color} stopOpacity="0.3" />
            </linearGradient>
            <linearGradient id="hexShine" x1="0%" y1="0%" x2="50%" y2="100%">
              <stop offset="0%" stopColor="white" stopOpacity="0.15" />
              <stop offset="100%" stopColor="white" stopOpacity="0" />
            </linearGradient>
          </defs>
          {/* Outer hex */}
          <polygon points="100,10 182,55 182,175 100,220 18,175 18,55"
            fill="url(#hexGrad)" stroke={color} strokeWidth="1.5" opacity="0.9" />
          {/* Shine layer */}
          <polygon points="100,10 182,55 182,175 100,220 18,175 18,55"
            fill="url(#hexShine)" />
          {/* Inner hex */}
          <polygon points="100,40 160,75 160,155 100,190 40,155 40,75"
            fill="none" stroke={color} strokeWidth="1" opacity="0.4" />
          {/* B letter */}
          <text x="100" y="128" textAnchor="middle" fill="white"
            fontSize="52" fontWeight="800" fontFamily="Montserrat,sans-serif" opacity="0.95">B</text>
          {/* Facet lines */}
          <line x1="100" y1="10" x2="100" y2="40" stroke="white" strokeWidth="0.8" opacity="0.2" />
          <line x1="182" y1="55" x2="160" y2="75" stroke="white" strokeWidth="0.8" opacity="0.2" />
          <line x1="182" y1="175" x2="160" y2="155" stroke="white" strokeWidth="0.8" opacity="0.2" />
        </svg>
        {/* Spinning ring */}
        <div style={{
          position: 'absolute', inset: -16,
          borderRadius: '50%',
          border: `1px solid ${color}30`,
          animation: 'spin 8s linear infinite',
          pointerEvents: 'none',
        }} />
      </div>

      {/* Status */}
      <div style={{ textAlign: 'center' }}>
        <div style={{
          fontSize: 11, fontWeight: 700, letterSpacing: '0.18em',
          color: color, marginBottom: 6,
        }}>{label}</div>
        <div style={{ fontSize: 10, color: TEXT_DIM }}>
          {verdict === 'APPROVE' ? 'Token structure ready · All gates cleared'
            : verdict === 'HALT'    ? 'Hard governance halt · KYC gate blocked'
            : 'Three.js 3D token loads here in next step'}
        </div>
      </div>

      {/* Placeholder note */}
      <div style={{
        fontSize: 9.5, color: TEXT_DIM, opacity: 0.4,
        border: `1px dashed ${BORDER}`, borderRadius: 6, padding: '4px 10px',
      }}>
        CSS placeholder — Three.js 3D replaces this
      </div>
    </div>
  )
}

/* ── Decision zone ───────────────────────────────────────────────────── */
function DecisionZone({ caseId, data }) {
  const [decision, setDecision]   = useState('')
  const [rationale, setRationale] = useState('')
  const [signature, setSignature] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [errMsg, setErrMsg]       = useState('')
  const isHalt = data.recommendation === 'HALT'

  function handleSubmit() {
    if (!decision) { setErrMsg('Select a decision.'); return }
    if (!rationale.trim()) { setErrMsg('Rationale is required.'); return }
    if (!signature.trim()) { setErrMsg('E-signature is required.'); return }
    setErrMsg('')
    setSubmitted(true)
    // Real POST /cases/:id/authorize comes in the data-wiring step
  }

  if (submitted) {
    return (
      <div style={{
        padding: '1.5rem', borderRadius: 12, textAlign: 'center',
        background: decision === 'approve' ? `${GREEN}18` : `${RED}18`,
        border: `1px solid ${decision === 'approve' ? `${GREEN}55` : `${RED}55`}`,
        animation: 'fadeIn 0.4s ease',
      }}>
        <div style={{ fontSize: 20, marginBottom: 8 }}>{decision === 'approve' ? '✅' : '🚫'}</div>
        <div style={{ fontSize: 14, fontWeight: 700, color: TEXT, marginBottom: 4 }}>
          Decision recorded: {decision === 'approve' ? 'APPROVED' : 'REJECTED'}
        </div>
        <div style={{ fontSize: 11.5, color: TEXT_DIM }}>
          Signed by Nevine AKF · Layer 2 ECDSA seal will be applied on submission to server.
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Recommendation banner */}
      <div style={{
        padding: '0.875rem 1.25rem', borderRadius: 10,
        background: data.rec_bg, border: `1px solid ${data.rec_color}44`,
        display: 'flex', alignItems: 'center', gap: '0.875rem',
      }}>
        <div style={{ fontSize: 18 }}>{data.recommendation === 'APPROVE' ? '🤖' : '⚠️'}</div>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: data.rec_color, letterSpacing: '0.1em' }}>
            SYSTEM RECOMMENDATION: {data.recommendation}
          </div>
          <div style={{ fontSize: 11, color: TEXT_DIM, marginTop: 2 }}>
            {data.recommendation === 'APPROVE'
              ? 'All 5 compliance gates cleared. Token structure ready. Final decision is yours.'
              : 'Hard governance halt — KYC mandatory gate blocked. Human override not permitted.'}
          </div>
        </div>
      </div>

      {!isHalt && (
        <>
          {/* Decision buttons */}
          <div style={{ display: 'flex', gap: '0.75rem' }}>
            {['approve', 'reject'].map(d => (
              <button key={d}
                onClick={() => setDecision(d)}
                style={{
                  flex: 1, padding: '0.75rem',
                  borderRadius: 8, border: `2px solid ${decision === d
                    ? (d === 'approve' ? GREEN : RED)
                    : BORDER}`,
                  background: decision === d
                    ? (d === 'approve' ? `${GREEN}25` : `${RED}25`)
                    : NAVY_PANEL,
                  color: decision === d
                    ? (d === 'approve' ? GREEN_LT : RED_LT)
                    : TEXT_DIM,
                  fontSize: 12, fontWeight: 700, letterSpacing: '0.12em',
                  fontFamily: 'inherit', cursor: 'pointer', transition: 'all 0.2s',
                }}
              >
                {d === 'approve' ? '✓ APPROVE' : '✗ REJECT'}
              </button>
            ))}
          </div>

          {/* Rationale */}
          <div>
            <label style={{ fontSize: 10.5, color: TEXT_DIM, letterSpacing: '0.1em', display: 'block', marginBottom: 5 }}>
              RATIONALE (required)
            </label>
            <textarea
              value={rationale}
              onChange={e => setRationale(e.target.value)}
              placeholder="Document your decision rationale for the audit record…"
              rows={3}
              style={{
                width: '100%', background: NAVY, border: `1px solid ${BORDER}`, borderRadius: 8,
                padding: '0.75rem', color: TEXT, fontSize: 12.5, fontFamily: 'inherit',
                resize: 'vertical', outline: 'none',
              }}
              onFocus={e  => { e.target.style.borderColor = GOLD }}
              onBlur={e   => { e.target.style.borderColor = BORDER }}
            />
          </div>

          {/* E-signature */}
          <div>
            <label style={{ fontSize: 10.5, color: TEXT_DIM, letterSpacing: '0.1em', display: 'block', marginBottom: 5 }}>
              E-SIGNATURE — type your full name to sign
            </label>
            <input
              type="text"
              value={signature}
              onChange={e => setSignature(e.target.value)}
              placeholder="Nevine AKF"
              style={{
                width: '100%', background: NAVY, border: `1px solid ${BORDER}`, borderRadius: 8,
                padding: '0.75rem', color: TEXT, fontSize: 13, fontFamily: "'JetBrains Mono',monospace",
                outline: 'none',
              }}
              onFocus={e  => { e.target.style.borderColor = GOLD }}
              onBlur={e   => { e.target.style.borderColor = BORDER }}
            />
          </div>

          {errMsg && <div style={{ fontSize: 11, color: RED_LT }}>{errMsg}</div>}

          <button
            onClick={handleSubmit}
            style={{
              background: `linear-gradient(135deg, ${GOLD} 0%, ${GOLD_DRK} 100%)`,
              border: 'none', borderRadius: 8, padding: '0.875rem',
              color: NAVY, fontSize: 12, fontWeight: 700, letterSpacing: '0.15em',
              fontFamily: 'inherit', cursor: 'pointer',
              boxShadow: `0 4px 20px ${GOLD}35`,
            }}
          >
            SUBMIT DECISION & APPLY L2 SEAL
          </button>
        </>
      )}
    </div>
  )
}

/* ── Review page ─────────────────────────────────────────────────────── */
export default function Review() {
  const { id }           = useParams()
  const navigate         = useNavigate()
  const { user, logout } = useSession()
  const chatRef          = useRef(null)
  const [chatVisible, setChatVisible] = useState([])

  const data = CASE_DATA[id] ?? CASE_DATA['REQ-2041']

  // Animate chat messages in sequence
  useEffect(() => {
    setChatVisible([])
    data.chat.forEach((m, i) => {
      setTimeout(() => {
        setChatVisible(prev => [...prev, m])
        if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight
      }, i * 400)
    })
  }, [id])

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div style={{ minHeight: '100vh', background: NAVY, fontFamily: "'Montserrat', sans-serif", display: 'flex', flexDirection: 'column' }}>
      {/* Navbar */}
      <nav style={{
        height: 58, background: NAVY_MID, borderBottom: `1px solid ${BORDER}`,
        display: 'flex', alignItems: 'center', paddingInline: '1.5rem', gap: '0.875rem',
        position: 'sticky', top: 0, zIndex: 50, flexShrink: 0,
      }}>
        <svg width="24" height="24" viewBox="0 0 56 56" fill="none">
          <polygon points="28,2 52,15 52,41 28,54 4,41 4,15" fill={GOLD} opacity="0.15" stroke={GOLD} strokeWidth="1.5" />
          <text x="28" y="33" textAnchor="middle" fill={GOLD} fontSize="16" fontWeight="800" fontFamily="Montserrat,sans-serif">B</text>
        </svg>
        <span style={{ fontSize: 13, fontWeight: 800, letterSpacing: '0.18em', color: TEXT }}>BRIGHTUITY</span>
        <div style={{ width: 1, height: 20, background: BORDER }} />
        <span style={{ fontSize: 10.5, color: TEXT_DIM }}>Decision Review</span>
        <span style={{ fontSize: 10.5, color: GOLD, fontFamily: "'JetBrains Mono',monospace" }}>#{id}</span>
        <div style={{ flex: 1 }} />
        {/* PDF export link */}
        <a
          href={evidencePdfUrl(id, { download: true })}
          target="_blank" rel="noreferrer"
          style={{
            background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6,
            padding: '4px 12px', color: TEXT_DIM, fontSize: 10, textDecoration: 'none',
            letterSpacing: '0.08em', transition: 'all 0.2s',
          }}
          onMouseEnter={e => { e.currentTarget.style.borderColor = GOLD; e.currentTarget.style.color = GOLD }}
          onMouseLeave={e => { e.currentTarget.style.borderColor = BORDER; e.currentTarget.style.color = TEXT_DIM }}
        >↓ EXPORT PDF</a>
        <button onClick={() => navigate('/dashboard')}
          style={{ background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6, padding: '4px 10px', color: TEXT_DIM, fontSize: 10, fontFamily: 'inherit', cursor: 'pointer' }}>
          ← QUEUE
        </button>
        {user && (
          <button onClick={handleLogout}
            style={{ background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6, padding: '4px 10px', color: TEXT_DIM, fontSize: 10, fontFamily: 'inherit', cursor: 'pointer' }}>
            SIGN OUT
          </button>
        )}
      </nav>

      {/* Three-panel layout */}
      <div style={{ flex: 1, display: 'flex', overflow: 'hidden', minHeight: 0 }}>

        {/* LEFT — Band chat */}
        <div style={{
          width: 300, flexShrink: 0, background: NAVY_PANEL,
          borderRight: `1px solid ${BORDER}`, display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: '1rem 1rem 0.75rem', borderBottom: `1px solid ${BORDER}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 2 }}>
              <div style={{ width: 7, height: 7, borderRadius: '50%', background: GREEN_LT, animation: 'pulse 1.5s infinite' }} />
              <span style={{ fontSize: 10, color: TEXT_DIM, letterSpacing: '0.1em' }}>BAND COORDINATION · LIVE</span>
            </div>
            <div style={{ fontSize: 9.5, color: TEXT_DIM, opacity: 0.6 }}>
              Proving cross-framework agent coordination
            </div>
          </div>
          <div ref={chatRef} style={{ flex: 1, overflowY: 'auto', padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.875rem' }}>
            {chatVisible.map((m, i) => (
              <div key={i} style={{ animation: 'chatEntry 0.3s ease' }}>
                <div style={{ fontSize: 9.5, fontWeight: 700, color: AGENT_COLORS[m.agent] ?? TEXT_DIM, marginBottom: 3, letterSpacing: '0.04em' }}>
                  @{m.agent}
                </div>
                <div style={{ fontSize: 11.5, color: TEXT, lineHeight: 1.5, background: NAVY_MID, borderRadius: 8, padding: '0.5rem 0.75rem', borderLeft: `2px solid ${AGENT_COLORS[m.agent] ?? BORDER}` }}>
                  {m.msg}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* CENTER — Token visual + case summary */}
        <div style={{
          flex: 1, display: 'flex', flexDirection: 'column', background: NAVY,
          borderRight: `1px solid ${BORDER}`, overflowY: 'auto',
        }}>
          {/* Case header */}
          <div style={{ padding: '1.25rem 1.5rem', borderBottom: `1px solid ${BORDER}` }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '1rem' }}>
              <img src={data.photo} width={44} height={44}
                style={{ borderRadius: '50%', border: `2px solid ${BORDER}` }}
                onError={e => { e.target.style.display = 'none' }} />
              <div>
                <div style={{ fontSize: 16, fontWeight: 700, color: TEXT }}>{data.name}</div>
                <div style={{ fontSize: 11, color: TEXT_DIM }}>{data.flag} {data.nationality} · {data.asset}</div>
              </div>
              <div style={{ marginLeft: 'auto', textAlign: 'right' }}>
                <div style={{ fontSize: 18, fontWeight: 800, color: GOLD }}>{data.value}</div>
                <div style={{ fontSize: 9.5, color: TEXT_DIM }}>Asset Value</div>
              </div>
            </div>
          </div>

          {/* Hex token */}
          <HexToken verdict={data.recommendation} />

          {/* Token structure */}
          {data.tokens !== '—' && (
            <div style={{ padding: '0 1.5rem 1.5rem' }}>
              <div style={{
                background: NAVY_MID, border: `1px solid ${BORDER}`, borderRadius: 10, padding: '0.875rem',
              }}>
                <div style={{ fontSize: 10, color: TEXT_DIM, letterSpacing: '0.1em', marginBottom: 6 }}>TOKEN STRUCTURE</div>
                <div style={{ fontSize: 12.5, color: TEXT, fontFamily: "'JetBrains Mono',monospace" }}>{data.tokens}</div>
              </div>
            </div>
          )}
        </div>

        {/* RIGHT — Verdict cards */}
        <div style={{
          width: 340, flexShrink: 0, background: NAVY_PANEL,
          overflowY: 'auto', display: 'flex', flexDirection: 'column',
        }}>
          <div style={{ padding: '1rem 1rem 0.75rem', borderBottom: `1px solid ${BORDER}`, flexShrink: 0 }}>
            <div style={{ fontSize: 10.5, fontWeight: 700, color: TEXT, letterSpacing: '0.1em', marginBottom: 2 }}>AGENT VERDICTS</div>
            <div style={{ fontSize: 9.5, color: TEXT_DIM }}>Click a card to expand · {data.verdicts.filter(v => v.verdict !== 'skipped').length}/6 active</div>
          </div>
          <div style={{ flex: 1, padding: '1rem', display: 'flex', flexDirection: 'column', gap: '0.625rem', overflowY: 'auto' }}>
            {data.verdicts.map((v, i) => <VerdictCard key={v.agent} v={v} index={i} />)}
          </div>

          {/* Forward dropdown */}
          <div style={{ padding: '0.875rem', borderTop: `1px solid ${BORDER}`, flexShrink: 0 }}>
            <div style={{ fontSize: 10, color: TEXT_DIM, letterSpacing: '0.08em', marginBottom: 6 }}>FORWARD PACKAGE TO</div>
            <select style={{
              width: '100%', background: NAVY, border: `1px solid ${BORDER}`, borderRadius: 7,
              padding: '0.6rem 0.75rem', color: TEXT_DIM, fontSize: 11.5, fontFamily: 'inherit',
              outline: 'none',
            }}>
              <option value="">Select department…</option>
              <option>Legal & Compliance</option>
              <option>Senior Management</option>
              <option>Risk Committee</option>
              <option>Regulatory Affairs</option>
            </select>
          </div>
        </div>
      </div>

      {/* BOTTOM — Decision zone */}
      <div style={{
        background: NAVY_MID, borderTop: `1px solid ${BORDER}`,
        padding: '1.25rem 1.5rem', flexShrink: 0,
      }}>
        <div style={{ maxWidth: 900, margin: '0 auto' }}>
          <div style={{ fontSize: 11, color: TEXT_DIM, letterSpacing: '0.12em', marginBottom: '0.875rem' }}>
            HUMAN AUTHORIZATION — LAYER 2
          </div>
          <DecisionZone caseId={id} data={data} />
        </div>
      </div>
    </div>
  )
}
