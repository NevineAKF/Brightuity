import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../context/SessionContext.jsx'

/* ── Design tokens ──────────────────────────────────────────────────── */
const NAVY      = '#0A1A2F'
const NAVY_MID  = '#0F2340'
const NAVY_LITE = '#1A3A5C'
const BORDER    = '#1E3A5F'
const GOLD      = '#E8A93D'
const GOLD_DRK  = '#C4891A'
const TEXT      = '#E2E8F0'
const TEXT_DIM  = '#8BA3C1'
const ERR       = '#E05252'

/* ── Hex logo ───────────────────────────────────────────────────────── */
function HexLogo({ size = 52 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 56 56" fill="none">
      <polygon points="28,2 52,15 52,41 28,54 4,41 4,15"
        fill={GOLD} opacity="0.12" stroke={GOLD} strokeWidth="1.5" />
      <polygon points="28,9 47,20 47,36 28,47 9,36 9,20"
        fill={GOLD} opacity="0.07" />
      <text x="28" y="33" textAnchor="middle"
        fill={GOLD} fontSize="16" fontWeight="800"
        fontFamily="Montserrat,sans-serif">B</text>
    </svg>
  )
}

/* ── Vault lock SVG — shackle lifts when unlocking ─────────────────── */
function VaultLock({ unlocking }) {
  return (
    <div style={{ width: 80, height: 88, margin: '0 auto 1.75rem', position: 'relative' }}>
      <svg viewBox="0 0 80 88" fill="none" style={{ width: '100%', height: '100%', overflow: 'visible' }}>
        {/* Glow backdrop when unlocked */}
        {unlocking && (
          <ellipse cx="40" cy="64" rx="30" ry="12"
            fill={GOLD} opacity="0.10"
            style={{ animation: 'pulse 1s ease-in-out infinite' }} />
        )}
        {/* Lock body */}
        <rect x="8" y="36" width="64" height="46" rx="8"
          fill={NAVY_MID} stroke={unlocking ? GOLD : BORDER} strokeWidth="2"
          style={{ transition: 'stroke 0.4s' }} />
        {/* Keyhole circle */}
        <circle cx="40" cy="56" r="9" fill={NAVY} stroke={GOLD} strokeWidth="1.5" />
        {/* Keyhole slot */}
        <rect x="37" y="57" width="6" height="13" rx="3"
          fill={NAVY} stroke={GOLD} strokeWidth="1.5" />
        {/* Shackle — animates up-and-left on unlock */}
        <path d="M18 38 V22 A22 22 0 0 1 62 22 V38"
          stroke={unlocking ? GOLD : TEXT_DIM} strokeWidth="6"
          strokeLinecap="round" fill="none"
          style={{
            transition: 'transform 0.55s cubic-bezier(.34,1.56,.64,1), stroke 0.3s',
            transform: unlocking ? 'translate(-4px, -18px) rotate(-8deg)' : 'none',
            transformOrigin: '18px 38px',
          }} />
      </svg>
    </div>
  )
}

