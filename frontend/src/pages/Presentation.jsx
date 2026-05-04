import { useState, useEffect, useCallback } from 'react'

const ACCENT = '#F5A623'
const BLUE = '#4F9CF9'
const DIM = '#8B9AB1'
const SURFACE = '#0F1629'
const BORDER = '#1E2D4A'

function Dot({ active }) {
  return (
    <div
      style={{
        width: active ? '2.4vw' : '0.6vw',
        height: '0.6vw',
        borderRadius: '9999px',
        background: active ? ACCENT : BORDER,
        transition: 'all 0.3s ease',
      }}
    />
  )
}

function Nav({ current, total, onPrev, onNext }) {
  return (
    <div style={{ position: 'fixed', bottom: '3.5vh', left: 0, right: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '2vw', zIndex: 100 }}>
      <button onClick={onPrev} disabled={current === 0} style={{ background: 'none', border: 'none', cursor: current === 0 ? 'default' : 'pointer', opacity: current === 0 ? 0.2 : 0.7, color: '#F0F4FF', fontSize: '1.8vw', lineHeight: 1, padding: '0.4vw 0.8vw' }}>&#8592;</button>
      <div style={{ display: 'flex', alignItems: 'center', gap: '0.6vw' }}>
        {Array.from({ length: total }).map((_, i) => <Dot key={i} active={i === current} />)}
      </div>
      <button onClick={onNext} disabled={current === total - 1} style={{ background: 'none', border: 'none', cursor: current === total - 1 ? 'default' : 'pointer', opacity: current === total - 1 ? 0.2 : 0.7, color: '#F0F4FF', fontSize: '1.8vw', lineHeight: 1, padding: '0.4vw 0.8vw' }}>&#8594;</button>
    </div>
  )
}

function SlideCounter({ current, total }) {
  return (
    <div style={{ position: 'fixed', top: '3vh', right: '4vw', fontFamily: "'DM Sans', sans-serif", fontSize: '1.3vw', color: DIM, letterSpacing: '0.05em', zIndex: 100 }}>
      {String(current + 1).padStart(2, '0')} / {String(total).padStart(2, '0')}
    </div>
  )
}

function GeoAccents() {
  return (
    <>
      <div style={{ position: 'absolute', top: '-8vw', right: '-8vw', width: '32vw', height: '32vw', borderRadius: '50%', border: `1px solid ${BORDER}`, opacity: 0.6, pointerEvents: 'none' }} />
      <div style={{ position: 'absolute', top: '-4vw', right: '-4vw', width: '20vw', height: '20vw', borderRadius: '50%', border: `1px solid #1E3060`, opacity: 0.5, pointerEvents: 'none' }} />
      <div style={{ position: 'absolute', bottom: '-10vw', left: '-6vw', width: '28vw', height: '28vw', borderRadius: '50%', border: `1px solid ${BORDER}`, opacity: 0.4, pointerEvents: 'none' }} />
    </>
  )
}

function GoldLine({ style = {} }) {
  return <div style={{ height: '2px', background: `linear-gradient(90deg, ${ACCENT}, transparent)`, ...style }} />
}

function Tag({ children }) {
  return (
    <span style={{ display: 'inline-block', fontFamily: "'DM Sans', sans-serif", fontSize: '1.1vw', fontWeight: 600, color: ACCENT, letterSpacing: '0.15em', textTransform: 'uppercase', padding: '0.3vh 0', marginBottom: '2vh' }}>
      {children}
    </span>
  )
}

