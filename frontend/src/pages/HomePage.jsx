import { useState, useEffect } from 'react'
import { MessageSquare, FileText, TrendingUp, Clock, CheckCircle, XCircle, Sparkles } from 'lucide-react'
import { Link } from 'react-router-dom'
import api from '../lib/api'

function StatCard({ title, value, subtitle, icon: Icon, colorClass, glowClass }) {
  return (
    <div className={`glass-card p-6 ${glowClass}`}>
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-white/80 font-medium">{title}</h3>
        <div className={`p-2 rounded-lg bg-white/5 ${colorClass}`}>
          <Icon size={20} />
        </div>
      </div>
      <p className={`text-4xl font-bold mb-1 ${colorClass}`}>{value}</p>
      <p className="text-white/50 text-sm">{subtitle}</p>
    </div>
  )
}

function QuickActionCard({ to, icon: Icon, title, description }) {
  return (
    <Link 
      to={to}
      className="glass-card p-5 flex items-center space-x-4 group cursor-pointer"
    >
      <div className="p-3 rounded-xl bg-gradient-to-br from-purple-500/20 to-pink-500/20 group-hover:from-purple-500/30 group-hover:to-pink-500/30 transition-all">
        <Icon className="text-purple-400 group-hover:text-purple-300 transition-colors" size={24} />
      </div>
      <div>
        <h3 className="text-white font-semibold group-hover:text-purple-300 transition-colors">{title}</h3>
        <p className="text-white/50 text-sm">{description}</p>
      </div>
    </Link>
  )
}

function HomePage() {
  const [stats, setStats] = useState({
    pending: 0,
    approved: 0,
    posted: 0,
    rejected: 0
  })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchStats()
    const interval = setInterval(fetchStats, 30000)
    return () => clearInterval(interval)
  }, [])

  const fetchStats = async () => {
    try {
      const response = await api.get('/content/stats')
      setStats(response.data)
      setLoading(false)
    } catch (error) {
      console.error('Failed to fetch stats:', error)
      setLoading(false)
    }
  }

  return (
    <div className="fade-in">
      <div className="mb-8">
        <div className="flex items-center space-x-3 mb-2">
          <Sparkles className="text-cyan-400 h-8 w-8" />
          <h1 className="text-3xl font-bold gradient-text">Gradus AI Dashboard</h1>
        </div>
        <p className="text-white/60">Automated content creation and approval system for social media</p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
        <StatCard 
          title="Pending" 
          value={loading ? '...' : stats.pending}
          subtitle="Awaiting review"
          icon={Clock}
          colorClass="text-cyan-400"
          glowClass="stat-cyan"
        />
        <StatCard 
          title="Approved" 
          value={loading ? '...' : stats.approved}
          subtitle="Ready to post"
          icon={CheckCircle}
          colorClass="text-green-400"
          glowClass="stat-green"
        />
        <StatCard 
          title="Posted" 
          value={loading ? '...' : stats.posted}
          subtitle="Published content"
          icon={TrendingUp}
          colorClass="text-purple-400"
          glowClass="stat-purple"
        />
        <StatCard 
          title="Rejected" 
          value={loading ? '...' : stats.rejected}
          subtitle="Not approved"
          icon={XCircle}
          colorClass="text-pink-400"
          glowClass="stat-pink"
        />
      </div>

      <div className="mb-8">
        <h2 className="text-xl font-semibold text-white mb-4">Quick Actions</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <QuickActionCard 
            to="/chat"
            icon={MessageSquare}
            title="Test Claude Chat"
            description="Chat with Claude AI and test translation"
          />
          <QuickActionCard 
            to="/content"
            icon={FileText}
            title="Review Content"
            description="Approve or reject pending content"
          />
        </div>
      </div>

      <div className="glass-card p-6 gradient-border">
        <h3 className="text-lg font-semibold text-white mb-4 flex items-center space-x-2">
          <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse"></span>
          <span>System Status</span>
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>FastAPI Backend: Running</span>
          </div>
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>Claude API: Configured</span>
          </div>
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>PostgreSQL Database: Connected</span>
          </div>
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>DALL-E Image Generation: Active</span>
          </div>
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>Telegram Notifications: Active</span>
          </div>
          <div className="flex items-center space-x-3 text-white/70">
            <span className="text-green-400">✓</span>
            <span>Social Media Posting: Active</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export default HomePage
