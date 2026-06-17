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
const CYAN      = '#4FC3F7'

/* ── Hex logo with embedded padlock — unlocks on Sign In ────────────── */
/*
 * CHANGE 1: replaced the inner "B" text with a padlock motif.
 * Viewbox upgraded to 64×64 to match the task's coordinate system.
 * Shackle group translates up + rotates when unlocking=true.
 * Keyhole group rotates 90° (key-turned effect) when unlocking=true.
 * Both transitions use cubic-bezier(.34,1.56,.64,1) for a springy feel.
 */
function HexLogo({ size = 52, unlocking = false }) {
  return (
    <svg width={size} height={size} viewBox="0 0 64 64" fill="none">
      {/* Outer hexagon — gold outline, faint fill */}
      <polygon
        points="32,4 56,18 56,46 32,60 8,46 8,18"
        fill={GOLD} opacity="0.12" stroke={GOLD} strokeWidth="1.5"
      />
      {/* Inner hexagon — subtler fill layer */}
      <polygon
        points="32,12 52,23 52,41 32,52 12,41 12,23"
        fill={GOLD} opacity="0.07"
      />

      {/* ── Padlock motif ─────────────────────────────────── */}

      {/* Shackle — arcs over the top, lifts + tilts on unlock */}
      <g
        style={{
          transformOrigin: '32px 30px',
          transform: unlocking
            ? 'translateY(-9px) rotate(-12deg)'
            : 'none',
          transition: 'transform 0.7s cubic-bezier(.34,1.56,.64,1)',
        }}
      >
        <path
          d="M25 30 V25 A7 7 0 0 1 39 25 V30"
          stroke={CYAN}
          strokeWidth="2.2"
          strokeLinecap="round"
          fill="none"
          opacity="0.85"
        />
      </g>

      {/* Lock body — gold-outlined rect */}
      <rect
        x="23" y="30" width="18" height="15" rx="3"
        fill={NAVY} stroke={GOLD} strokeWidth="1.5"
      />

      {/* Keyhole — rotates 90° (key-turned) on unlock */}
      <g
        style={{
          transformOrigin: '32px 36px',
          transform: unlocking ? 'rotate(90deg)' : 'rotate(0deg)',
          transition: 'transform 0.7s cubic-bezier(.34,1.56,.64,1)',
        }}
      >
        <circle cx="32" cy="36" r="2.6" fill={GOLD} />
        <rect x="30.7" y="36" width="2.6" height="5" rx="1.3" fill={GOLD} />
      </g>
    </svg>
  )
}