function Slide01() {
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center' }}>
      <GeoAccents />
      <div style={{ position: 'absolute', top: 0, left: 0, width: '45vw', height: '100vh', background: 'linear-gradient(135deg, #0F1A35 0%, #080D1A 100%)', borderRight: `1px solid ${BORDER}` }} />
      <div style={{ position: 'absolute', top: '8vh', left: '4vw', right: '4vw', display: 'flex', alignItems: 'center', gap: '1vw' }}>
        <div style={{ width: '2.5vw', height: '2px', background: ACCENT }} />
        <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.2vw', color: ACCENT, letterSpacing: '0.2em', textTransform: 'uppercase', fontWeight: 600 }}>Gradus Media</span>
      </div>
      <div style={{ position: 'relative', zIndex: 10, paddingLeft: '6vw', paddingRight: '4vw', maxWidth: '60vw' }}>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '8.5vw', fontWeight: 800, lineHeight: 0.9, color: '#F0F4FF', letterSpacing: '-0.03em', marginBottom: '3vh', textWrap: 'balance' }}>
          Gradus<span style={{ color: ACCENT }}>AI</span>
        </div>
        <GoldLine style={{ width: '20vw', marginBottom: '3vh' }} />
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '2.4vw', fontWeight: 400, color: '#B8C8E8', lineHeight: 1.3, marginBottom: '4vh', textWrap: 'balance' }}>
          Intelligent Operations Platform
        </div>
        <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.5vw', color: DIM, lineHeight: 1.6, maxWidth: '44vw' }}>
          Content automation, AI bots, and analytics — built for the scale of modern Ukrainian business.
        </div>
      </div>
      <div style={{ position: 'absolute', right: '6vw', top: '50%', transform: 'translateY(-50%)', display: 'flex', flexDirection: 'column', gap: '3vh' }}>
        {['Content Pipeline', 'AI Bots × 5', 'Legal Intelligence', 'Photo Analytics'].map((label, i) => (
          <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '1.2vw' }}>
            <div style={{ width: '0.5vw', height: '0.5vw', borderRadius: '50%', background: i === 0 ? ACCENT : BLUE, opacity: 0.8 }} />
            <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.3vw', color: '#8B9AB1' }}>{label}</span>
          </div>
        ))}
      </div>
      <div style={{ position: 'absolute', bottom: '6vh', left: '6vw', fontFamily: "'DM Sans', sans-serif", fontSize: '1.1vw', color: DIM, letterSpacing: '0.08em' }}>2026</div>
    </div>
  )
}

