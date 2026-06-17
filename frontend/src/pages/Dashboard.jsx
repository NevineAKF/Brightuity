import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useSession } from '../context/SessionContext.jsx'

/* ── Design tokens ──────────────────────────────────────────────────── */
const NAVY      = '#0A1A2F'
const NAVY_MID  = '#0F2340'
const NAVY_CARD = '#0D1F38'
const BORDER    = '#1E3A5F'
const GOLD      = '#E8A93D'
const GOLD_DRK  = '#C4891A'
const TEXT      = '#E2E8F0'
const TEXT_DIM  = '#8BA3C1'
const TEXT_FAINT= '#4A6A8A'
const GREEN     = '#1B7F4B'
const RED       = '#B3261E'
const AMBER     = '#D97706'

/* ── Hardcoded queue — real data wiring comes in the next step ──────── */
const CASES = [
  {
    request_id:    'REQ-2041',
    full_name:     'Marcus Weber',
    nationality:   'German',
    country_flag:  '🇩🇪',
    asset_type:    'Commercial Real Estate',
    asset_detail:  'Grade A office, Frankfurt CBD',
    asset_value_eur: 2500000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-3F2A9C4E',
    photo_url:     'https://randomuser.me/api/portraits/men/42.jpg',
  },
  {
    request_id:    'REQ-2042',
    full_name:     'Sofia Andreou',
    nationality:   'Greek',
    country_flag:  '🇬🇷',
    asset_type:    'Residential Property',
    asset_detail:  'Luxury apartment, Athens Riviera',
    asset_value_eur: 850000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-7B1D5E8A',
    photo_url:     'https://randomuser.me/api/portraits/women/23.jpg',
  },
  {
    request_id:    'REQ-2043',
    full_name:     'Viktor Petrov',
    nationality:   'Bulgarian',
    country_flag:  '🇧🇬',
    asset_type:    'Gold Reserve',
    asset_detail:  '1,200 troy oz verified bullion',
    asset_value_eur: 1200000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-2C8F1A3D',
    photo_url:     'https://randomuser.me/api/portraits/men/77.jpg',
  },
  {
    request_id:    'REQ-2044',
    full_name:     'Isabella Rossi',
    nationality:   'Italian',
    country_flag:  '🇮🇹',
    asset_type:    'Commercial Real Estate',
    asset_detail:  'Mixed-use complex, Milan',
    asset_value_eur: 4200000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-9A4C7E2B',
    photo_url:     'https://randomuser.me/api/portraits/women/34.jpg',
  },
  {
    request_id:    'REQ-2045',
    full_name:     'Liam O\'Brien',
    nationality:   'Irish',
    country_flag:  '🇮🇪',
    asset_type:    'Government Bond Portfolio',
    asset_detail:  'EU sovereign bonds, AAA-rated',
    asset_value_eur: 5750000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-4D3B6F1C',
    photo_url:     'https://randomuser.me/api/portraits/men/15.jpg',
  },
  {
    request_id:    'REQ-2046',
    full_name:     'Amélie Dupont',
    nationality:   'French',
    country_flag:  '🇫🇷',
    asset_type:    'Fine Art Collection',
    asset_detail:  '12 provenance-verified works',
    asset_value_eur: 3100000,
    status:        'pending',
    encrypted_doc_id: 'EVP-DOC-6E9A2C5D',
    photo_url:     'https://randomuser.me/api/portraits/women/61.jpg',
  },
]

/* ── Status badge ───────────────────────────────────────────────────── */
function StatusBadge({ status }) {
  const cfg = {
    pending:     { label: 'PENDING',     bg: `${NAVY_MID}`,     color: TEXT_DIM, border: BORDER },
    processing:  { label: 'PROCESSING',  bg: `${AMBER}18`,      color: AMBER,    border: `${AMBER}44` },
    awaiting_decision: { label: 'AWAITING DECISION', bg: `${GOLD}18`, color: GOLD, border: `${GOLD}44` },
    authorized:  { label: 'AUTHORIZED',  bg: `${GREEN}20`,      color: '#34D399', border: `${GREEN}55` },
    rejected:    { label: 'REJECTED',    bg: `${RED}20`,        color: '#F87171', border: `${RED}55` },
    error:       { label: 'ERROR',       bg: `${RED}20`,        color: '#F87171', border: `${RED}55` },
  }
  const s = cfg[status] ?? cfg.pending
  return (
    <span style={{
      fontSize: 9.5, fontWeight: 700, letterSpacing: '0.1em',
      padding: '3px 8px', borderRadius: 4,
      background: s.bg, color: s.color, border: `1px solid ${s.border}`,
    }}>{s.label}</span>
  )
}