/* ── Login page ─────────────────────────────────────────────────────── */
export default function Login() {
  const navigate         = useNavigate()
  const { login }        = useSession()
  const [pw, setPw]      = useState('')
  const [unlocking, setUnlocking] = useState(false)   /* CHANGE 1 + WIRE */
  const [err, setErr]    = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    if (unlocking) return                              // guard against double-fire
    if (!pw.trim()) { setErr('Access code required.'); return }
    setErr('')
    setUnlocking(true)
    // Demo: any non-empty access code proceeds — no real auth in Phase 1
    setTimeout(() => {
      login('Nevine AKF', 'Head of Digital Assets')
      navigate('/dashboard')
    }, 700)                                            // matches unlock animation
  }

  const inputBase = {
    width: '100%', background: NAVY, border: `1px solid ${BORDER}`,
    borderRadius: 8, padding: '0.75rem 1rem', color: TEXT,
    fontSize: 14, fontFamily: 'inherit', outline: 'none',
    transition: 'border-color 0.2s',
  }

  return (
    /*
     * CHANGE 2: outer container is now flexDirection:'column' so the tagline
     * renders as a normal-flow sibling below the card — never overlaps.
     */
    <div style={{
      minHeight: '100vh',
      background: `radial-gradient(ellipse at 55% 15%, #0D2B4A 0%, ${NAVY} 70%)`,
      display: 'flex', flexDirection: 'column',
      alignItems: 'center', justifyContent: 'center',
      fontFamily: "'Montserrat', sans-serif", position: 'relative', overflow: 'hidden',
    }}>
      {/* Subtle grid — absolutely positioned, behind everything */}
      <div style={{
        position: 'absolute', inset: 0, pointerEvents: 'none',
        backgroundImage: `linear-gradient(${BORDER}28 1px,transparent 1px),linear-gradient(90deg,${BORDER}28 1px,transparent 1px)`,
        backgroundSize: '64px 64px',
      }} />

      {/* Corner accent — absolutely positioned */}
      <div style={{
        position: 'absolute', top: 0, left: 0,
        width: 260, height: 260,
        background: `radial-gradient(circle at top left, ${GOLD}0A 0%, transparent 70%)`,
        pointerEvents: 'none',
      }} />

      {/* Card — normal-flow flex child */}
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

        {/* Logo + wordmark — HexLogo now receives the unlocking state */}
        <div style={{ textAlign: 'center', marginBottom: '1.25rem' }}>
          <HexLogo size={52} unlocking={unlocking} />
          <div style={{ marginTop: '0.6rem' }}>
            <div style={{ fontSize: 21, fontWeight: 800, letterSpacing: '0.22em', color: TEXT }}>BRIGHTUITY</div>
            <div style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: '0.18em', color: GOLD, marginTop: 5 }}>
              RWA TOKENIZATION INTELLIGENCE
            </div>
          </div>
        </div>

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
              disabled={unlocking}
              style={{ ...inputBase, borderColor: err ? ERR : BORDER, fontSize: 18, letterSpacing: '0.1em' }}
              onFocus={e => { e.target.style.borderColor = GOLD }}
              onBlur={e  => { e.target.style.borderColor = err ? ERR : BORDER }}
            />
            {err && <div style={{ fontSize: 11, color: ERR, marginTop: 5 }}>{err}</div>}
          </div>

          {/* Submit */}
          <button
            type="submit"
            disabled={unlocking}
            style={{
              width: '100%',
              background: unlocking ? GOLD_DRK : `linear-gradient(135deg, ${GOLD} 0%, ${GOLD_DRK} 100%)`,
              border: 'none', borderRadius: 8, padding: '0.875rem',
              color: NAVY, fontSize: 12, fontWeight: 700, letterSpacing: '0.18em',
              fontFamily: 'inherit', cursor: unlocking ? 'default' : 'pointer',
              boxShadow: `0 4px 24px ${GOLD}38`, transition: 'transform 0.15s, opacity 0.2s',
            }}
            onMouseEnter={e => { if (!unlocking) e.currentTarget.style.transform = 'translateY(-1px)' }}
            onMouseLeave={e => { e.currentTarget.style.transform = 'none' }}
          >
            {unlocking ? 'UNLOCKING VAULT…' : 'SIGN IN'}
          </button>
        </form>

        {/* Footer — inside card, unchanged */}
        <div style={{ textAlign: 'center', marginTop: '1.5rem', fontSize: 9.5, color: TEXT_DIM, opacity: 0.4, letterSpacing: '0.1em' }}>
          ZONE 1 · END-TO-END ENCRYPTED · ISO 27001 ALIGNED
        </div>
      </div>

      {/*
       * CHANGE 2: tagline is now a normal-flow flex child (marginTop 30px),
       * so it always sits clearly below the card and can never overlap it.
       * Text, gold color, sizing and letter-spacing preserved as specified.
       */}
      <div style={{
        position: 'relative', zIndex: 1,
        marginTop: 30, textAlign: 'center',
        fontSize: 12, fontWeight: 600, letterSpacing: '0.08em',
        color: GOLD, opacity: 0.7,
      }}>
        Tokenize the Real World. Unlock Infinite Liquidity.
      </div>
    </div>
  )
}