function Slide02() {
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', paddingLeft: '8vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10, width: '100%' }}>
        <Tag>The challenge</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '4.8vw', fontWeight: 700, color: '#F0F4FF', lineHeight: 1.05, letterSpacing: '-0.02em', marginBottom: '5vh', maxWidth: '65vw', textWrap: 'balance' }}>
          Scale kills quality.<br /><span style={{ color: ACCENT }}>Unless you automate.</span>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '2.5vw', maxWidth: '78vw' }}>
          {[
            { num: '7', unit: 'sources', desc: 'Content scraped from 5 English and 2 Ukrainian media platforms — every hour, around the clock.' },
            { num: '2', unit: 'platforms', desc: 'Facebook and LinkedIn publishing — scheduled, approved, and posted without a single manual action.' },
            { num: '100%', unit: 'automated', desc: 'Scraping, AI translation, image sourcing, and scheduling — fully hands-off once configured.' },
          ].map(({ num, unit, desc }) => (
            <div key={num} style={{ padding: '2.5vh 2vw', background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw', borderTop: `3px solid ${ACCENT}` }}>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '4.5vw', fontWeight: 800, color: ACCENT, lineHeight: 1, marginBottom: '0.5vh' }}>{num}</div>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.4vw', fontWeight: 600, color: '#F0F4FF', marginBottom: '1.5vh' }}>{unit}</div>
              <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.3vw', color: DIM, lineHeight: 1.5 }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide03() {
  const layers = [
    { label: 'Presentation Layer', color: BLUE, items: ['React + Vite', 'Tailwind CSS', 'Admin Dashboard', 'HR Dashboard', 'Law Dashboard'] },
    { label: 'Application Layer', color: ACCENT, items: ['FastAPI (Python)', 'APScheduler', 'SQLAlchemy ORM', 'Telegram Webhooks', 'REST APIs'] },
    { label: 'Intelligence Layer', color: '#A78BFA', items: ['Claude Sonnet / Haiku', 'OpenAI GPT-4o', 'Pinecone Vector DB', 'Vision API', 'RAG Pipeline'] },
    { label: 'Data Layer', color: '#34D399', items: ['PostgreSQL', 'Facebook Graph API', 'LinkedIn API v2', 'NBU Exchange Rate', 'Robota.ua API'] },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>Architecture</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3.6vw', fontWeight: 700, color: '#F0F4FF', marginBottom: '4.5vh', letterSpacing: '-0.02em' }}>
          Four-layer system design
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '2vw' }}>
          {layers.map(({ label, color, items }) => (
            <div key={label} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw', overflow: 'hidden' }}>
              <div style={{ padding: '1.5vh 1.5vw', borderBottom: `1px solid ${BORDER}`, display: 'flex', alignItems: 'center', gap: '0.8vw' }}>
                <div style={{ width: '0.7vw', height: '0.7vw', borderRadius: '50%', background: color, flexShrink: 0 }} />
                <span style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.15vw', fontWeight: 600, color: '#F0F4FF' }}>{label}</span>
              </div>
              <div style={{ padding: '1.5vh 1.5vw', display: 'flex', flexDirection: 'column', gap: '1.2vh' }}>
                {items.map(item => (
                  <div key={item} style={{ display: 'flex', alignItems: 'center', gap: '0.7vw' }}>
                    <div style={{ width: '0.35vw', height: '0.35vw', borderRadius: '50%', background: color, opacity: 0.7, flexShrink: 0 }} />
                    <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.25vw', color: DIM }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div style={{ marginTop: '3vh', display: 'flex', alignItems: 'center', gap: '3vw' }}>
          <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.2vw', color: DIM }}>Deployed on</span>
          {['Render (Docker)', 'Nix environment', 'PostgreSQL (managed)'].map(t => (
            <span key={t} style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.2vw', color: '#F0F4FF', background: '#1A2540', padding: '0.4vh 1vw', borderRadius: '0.4vw', border: `1px solid ${BORDER}` }}>{t}</span>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide04() {
  const bots = [
    { name: 'Maya', role: 'Marketing & Trends Expert', desc: 'Answers brand strategy and market trend questions. Learns from real queries and promotes AI-generated answers to production.', color: ACCENT },
    { name: 'Alex Gradus', role: 'Bar Operations Consultant', desc: 'Premium HoReCa advisor for AVTD distribution partners. Preset-first cost optimization with Claude fallback.', color: BLUE },
    { name: 'Solomon', role: 'Supreme Court Search', desc: 'Searches Ukrainian cassation decisions. Claude parses legal queries, Haiku scorer rates relevance 0–10, returns top substantive results.', color: '#A78BFA' },
    { name: 'Alex Photo', role: 'Merchandising Verifier', desc: 'Analyzes shelf photos against AVTD standards. Two-pass vision: full scan + targeted Ukrainka/Helsinki retry. $0.12 per report.', color: '#34D399' },
    { name: 'HR Bot', role: 'Employee Onboarding', desc: 'RAG-powered knowledge base with Pinecone. Phone-based auth, 4 access levels, 44 legal templates, document upload.', color: '#FB923C' },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>AI Bot Ecosystem</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3.6vw', fontWeight: 700, color: '#F0F4FF', marginBottom: '4vh', letterSpacing: '-0.02em' }}>
          Five specialized Telegram agents
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(5, 1fr)', gap: '1.5vw' }}>
          {bots.map(({ name, role, desc, color }) => (
            <div key={name} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw', padding: '2vh 1.5vw', borderTop: `3px solid ${color}` }}>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.6vw', fontWeight: 700, color, marginBottom: '0.4vh' }}>{name}</div>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.1vw', fontWeight: 600, color: '#F0F4FF', marginBottom: '1.5vh', lineHeight: 1.3 }}>{role}</div>
              <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.15vw', color: DIM, lineHeight: 1.55 }}>{desc}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide05() {
  const steps = [
    { label: '7 Sources', sub: '5 English + 2 Ukrainian', color: ACCENT },
    { label: 'AI Scraping', sub: 'Playwright + Trafilatura', color: BLUE },
    { label: 'Claude Translation', sub: 'EN → Ukrainian', color: '#A78BFA' },
    { label: 'Image Sourcing', sub: '4-tier Unsplash', color: '#34D399' },
    { label: 'Human Review', sub: 'Telegram approval', color: '#FB923C' },
    { label: 'Scheduled Post', sub: 'Facebook + LinkedIn', color: '#F472B6' },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>Content Pipeline</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3.6vw', fontWeight: 700, color: '#F0F4FF', marginBottom: '5vh', letterSpacing: '-0.02em' }}>
          From raw source to published post — fully automated
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0', marginBottom: '4.5vh' }}>
          {steps.map(({ label, sub, color }, i) => (
            <div key={label} style={{ display: 'flex', alignItems: 'center', flex: 1 }}>
              <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                <div style={{ width: '4vw', height: '4vw', borderRadius: '50%', background: SURFACE, border: `2px solid ${color}`, display: 'flex', alignItems: 'center', justifyContent: 'center', marginBottom: '1.5vh' }}>
                  <span style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.4vw', fontWeight: 700, color }}>{i + 1}</span>
                </div>
                <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.25vw', fontWeight: 600, color: '#F0F4FF', textAlign: 'center', marginBottom: '0.4vh' }}>{label}</div>
                <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.1vw', color: DIM, textAlign: 'center' }}>{sub}</div>
              </div>
              {i < steps.length - 1 && (
                <div style={{ width: '3vw', height: '2px', background: `linear-gradient(90deg, ${color}, ${steps[i + 1].color})`, flexShrink: 0 }} />
              )}
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', gap: '3vw' }}>
          {[
            { label: 'Deduplication', detail: 'DB row locking + idempotency checks prevent duplicate posts across runs.' },
            { label: 'LinkedIn Native', detail: 'Text posts with first-comment source URLs — no link preview penalty.' },
            { label: 'Daily Digest', detail: 'Claude Haiku generates daily insights from top 5 articles, posted 07:00 UTC.' },
          ].map(({ label, detail }) => (
            <div key={label} style={{ flex: 1, padding: '2vh 1.5vw', background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw' }}>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.3vw', fontWeight: 600, color: ACCENT, marginBottom: '0.8vh' }}>{label}</div>
              <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.2vw', color: DIM, lineHeight: 1.5 }}>{detail}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide06() {
  const stats = [
    { n: '24 / 7', label: 'Automation uptime', sub: 'APScheduler keeps content flowing with zero manual intervention' },
    { n: '5', label: 'AI Telegram bots', sub: 'Maya · Alex Gradus · Solomon · Alex Photo · HR Bot' },
    { n: '1,028', label: 'Legal corpus chunks', sub: '15 Ukrainian laws + INCOTERMS 2020 indexed in Pinecone' },
    { n: '44', label: 'Contract templates', sub: 'Instant access to supply agreement library via HR Bot menu' },
    { n: '$0.12', label: 'Per shelf report', sub: 'Full AVTD merchandising analysis with two-pass vision AI' },
    { n: '7', label: 'Content sources', sub: 'Monitored continuously with Playwright + Trafilatura extraction' },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>By the numbers</Tag>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '2.5vw 3vw' }}>
          {stats.map(({ n, label, sub }) => (
            <div key={n} style={{ display: 'flex', flexDirection: 'column' }}>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '5.5vw', fontWeight: 800, color: ACCENT, lineHeight: 1, letterSpacing: '-0.03em', marginBottom: '0.5vh' }}>{n}</div>
              <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.5vw', fontWeight: 600, color: '#F0F4FF', marginBottom: '0.6vh' }}>{label}</div>
              <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.2vw', color: DIM, lineHeight: 1.5 }}>{sub}</div>
              <div style={{ marginTop: '1.5vh', height: '1px', background: BORDER, width: '80%' }} />
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide07() {
  const cols = [
    {
      title: 'Backend',
      color: ACCENT,
      items: ['Python 3.11 + FastAPI', 'PostgreSQL + SQLAlchemy', 'APScheduler (cron jobs)', 'psycopg2 (direct SQL)', 'Trafilatura + Playwright'],
    },
    {
      title: 'AI & Intelligence',
      color: BLUE,
      items: ['Claude Sonnet 3.5 / Haiku', 'OpenAI GPT-4o (embeddings)', 'Pinecone Vector DB', 'Telethon (Telegram scraper)', 'python-docx (DOCX export)'],
    },
    {
      title: 'Frontend',
      color: '#A78BFA',
      items: ['React 18 + Vite', 'Tailwind CSS', 'React Router v6', 'Recharts (analytics)', 'Google Analytics 4'],
    },
    {
      title: 'Integrations',
      color: '#34D399',
      items: ['Telegram Bot API (5 bots)', 'Facebook Graph API', 'LinkedIn API v2', 'WayForPay (payments)', 'NBU Exchange Rate API'],
    },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>Tech Stack</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3.6vw', fontWeight: 700, color: '#F0F4FF', marginBottom: '4.5vh', letterSpacing: '-0.02em' }}>
          Production-grade, service-oriented
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '2vw' }}>
          {cols.map(({ title, color, items }) => (
            <div key={title} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw', overflow: 'hidden' }}>
              <div style={{ padding: '1.8vh 1.5vw', background: `${color}14`, borderBottom: `1px solid ${color}30` }}>
                <span style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.4vw', fontWeight: 700, color }}>{title}</span>
              </div>
              <div style={{ padding: '1.8vh 1.5vw', display: 'flex', flexDirection: 'column', gap: '1.4vh' }}>
                {items.map(item => (
                  <div key={item} style={{ display: 'flex', alignItems: 'flex-start', gap: '0.7vw' }}>
                    <span style={{ color, fontSize: '1.3vw', lineHeight: '1.6vw', flexShrink: 0 }}>—</span>
                    <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.25vw', color: '#B8C8E8', lineHeight: 1.4 }}>{item}</span>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide08() {
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center' }}>
      <GeoAccents />
      <div style={{ position: 'absolute', top: 0, left: 0, width: '50vw', height: '100vh', background: 'linear-gradient(135deg, #0A1830 0%, #080D1A 100%)', borderRight: `1px solid ${BORDER}` }} />
      <div style={{ position: 'relative', zIndex: 10, display: 'grid', gridTemplateColumns: '1fr 1fr', width: '100%' }}>
        <div style={{ paddingLeft: '7vw', paddingRight: '5vw', paddingTop: '0', paddingBottom: '0' }}>
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.1vw', fontWeight: 600, color: ACCENT, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '2vh' }}>HR Operations</div>
          <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3vw', fontWeight: 700, color: '#F0F4FF', lineHeight: 1.1, marginBottom: '3.5vh', letterSpacing: '-0.02em', textWrap: 'balance' }}>
            Onboarding on autopilot
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2.5vh' }}>
            {[
              { stat: '24/7', detail: 'Employee Q&A answered by RAG bot — no HR team involvement for routine questions' },
              { stat: '44', detail: 'Legal contract templates instantly accessible via interactive Telegram menu' },
              { stat: '4 levels', detail: 'Phone-based authentication with role-gated content access per employee tier' },
            ].map(({ stat, detail }) => (
              <div key={stat} style={{ display: 'flex', gap: '1.5vw', alignItems: 'flex-start' }}>
                <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '2.2vw', fontWeight: 800, color: ACCENT, lineHeight: 1, minWidth: '7vw' }}>{stat}</div>
                <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.3vw', color: DIM, lineHeight: 1.55, paddingTop: '0.3vh' }}>{detail}</div>
              </div>
            ))}
          </div>
        </div>
        <div style={{ paddingLeft: '5vw', paddingRight: '7vw' }}>
          <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.1vw', fontWeight: 600, color: BLUE, letterSpacing: '0.15em', textTransform: 'uppercase', marginBottom: '2vh' }}>Field Operations</div>
          <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3vw', fontWeight: 700, color: '#F0F4FF', lineHeight: 1.1, marginBottom: '3.5vh', letterSpacing: '-0.02em', textWrap: 'balance' }}>
            Merchandising at scale
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '2.5vh' }}>
            {[
              { stat: '23', detail: 'Product reference images — ADJARI, Dovbush, GreenDay, Helsinki, Ukrainka visual anchors for AI' },
              { stat: '~15%', detail: 'Target deviation after two-pass retry system — down from 36% baseline on cognac detection' },
              { stat: '$0.12', detail: 'Per complete shelf report — full AVTD portfolio analysis across all product categories' },
            ].map(({ stat, detail }) => (
              <div key={stat} style={{ display: 'flex', gap: '1.5vw', alignItems: 'flex-start' }}>
                <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '2.2vw', fontWeight: 800, color: BLUE, lineHeight: 1, minWidth: '7vw' }}>{stat}</div>
                <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.3vw', color: DIM, lineHeight: 1.55, paddingTop: '0.3vh' }}>{detail}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Slide09() {
  const items = [
    { title: 'HeyGen Avatar Video', detail: 'Weekly AI-generated video digest — Alex Gradus persona, 60-90s script via Claude Sonnet, distributed to Facebook, Telegram, and LinkedIn.', status: 'Ready to activate', color: ACCENT },
    { title: 'Salary Intelligence', detail: 'Robota.ua JWT-authenticated GraphQL analytics — market salary benchmarks with dual UAH/USD display and live NBU exchange rates.', status: 'Live in Hunt module', color: '#34D399' },
    { title: 'Maya Hunt Recruitment', detail: '2×2 Telegram action menu, vacancy scoring, candidate auto-posting, hire tracking, and 8-section ROI analytics dashboard.', status: 'Fully deployed', color: BLUE },
    { title: 'Solomon Contracts', detail: 'AI-powered supply contract risk analysis — Claude Sonnet free-form scan, Pinecone RAG grounding, DOCX output with risk notes and legal opinion.', status: 'Phase 2 complete', color: '#A78BFA' },
  ]
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', flexDirection: 'column', justifyContent: 'center', paddingLeft: '7vw', paddingRight: '7vw' }}>
      <GeoAccents />
      <div style={{ position: 'relative', zIndex: 10 }}>
        <Tag>Platform modules</Tag>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '3.6vw', fontWeight: 700, color: '#F0F4FF', marginBottom: '4.5vh', letterSpacing: '-0.02em' }}>
          Beyond content — a full operations layer
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: '2vw' }}>
          {items.map(({ title, detail, status, color }) => (
            <div key={title} style={{ background: SURFACE, border: `1px solid ${BORDER}`, borderRadius: '0.8vw', padding: '2.5vh 2vw', display: 'flex', flexDirection: 'column', gap: '1vh' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.6vw', fontWeight: 700, color }}>{title}</div>
                <span style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.05vw', color, background: `${color}18`, padding: '0.3vh 0.8vw', borderRadius: '0.4vw', border: `1px solid ${color}40`, flexShrink: 0, marginLeft: '1vw' }}>{status}</span>
              </div>
              <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.25vw', color: DIM, lineHeight: 1.55 }}>{detail}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function Slide10() {
  return (
    <div style={{ width: '100vw', height: '100vh', background: '#080D1A', position: 'relative', overflow: 'hidden', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <GeoAccents />
      <div style={{ position: 'absolute', inset: 0, background: 'radial-gradient(ellipse at 50% 60%, #0F1E40 0%, #080D1A 70%)' }} />
      <div style={{ position: 'relative', zIndex: 10, textAlign: 'center', maxWidth: '70vw' }}>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.5vw', fontWeight: 600, color: ACCENT, letterSpacing: '0.2em', textTransform: 'uppercase', marginBottom: '3vh' }}>Gradus Media — 2026</div>
        <div style={{ fontFamily: "'Space Grotesk', sans-serif", fontSize: '6vw', fontWeight: 800, color: '#F0F4FF', lineHeight: 0.95, letterSpacing: '-0.03em', marginBottom: '4vh', textWrap: 'balance' }}>
          Built for the future of<br /><span style={{ color: ACCENT }}>Ukrainian business.</span>
        </div>
        <div style={{ width: '12vw', height: '2px', background: `linear-gradient(90deg, transparent, ${ACCENT}, transparent)`, margin: '0 auto', marginBottom: '4vh' }} />
        <div style={{ fontFamily: "'DM Sans', sans-serif", fontSize: '1.6vw', color: DIM, lineHeight: 1.6, maxWidth: '50vw', margin: '0 auto' }}>
          GradusAI is a living platform — every expert correction, every agent query, every shelf report makes it smarter.
        </div>
      </div>
    </div>
  )
}

const SLIDES = [Slide01, Slide02, Slide03, Slide04, Slide05, Slide06, Slide07, Slide08, Slide09, Slide10]
const TITLES = ['Overview', 'Challenge', 'Architecture', 'Bot Ecosystem', 'Content Pipeline', 'Numbers', 'Tech Stack', 'Business Impact', 'Platform Modules', 'Closing']

export default function Presentation() {
  const [current, setCurrent] = useState(0)
  const total = SLIDES.length

  const prev = useCallback(() => setCurrent(c => Math.max(0, c - 1)), [])
  const next = useCallback(() => setCurrent(c => Math.min(total - 1, c + 1)), [total])

  useEffect(() => {
    const handler = (e) => {
      if (e.key === 'ArrowRight' || e.key === 'ArrowDown' || e.key === ' ') { e.preventDefault(); next() }
      if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') { e.preventDefault(); prev() }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [prev, next])

  const SlideComponent = SLIDES[current]

  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 9999, background: '#080D1A', fontFamily: "'Space Grotesk', 'DM Sans', sans-serif" }}>
      <SlideComponent />
      <SlideCounter current={current} total={total} />
      <Nav current={current} total={total} onPrev={prev} onNext={next} />
      <div style={{ position: 'fixed', top: '3vh', left: '4vw', fontFamily: "'Space Grotesk', sans-serif", fontSize: '1.1vw', fontWeight: 700, color: '#F0F4FF', letterSpacing: '-0.01em', zIndex: 100 }}>
        Gradus<span style={{ color: ACCENT }}>AI</span>
      </div>
      <div style={{ position: 'fixed', top: '2.4vh', left: 0, right: 0, display: 'flex', justifyContent: 'center', zIndex: 100 }}>
        <div style={{ display: 'flex', gap: '0.2vw', background: '#0F1629', border: '1px solid #1E2D4A', borderRadius: '2vw', padding: '0.5vh 1.5vw', alignItems: 'center' }}>
          {TITLES.map((title, i) => (
            <button
              key={i}
              onClick={() => setCurrent(i)}
              style={{
                background: i === current ? '#F5A62318' : 'none',
                border: 'none',
                cursor: 'pointer',
                fontFamily: "'DM Sans', sans-serif",
                fontSize: '1.05vw',
                fontWeight: i === current ? 600 : 400,
                color: i === current ? ACCENT : '#8B9AB1',
                padding: '0.3vh 0.9vw',
                borderRadius: '1vw',
                transition: 'all 0.2s',
              }}
            >
              {title}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