/* ── Case card ──────────────────────────────────────────────────────── */
function CaseCard({ c, onClick }) {
  const [hov, setHov] = useState(false)
  const fmtEur = v => '€' + (v >= 1_000_000
    ? (v / 1_000_000).toFixed(2) + 'M'
    : (v / 1_000).toFixed(0) + 'K')

  return (
    <div
      onClick={onClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: hov ? '#112238' : NAVY_CARD,
        border: `1px solid ${hov ? `${GOLD}55` : BORDER}`,
        borderRadius: 14, padding: '1.25rem',
        cursor: 'pointer', transition: 'all 0.2s',
        transform: hov ? 'translateY(-2px)' : 'none',
        boxShadow: hov ? `0 8px 32px rgba(0,0,0,0.4), 0 0 0 1px ${GOLD}22` : 'none',
        display: 'flex', flexDirection: 'column', gap: '0.75rem',
        animation: 'fadeIn 0.35s ease',
      }}
    >
      {/* Header: photo + name + badge */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: '0.875rem' }}>
        <div style={{ position: 'relative', flexShrink: 0 }}>
          <img
            src={c.photo_url}
            alt={c.full_name}
            width={52} height={52}
            style={{ borderRadius: '50%', border: `2px solid ${BORDER}`, objectFit: 'cover', display: 'block' }}
            onError={e => { e.target.style.display = 'none' }}
          />
          {/* Verified tick */}
          <div style={{
            position: 'absolute', bottom: -2, right: -2,
            width: 18, height: 18, borderRadius: '50%',
            background: GOLD, border: `2px solid ${NAVY_CARD}`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 9, color: NAVY, fontWeight: 800,
          }}>✓</div>
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ fontSize: 14, fontWeight: 700, color: TEXT, marginBottom: 3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
            {c.full_name}
          </div>
          <div style={{ fontSize: 11, color: TEXT_DIM }}>
            {c.country_flag} {c.nationality}
          </div>
          <div style={{ marginTop: 5 }}>
            <StatusBadge status={c.status} />
          </div>
        </div>
      </div>

      {/* Divider */}
      <div style={{ height: 1, background: BORDER }} />

      {/* Asset info */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontSize: 10, color: TEXT_DIM, letterSpacing: '0.08em', marginBottom: 2 }}>ASSET TYPE</div>
          <div style={{ fontSize: 12, fontWeight: 600, color: TEXT }}>{c.asset_type}</div>
          <div style={{ fontSize: 10.5, color: TEXT_DIM, marginTop: 2 }}>{c.asset_detail}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 10, color: TEXT_DIM, letterSpacing: '0.08em', marginBottom: 2 }}>VALUE</div>
          <div style={{ fontSize: 16, fontWeight: 700, color: GOLD }}>{fmtEur(c.asset_value_eur)}</div>
        </div>
      </div>

      {/* Encrypted doc ID */}
      <div style={{
        background: NAVY, borderRadius: 6, padding: '0.4rem 0.6rem',
        display: 'flex', alignItems: 'center', gap: 6,
      }}>
        <span style={{ fontSize: 10, color: TEXT_FAINT }}>🔒</span>
        <span style={{ fontSize: 9.5, color: TEXT_FAINT, fontFamily: "'JetBrains Mono',monospace", letterSpacing: '0.04em' }}>
          {c.encrypted_doc_id}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 9.5, color: TEXT_FAINT, fontFamily: "'JetBrains Mono',monospace" }}>
          #{c.request_id}
        </span>
      </div>

      {/* CTA */}
      <div style={{
        padding: '0.55rem', borderRadius: 8, textAlign: 'center',
        background: hov ? `${GOLD}22` : 'transparent',
        border: `1px solid ${hov ? `${GOLD}55` : BORDER}`,
        color: hov ? GOLD : TEXT_DIM,
        fontSize: 11, fontWeight: 600, letterSpacing: '0.1em',
        transition: 'all 0.2s',
      }}>
        {hov ? 'INITIATE REVIEW →' : 'CLICK TO REVIEW'}
      </div>
    </div>
  )
}

