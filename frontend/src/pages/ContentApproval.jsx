import { useState, useEffect } from 'react'
import { CheckCircle, XCircle, Clock, Image } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import api from '../lib/api'

function MiniStatCard({ label, value, colorClass }) {
  return (
    <div className="glass-card p-4">
      <div className={`text-sm ${colorClass} opacity-70`}>{label}</div>
      <div className={`text-2xl font-bold ${colorClass}`}>{value}</div>
    </div>
  )
}

function ContentApproval() {
  const [pendingContent, setPendingContent] = useState([])
  const [stats, setStats] = useState({ pending: 0, approved: 0, posted: 0, rejected: 0 })
  const [loading, setLoading] = useState(true)
  const [imageVersions, setImageVersions] = useState({}) // Track cache-busting versions per article

  useEffect(() => {
    fetchData()
  }, [])

  const fetchData = async () => {
    try {
      const [contentRes, statsRes] = await Promise.all([
        api.get('/content/pending'),
        api.get('/content/stats')
      ])
      setPendingContent(contentRes.data)
      setStats(statsRes.data)
    } catch (error) {
      console.error('Error fetching data:', error)
    }
    setLoading(false)
  }

  const handleApprove = async (contentId) => {
    if (!window.confirm('Approve and schedule for posting?')) return
    
    try {
      const response = await api.post(`/content/${contentId}/approve`, {
        moderator: 'Admin',
        platforms: ['facebook', 'linkedin']
      })
      
      if (response.data.status === 'success' && response.data.fb_post_url) {
        alert(`Posted to Facebook!\n\n${response.data.fb_post_url}`)
      } else {
        alert('Content approved successfully!')
      }
      
      fetchData()
    } catch (error) {
      console.error('Error approving content:', error)
      alert('Failed to approve content')
    }
  }

  const handleReject = async (contentId) => {
    const reason = prompt('Reason for rejection:')
    if (!reason) return

    try {
      await api.post(`/content/${contentId}/reject`, {
        moderator: 'Admin',
        reason: reason
      })
      fetchData()
    } catch (error) {
      console.error('Error rejecting content:', error)
    }
  }

  const handleGenerateImage = async (contentId) => {
    try {
      console.log('Fetching image for content', contentId)
      const response = await api.post(`/admin/articles/${contentId}/fetch-image`)
      if (response.data.image_url) {
        alert('Image fetched from Unsplash!')
      }
      fetchData()
    } catch (error) {
      console.error('Error fetching image:', error)
      const message = error.response?.data?.detail || 'Failed to fetch image'
      alert(message)
    }
  }

  const handleFetchNewImage = async (contentId) => {
    try {
      console.log('Fetching new image for content', contentId)
      const response = await api.post(`/admin/articles/${contentId}/fetch-image`)
      
      if (response.data.image_url) {
        setImageVersions(prev => ({
          ...prev,
          [contentId]: Date.now()
        }))
        alert('New image fetched from Unsplash!')
      }
      
      fetchData()
    } catch (error) {
      console.error('Error fetching image:', error)
      const message = error.response?.data?.detail || 'Failed to fetch image'
      alert(message)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="text-white/60">Loading...</div>
      </div>
    )
  }

  return (
    <div className="fade-in">
      <div className="mb-6">
        <h1 className="text-3xl font-bold gradient-text">Content Approval</h1>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
        <MiniStatCard label="Pending" value={stats.pending} colorClass="text-yellow-400" />
        <MiniStatCard label="Approved" value={stats.approved} colorClass="text-green-400" />
        <MiniStatCard label="Posted" value={stats.posted} colorClass="text-cyan-400" />
        <MiniStatCard label="Rejected" value={stats.rejected} colorClass="text-pink-400" />
      </div>

      {pendingContent.length === 0 ? (
        <div className="glass-card p-12 text-center">
          <Clock className="mx-auto h-12 w-12 text-white/30 mb-4" />
          <p className="text-white/60 text-lg">No content pending approval</p>
          <p className="text-white/40 text-sm mt-2">New content from the news scraper will appear here</p>
        </div>
      ) : (
        <div className="space-y-6">
          {pendingContent.map((content) => (
            <div key={content.id} className="glass-card p-6">
              <div className="flex flex-col md:flex-row justify-between items-start gap-4 mb-4">
                <div className="flex-1">
                  <h3 className="text-xl font-bold text-white mb-2">
                    {content.translated_title || content.extra_metadata?.title || 'Untitled'}
                  </h3>
                  <p className="text-white/50 text-sm">Source: {content.source}</p>
                </div>
                <span className="px-4 py-1.5 bg-yellow-500/20 text-yellow-400 rounded-full text-sm font-medium border border-yellow-500/30">
                  Pending Review
                </span>
              </div>

              <div className="space-y-4 mb-6">
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm font-medium text-white/60 mb-2">Original Title (English):</p>
                    <div className="p-3 bg-white/5 border border-white/10 rounded-lg text-white/80 text-sm font-medium">
                      {content.extra_metadata?.title || 'No title'}
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-cyan-400/80 mb-2">Translated Title (Ukrainian):</p>
                    <div className="p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-lg text-white text-sm font-medium">
                      {content.translated_title || 'No translation'}
                    </div>
                  </div>
                </div>
                
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div>
                    <p className="text-sm font-medium text-white/60 mb-2">Original Content (English):</p>
                    <div className="p-3 bg-white/5 border border-white/10 rounded-lg text-white/70 text-sm max-h-48 overflow-y-auto prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown>{content.original_text || 'No content'}</ReactMarkdown>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm font-medium text-cyan-400/80 mb-2">Translated Content (Ukrainian):</p>
                    <div className="p-3 bg-cyan-500/10 border border-cyan-500/20 rounded-lg text-white text-sm max-h-48 overflow-y-auto prose prose-invert prose-sm max-w-none">
                      <ReactMarkdown>{content.translated_text || 'No translation'}</ReactMarkdown>
                    </div>
                  </div>
                </div>
              </div>

              {content.image_url ? (
                <div className="mb-6">
                  <h4 className="font-semibold text-white/80 mb-3 flex items-center space-x-2">
                    <Image size={16} className="text-purple-400" />
                    <span>Generated Image</span>
                  </h4>
                  <div className="bg-white/5 p-4 rounded-xl border border-white/10">
                    <img 
                      src={`/api/images/serve/${content.id}${imageVersions[content.id] ? `?v=${imageVersions[content.id]}` : ''}`} 
                      alt="Generated" 
                      className="w-full max-w-md rounded-lg shadow-2xl mb-3"
                      onError={(e) => {
                        e.target.onerror = null;
                        e.target.src = content.image_url;
                      }}
                    />
                    {content.image_prompt && (
                      <p className="text-xs text-white/40 italic mb-3">
                        Prompt: {content.image_prompt}
                      </p>
                    )}
                    <button
                      onClick={() => handleFetchNewImage(content.id)}
                      className="flex items-center space-x-2 text-sm bg-purple-500/20 text-purple-400 px-4 py-2 rounded-lg hover:bg-purple-500/30 border border-purple-500/30 transition-all"
                    >
                      <Image size={14} />
                      <span>Fetch New Image</span>
                    </button>
                  </div>
                </div>
              ) : (
                <div className="mb-6">
                  <button
                    onClick={() => handleGenerateImage(content.id)}
                    className="flex items-center space-x-2 bg-gradient-to-r from-purple-500/80 to-pink-500/80 hover:from-purple-500 hover:to-pink-500 text-white px-5 py-2.5 rounded-xl border border-white/20 transition-all duration-300 hover:transform hover:-translate-y-0.5"
                  >
                    <Image size={18} />
                    <span>Fetch Image</span>
                  </button>
                </div>
              )}

              <div className="flex flex-wrap gap-3">
                <button
                  onClick={() => handleApprove(content.id)}
                  className="flex items-center space-x-2 px-5 py-2.5 bg-green-500/20 text-green-400 rounded-xl hover:bg-green-500/30 border border-green-500/30 transition-all duration-300 hover:transform hover:-translate-y-0.5"
                >
                  <CheckCircle size={18} />
                  <span>Approve</span>
                </button>
                <button
                  onClick={() => handleReject(content.id)}
                  className="flex items-center space-x-2 px-5 py-2.5 bg-red-500/20 text-red-400 rounded-xl hover:bg-red-500/30 border border-red-500/30 transition-all duration-300 hover:transform hover:-translate-y-0.5"
                >
                  <XCircle size={18} />
                  <span>Reject</span>
                </button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default ContentApproval
