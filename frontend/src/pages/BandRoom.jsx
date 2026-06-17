/**
 * BandRoom.jsx — L3 Band coordination room (placeholder).
 *
 * This page will show live Band @mention streaming as agents coordinate.
 * Real wiring (POST /cases/:id/run + SSE/polling) comes in the next step.
 * For now it provides the routing target for Dashboard card clicks and
 * allows navigation into the Review page.
 */
import React, { useState, useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useSession } from '../context/SessionContext.jsx'

const NAVY      = '#0A1A2F'
const NAVY_MID  = '#0F2340'
const BORDER    = '#1E3A5F'
const GOLD      = '#E8A93D'
const GOLD_DRK  = '#C4891A'
const TEXT      = '#E2E8F0'
const TEXT_DIM  = '#8BA3C1'

/* Simulated pipeline messages — will be replaced by live Band stream */
const MOCK_MSGS = [
  { agent: 'Orchestrator',        msg: 'Case {id} received. Routing to Document Auditor…',         delay: 600  },
  { agent: 'Doc Auditor',         msg: '✓ PASS — Documentation verified. No issues found.',         delay: 1800 },
  { agent: 'Orchestrator',        msg: 'KYC clearance required. Routing to KYC Guardian…',          delay: 2600 },
  { agent: 'KYC Guardian',        msg: '✓ PASS — No sanctions, no PEP flags. Source of funds verified.', delay: 4200 },
  { agent: 'Orchestrator',        msg: 'Compliance mapping required. Routing to Dynamic Compliance…', delay: 5200 },
  { agent: 'Dynamic Compliance',  msg: '✓ PASS — MiCA Article 68 compliant. ERC-3643 permissible.', delay: 7400 },
  { agent: 'Orchestrator',        msg: 'Risk assessment required. Routing to Stress-Test Simulator…', delay: 8400 },
  { agent: 'Stress-Test Simulator', msg: '✓ PASS — Risk score 28/100. All stress scenarios passed.', delay: 10200 },
  { agent: 'Orchestrator',        msg: 'Token structuring required. Routing to Asset Tokenizer…',   delay: 11200 },
  { agent: 'Asset Tokenizer',     msg: '✓ PASS — ERC-3643 T-REX: 2,500,000 tokens @ €1.00. Lock-up 12mo.', delay: 13000 },
  { agent: 'Consensus Signer',    msg: '✓ SEALED — All gates cleared. ECDSA signature committed.', delay: 14400 },
  { agent: 'Orchestrator',        msg: 'Pipeline complete. Recommendation: APPROVE. Case ready for human review.', delay: 15600 },
]

const AGENT_COLORS = {
  'Orchestrator':          GOLD,
  'Doc Auditor':           '#60A5FA',
  'KYC Guardian':          '#A78BFA',
  'Dynamic Compliance':    '#34D399',
  'Stress-Test Simulator': '#F97316',
  'Asset Tokenizer':       '#22D3EE',
  'Consensus Signer':      '#FDE68A',
}