/* ── Navbar ─────────────────────────────────────────────────────────── */
function Navbar({ user, onLogout }) {
  return (
    <nav style={{
      height: 60, background: NAVY_MID, borderBottom: `1px solid ${BORDER}`,
      display: 'flex', alignItems: 'center', paddingInline: '2rem', gap: '1rem',
      position: 'sticky', top: 0, zIndex: 50,
    }}>
      {/* Logo */}
      <svg width="28" height="28" viewBox="0 0 56 56" fill="none" style={{ flexShrink: 0 }}>
        <polygon points="28,2 52,15 52,41 28,54 4,41 4,15" fill={GOLD} opacity="0.15" stroke={GOLD} strokeWidth="1.5" />
        <text x="28" y="33" textAnchor="middle" fill={GOLD} fontSize="16" fontWeight="800" fontFamily="Montserrat,sans-serif">B</text>
      </svg>
      <span style={{ fontSize: 15, fontWeight: 800, letterSpacing: '0.18em', color: TEXT }}>BRIGHTUITY</span>
      <span style={{ fontSize: 9.5, color: GOLD, letterSpacing: '0.1em', marginTop: 1 }}>RWA TOKENIZATION INTELLIGENCE</span>

      <div style={{ flex: 1 }} />

      {/* User info */}
      {user && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: TEXT }}>{user.name}</div>
            <div style={{ fontSize: 10, color: TEXT_DIM }}>{user.role}</div>
          </div>
          <div style={{
            width: 34, height: 34, borderRadius: '50%',
            background: `linear-gradient(135deg, ${GOLD} 0%, ${GOLD_DRK} 100%)`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontSize: 12, fontWeight: 800, color: NAVY, flexShrink: 0,
          }}>
            {user.name.split(' ').map(w => w[0]).join('')}
          </div>
          <button
            onClick={onLogout}
            style={{
              background: 'none', border: `1px solid ${BORDER}`, borderRadius: 6,
              padding: '4px 10px', color: TEXT_DIM, fontSize: 10, fontFamily: 'inherit',
              cursor: 'pointer', letterSpacing: '0.08em', transition: 'all 0.2s',
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = GOLD; e.currentTarget.style.color = GOLD }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = BORDER; e.currentTarget.style.color = TEXT_DIM }}
          >
            SIGN OUT
          </button>
        </div>
      )}
    </nav>
  )
}

/* ── Dashboard page ─────────────────────────────────────────────────── */
export default function Dashboard() {
  const navigate    = useNavigate()
  const { user, logout } = useSession()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  function handleCardClick(c) {
    // Navigate to Band room first; room triggers pipeline + then goes to review
    navigate(`/room/${c.request_id}`)
  }

  return (
    <div style={{ minHeight: '100vh', background: NAVY, fontFamily: "'Montserrat', sans-serif" }}>
      <Navbar user={user} onLogout={handleLogout} />

      <main style={{ maxWidth: 1280, margin: '0 auto', padding: '2rem 2rem 3rem' }}>
        {/* Page header */}
        <div style={{ marginBottom: '2rem', animation: 'slideUp 0.4s ease' }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '1rem', marginBottom: 8 }}>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: TEXT, letterSpacing: '0.05em' }}>
              Tokenization Request Queue
            </h1>
            <span style={{
              fontSize: 11, fontWeight: 600, color: GOLD, letterSpacing: '0.1em',
              background: `${GOLD}15`, padding: '3px 10px', borderRadius: 20, border: `1px solid ${GOLD}30`,
            }}>
              {CASES.filter(c => c.status === 'pending').length} PENDING
            </span>
          </div>
          <p style={{ fontSize: 12, color: TEXT_DIM, maxWidth: 560 }}>
            Select a case to initiate the AI compliance review. The system will route
            it through all seven agents and surface the Decision Evidence Package for your authorization.
          </p>
        </div>

        {/* Stats strip */}
        <div style={{
          display: 'flex', gap: '1rem', marginBottom: '2rem',
          animation: 'slideUp 0.5s ease',
        }}>
          {[
            { label: 'Pending Review', value: '24', color: TEXT_DIM },
            { label: 'In Pipeline',    value: '3',  color: AMBER },
            { label: 'Authorized',     value: '48', color: '#34D399' },
            { label: 'Rejected',       value: '8',  color: '#F87171' },
          ].map(s => (
            <div key={s.label} style={{
              background: NAVY_MID, border: `1px solid ${BORDER}`, borderRadius: 10,
              padding: '0.75rem 1.25rem', minWidth: 130,
            }}>
              <div style={{ fontSize: 22, fontWeight: 800, color: s.color }}>{s.value}</div>
              <div style={{ fontSize: 10.5, color: TEXT_DIM, letterSpacing: '0.06em', marginTop: 2 }}>{s.label}</div>
            </div>
          ))}
        </div>

        {/* Case grid */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
          gap: '1.25rem',
        }}>
          {CASES.map(c => (
            <CaseCard key={c.request_id} c={c} onClick={() => handleCardClick(c)} />
          ))}
        </div>
      </main>
    </div>
  )
}