/* ── Login page ─────────────────────────────────────────────────────── */
export default function Login() {
  const navigate      = useNavigate()
  const { login }     = useSession()
  const [pw, setPw]   = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (!pw.trim()) { setErr('Access code required.'); return }
    setErr('')
    setBusy(true)
    // Demo: any non-empty password unlocks after the animation
    setTimeout(() => {
      login('Nevine AKF', 'Head of Digital Assets')
      navigate('/dashboard')
    }, 950)
  }

  const inputBase = {
    width: '100%', background: NAVY, border: `1px solid ${BORDER}`,
    borderRadius: 8, padding: '0.75rem 1rem', color: TEXT,
    fontSize: 14, fontFamily: 'inherit', outline: 'none',
    transition: 'border-color 0.2s',
  }

  return (
    <div style={{
      minHeight: '100vh',
      background: `radial-gradient(ellipse at 55% 15%, #0D2B4A 0%, ${NAVY} 70%)`,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: "'Montserrat', sans-serif", position: 'relative', overflow: 'hidden',
    }}>
      {/* Subtle grid */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: `linear-gradient(${BORDER}28 1px,transparent 1px),linear-gradient(90deg,${BORDER}28 1px,transparent 1px)`,
        backgroundSize: '64px 64px',
      }} />

      {/* Corner accent */}
      <div style={{
        position: 'absolute', top: 0, left: 0,
        width: 260, height: 260,
        background: `radial-gradient(circle at top left, ${GOLD}0A 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* Card */}
      <div className="anim-slide-up" style={{
        position: 'relative', zIndex: 1,
        background: NAVY_MID, border: `1px solid ${BORDER}`,
        borderRadius: 18, padding: '2.75rem 2.5rem',
        width: '100%', maxWidth: 420,
        boxShadow: `0 32px 80px rgba(0,0,0,0.55), 0 0 0 1px ${GOLD}12`,
      }}>
        {/* Top gold accent line */}
        <div style={{
          position: 'absolute', top: 0, left: '12%', right: '12%', height: 2,
          background: `linear-gradient(90deg,transparent,${GOLD},transparent)`, borderRadius: 2,
        }} />

        {/* Logo + wordmark */}
        <div style={{ textAlign: 'center', marginBottom: '1.25rem' }}>
          <HexLogo size={52} />
          <div style={{ marginTop: '0.6rem' }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: '0.22em', color: TEXT }}>BRIGHTUITY</div>
            <div style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: '0.18em', color: GOLD, marginTop: 5 }}>
              RWA TOKENIZATION INTELLIGENCE
            </div>
          </div>
        </div>

        <VaultLock unlocking={busy} />

        {/* Subtitle */}
        <div style={{ textAlign: 'center', marginBottom: '1.75rem' }}>
          <div style={{ fontSize: 11, letterSpacing: '0.12em', color: TEXT_DIM }}>SECURE ZONE 1 ACCESS</div>
          <div style={{ fontSize: 10, color: TEXT_DIM, opacity: 0.6, marginTop: 3 }}>
            Digital Assets &amp; Tokenization Division
          </div>
        </div>

        <form onSubmit={handleSubmit}>
          {/* Identity — read-only */}
          <div style={{ marginBottom: '0.9rem' }}>
            <label style={{ fontSize: 10.5, letterSpacing: '0.12em', color: TEXT_DIM, display: 'block', marginBottom: 6 }}>
              IDENTITY
            </label>
            <div style={{
              ...inputBase, display: 'flex', alignItems: 'center', gap: 10,
              cursor: 'default', userSelect: 'none',
            }}>
              <span style={{ color: GOLD, fontSize: 11 }}>◈</span>
              <span style={{ fontSize: 13 }}>Nevine AKF</span>
              <span style={{ color: TEXT_DIM, fontSize: 11 }}>— Head of Digital Assets</span>
            </div>
          </div>

          {/* Password */}
          <div style={{ marginBottom: '1.5rem' }}>
            <label style={{ fontSize: 10.5, letterSpacing: '0.12em', color: TEXT_DIM, display: 'block', marginBottom: 6 }}>
              ACCESS CODE
            </label>
            <input
              type="password"
              value={pw}
              onChange={e => setPw(e.target.value)}
              placeholder="••••••••••"
              disabled={busy}
              style={{ ...inputBase, borderColor: err ? ERR : BORDER, fontSize: 18, letterSpacing: '0.1em' }}
              onFocus={e  => { e.target.style.borderColor = GOLD }}
              onBlur={e   => { e.target.style.borderColor = err ? ERR : BORDER }}
            />
            {err && <div style={{ fontSize: 11, color: ERR, marginTop: 5 }}>{err}</div>}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={busy}
            style={{
              width: '100%',
              background: busy ? GOLD_DRK : `linear-gradient(135deg, ${GOLD} 0%, ${GOLD_DRK} 100%)`,
              border: 'none', borderRadius: 8, padding: '0.875rem',
              color: NAVY, fontSize: 12, fontWeight: 700, letterSpacing: '0.18em',
              fontFamily: 'inherit', cursor: busy ? 'default' : 'pointer',
              boxShadow: `0 4px 24px ${GOLD}38`, transition: 'transform 0.15s, opacity 0.2s',
            }}
            onMouseEnter={e => { if (!busy) e.currentTarget.style.transform = 'translateY(-1px)' }}
            onMouseLeave={e => { e.currentTarget.style.transform = 'none' }}
          >
            {busy ? 'UNLOCKING VAULT…' : 'SIGN IN'}
          </button>
        </form>

        {/* Footer */}
        <div style={{ textAlign: 'center', marginTop: '1.5rem', fontSize: 9.5, color: TEXT_DIM, opacity: 0.4, letterSpacing: '0.1em' }}>
          ZONE 1 · END-TO-END ENCRYPTED · ISO 27001 ALIGNED
        </div>
      </div>
    </div>
  )
}