export default function BandRoom() {
  const { id }          = useParams()
  const navigate        = useNavigate()
  const { user, logout } = useSession()
  const [visible, setVisible] = useState([])
  const [done, setDone]       = useState(false)

  useEffect(() => {
    const timers = []
    MOCK_MSGS.forEach((m, i) => {
      timers.push(setTimeout(() => {
        setVisible(prev => [...prev, { ...m, msg: m.msg.replace('{id}', id), i }])
        if (i === MOCK_MSGS.length - 1) {
          setTimeout(() => setDone(true), 800)
        }
      }, m.delay))
    })
    return () => timers.forEach(clearTimeout)
  }, [id])

  function handleReview() {
    navigate(`/review/${id}`)
  }

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div style={{ minHeight: '100vh', background: NAVY, fontFamily: "'Montserrat', sans-serif" }}>
      {/* Navbar */}
      <nav style={{
        height: 60, background: NAVY_MID, borderBottom: `1px solid ${BORDER}`,
        display: 'flex', alignItems: 'center', paddingInline: '2rem', gap: '1rem',
        position: 'sticky', top: 0, zIndex: 50,
      }}>
        <svg width="26" height="26" viewBox="0 0 56 56" fill="none">
          <polygon points="28,2 52,15 52,41 28,54 4,41 4,15" fill={GOLD} opacity="0.15" stroke={GOLD} strokeWidth="1.5" />
          <text x="28" y="33" textAnchor="middle" fill={GOLD} fontSize="16" fontWeight="800" fontFamily="Montserrat,sans-serif">B</text>
        </svg>
        <span style={{ fontSize: 14, fontWeight: 800, letterSpacing: '0.18em', color: TEXT }}>BRIGHTUITY</span>
        <span style={{ fontSize: 9, color: TEXT_DIM, letterSpacing: '0.06em', marginTop: 1 }}>BAND COORDINATION ROOM</span>
        <div style={{ flex: 1 }} />
        <button
          onClick={() => navigate('/dashboard')}
          style={{ background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6, padding: '4px 10px', color: TEXT_DIM, fontSize: 10, fontFamily: 'inherit', cursor: 'pointer' }}
        >← DASHBOARD</button>
        {user && (
          <button
            onClick={handleLogout}
            style={{ background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6, padding: '4px 10px', color: TEXT_DIM, fontSize: 10, fontFamily: 'inherit', cursor: 'pointer' }}
          >SIGN OUT</button>
        )}
      </nav>

      <main style={{ maxWidth: 860, margin: '0 auto', padding: '2.5rem 2rem' }}>
        {/* Header */}
        <div style={{ marginBottom: '1.75rem', animation: 'slideUp 0.4s ease' }}>
          <div style={{ fontSize: 11, color: GOLD, letterSpacing: '0.14em', marginBottom: 6 }}>CASE {id}</div>
          <h1 style={{ fontSize: 20, fontWeight: 800, color: TEXT, marginBottom: 6 }}>
            Band Coordination Room
          </h1>
          <p style={{ fontSize: 12, color: TEXT_DIM }}>
            Seven agents are coordinating via Band @mentions. Each message is an auditable coordination record.
          </p>
        </div>

        {/* Chat window */}
        <div style={{
          background: NAVY_MID, border: `1px solid ${BORDER}`, borderRadius: 14,
          padding: '1.5rem', minHeight: 420, marginBottom: '1.5rem',
          position: 'relative', overflow: 'hidden',
        }}>
          {/* Top accent */}
          <div style={{ position: 'absolute', top: 0, left: '8%', right: '8%', height: 2, background: `linear-gradient(90deg,transparent,${GOLD},transparent)` }} />

          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: '1.25rem' }}>
            <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#34D399', animation: 'pulse 1.5s infinite' }} />
            <span style={{ fontSize: 10.5, color: TEXT_DIM, letterSpacing: '0.08em' }}>BAND CHANNEL · LIVE</span>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
            {visible.map(m => (
              <div key={m.i} style={{ animation: 'chatEntry 0.3s ease', display: 'flex', gap: '0.75rem', alignItems: 'flex-start' }}>
                <div style={{
                  flexShrink: 0, fontSize: 10, fontWeight: 700, letterSpacing: '0.06em',
                  color: AGENT_COLORS[m.agent] ?? TEXT_DIM,
                  minWidth: 160, paddingTop: 1,
                }}>
                  @{m.agent}
                </div>
                <div style={{ fontSize: 12.5, color: TEXT, lineHeight: 1.5 }}>{m.msg}</div>
              </div>
            ))}

            {!done && visible.length > 0 && (
              <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
                <div style={{ minWidth: 160, fontSize: 10, color: TEXT_DIM }}>@System</div>
                <div style={{ display: 'flex', gap: 4 }}>
                  {[0, 1, 2].map(i => (
                    <div key={i} style={{
                      width: 6, height: 6, borderRadius: '50%', background: GOLD,
                      animation: `pulse 1s ease-in-out ${i * 0.2}s infinite`,
                    }} />
                  ))}
                </div>
              </div>
            )}

            {visible.length === 0 && (
              <div style={{ color: TEXT_DIM, fontSize: 12, paddingTop: '1rem' }}>
                Connecting to Band channel…
              </div>
            )}
          </div>
        </div>

        {/* Proceed button — enabled once pipeline completes */}
        <div style={{ textAlign: 'center' }}>
          <button
            onClick={handleReview}
            disabled={!done}
            style={{
              background: done
                ? `linear-gradient(135deg, ${GOLD} 0%, ${GOLD_DRK} 100%)`
                : NAVY_MID,
              border: `1px solid ${done ? GOLD : BORDER}`,
              borderRadius: 10, padding: '0.875rem 2.5rem',
              color: done ? NAVY : TEXT_DIM,
              fontSize: 12, fontWeight: 700, letterSpacing: '0.15em',
              fontFamily: 'inherit', cursor: done ? 'pointer' : 'not-allowed',
              boxShadow: done ? `0 4px 24px ${GOLD}35` : 'none',
              transition: 'all 0.3s',
            }}
          >
            {done ? 'PROCEED TO REVIEW →' : 'AWAITING PIPELINE COMPLETION…'}
          </button>
          {!done && (
            <div style={{ fontSize: 10.5, color: TEXT_DIM, marginTop: 8 }}>
              The button unlocks when the Consensus Signer seals the package.
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
