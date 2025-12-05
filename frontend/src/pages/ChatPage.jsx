import { useState } from 'react'
import { Send, Languages, Sparkles } from 'lucide-react'
import axios from 'axios'
import { API_URL } from '../lib/api'

function ChatPage() {
  const [message, setMessage] = useState('')
  const [textToTranslate, setTextToTranslate] = useState('')
  const [chatResponse, setChatResponse] = useState('')
  const [translation, setTranslation] = useState('')
  const [loading, setLoading] = useState(false)

  const handleChat = async (e) => {
    e.preventDefault()
    if (!message.trim()) return

    setLoading(true)
    try {
      const response = await axios.post(`${API_URL}/chat`, {
        message: message
      })
      setChatResponse(response.data.response)
    } catch (error) {
      setChatResponse(`Error: ${error.response?.data?.detail || error.message}`)
    }
    setLoading(false)
  }

  const handleTranslate = async (e) => {
    e.preventDefault()
    if (!textToTranslate.trim()) return

    setLoading(true)
    try {
      const response = await axios.post(`${API_URL}/translate`, {
        text: textToTranslate
      })
      setTranslation(response.data.translation)
    } catch (error) {
      setTranslation(`Error: ${error.response?.data?.detail || error.message}`)
    }
    setLoading(false)
  }

  return (
    <div className="fade-in">
      <div className="flex items-center space-x-3 mb-6">
        <Sparkles className="text-cyan-400 h-8 w-8" />
        <h1 className="text-3xl font-bold gradient-text">Chat & Translation</h1>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="glass-card p-6">
          <div className="flex items-center space-x-2 mb-4">
            <div className="p-2 rounded-lg bg-purple-500/20">
              <Send className="text-purple-400" size={20} />
            </div>
            <h2 className="text-xl font-semibold text-white">Chat with Claude</h2>
          </div>

          <form onSubmit={handleChat} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">
                Your Message
              </label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-white/40 focus:ring-2 focus:ring-purple-500/50 focus:border-purple-500/50 transition-all"
                rows="4"
                placeholder="Type your message here..."
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Processing...' : 'Send Message'}
            </button>
          </form>

          {chatResponse && (
            <div className="mt-4 p-4 bg-white/5 border border-white/10 rounded-xl">
              <p className="text-sm font-medium text-white/70 mb-2">Response:</p>
              <p className="text-white whitespace-pre-wrap">{chatResponse}</p>
            </div>
          )}
        </div>

        <div className="glass-card p-6">
          <div className="flex items-center space-x-2 mb-4">
            <div className="p-2 rounded-lg bg-cyan-500/20">
              <Languages className="text-cyan-400" size={20} />
            </div>
            <h2 className="text-xl font-semibold text-white">English → Ukrainian</h2>
          </div>

          <form onSubmit={handleTranslate} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-white/70 mb-2">
                English Text
              </label>
              <textarea
                value={textToTranslate}
                onChange={(e) => setTextToTranslate(e.target.value)}
                className="w-full px-4 py-3 bg-white/5 border border-white/10 rounded-xl text-white placeholder-white/40 focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500/50 transition-all"
                rows="4"
                placeholder="Enter English text to translate..."
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full py-3 px-6 bg-gradient-to-r from-cyan-500/80 to-purple-500/80 hover:from-cyan-500 hover:to-purple-500 text-white font-medium rounded-xl border border-white/20 transition-all duration-300 hover:transform hover:-translate-y-0.5 hover:shadow-lg hover:shadow-cyan-500/25 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? 'Translating...' : 'Translate to Ukrainian'}
            </button>
          </form>

          {translation && (
            <div className="mt-4 p-4 bg-cyan-500/10 border border-cyan-500/20 rounded-xl">
              <p className="text-sm font-medium text-cyan-400 mb-2">Ukrainian Translation:</p>
              <p className="text-white whitespace-pre-wrap text-lg">{translation}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatPage
