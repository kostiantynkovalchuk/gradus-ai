import { useState } from 'react'
import { Send, Languages } from 'lucide-react'
import axios from 'axios'

const API_URL = window.location.origin.replace(':5000', ':8000')

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
    <div>
      <h1 className="text-3xl font-bold text-gray-900 mb-6">Chat & Translation</h1>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center space-x-2 mb-4">
            <Send className="text-purple-600" />
            <h2 className="text-xl font-semibold">Chat with Claude</h2>
          </div>

          <form onSubmit={handleChat} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                Your Message
              </label>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                rows="4"
                placeholder="Type your message here..."
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-purple-600 text-white py-2 px-4 rounded-lg hover:bg-purple-700 disabled:bg-gray-400 transition"
            >
              {loading ? 'Processing...' : 'Send Message'}
            </button>
          </form>

          {chatResponse && (
            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <p className="text-sm font-medium text-gray-700 mb-2">Response:</p>
              <p className="text-gray-900 whitespace-pre-wrap">{chatResponse}</p>
            </div>
          )}
        </div>

        <div className="bg-white rounded-lg shadow p-6">
          <div className="flex items-center space-x-2 mb-4">
            <Languages className="text-purple-600" />
            <h2 className="text-xl font-semibold">English → Ukrainian</h2>
          </div>

          <form onSubmit={handleTranslate} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-2">
                English Text
              </label>
              <textarea
                value={textToTranslate}
                onChange={(e) => setTextToTranslate(e.target.value)}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500 focus:border-transparent"
                rows="4"
                placeholder="Enter English text to translate..."
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="w-full bg-purple-600 text-white py-2 px-4 rounded-lg hover:bg-purple-700 disabled:bg-gray-400 transition"
            >
              {loading ? 'Translating...' : 'Translate to Ukrainian'}
            </button>
          </form>

          {translation && (
            <div className="mt-4 p-4 bg-gray-50 rounded-lg">
              <p className="text-sm font-medium text-gray-700 mb-2">Ukrainian Translation:</p>
              <p className="text-gray-900 whitespace-pre-wrap text-lg">{translation}</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default ChatPage
