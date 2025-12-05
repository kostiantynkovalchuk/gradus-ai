import { BrowserRouter as Router, Routes, Route, Link, useLocation } from 'react-router-dom'
import { Home, MessageSquare, FileText, Sparkles } from 'lucide-react'
import HomePage from './pages/HomePage'
import ChatPage from './pages/ChatPage'
import ContentApproval from './pages/ContentApproval'

function NavLink({ to, icon: Icon, children }) {
  const location = useLocation()
  const isActive = location.pathname === to
  
  return (
    <Link 
      to={to} 
      className={`flex items-center space-x-2 px-4 py-2 rounded-lg transition-all duration-300 ${
        isActive 
          ? 'bg-white/10 text-white' 
          : 'text-white/70 hover:text-white hover:bg-white/5'
      }`}
    >
      <Icon size={18} />
      <span className="font-medium">{children}</span>
    </Link>
  )
}

function Navigation() {
  return (
    <nav className="glass sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-16">
          <Link to="/" className="flex items-center space-x-3 group">
            <div className="relative">
              <Sparkles className="h-8 w-8 text-cyan-400 group-hover:text-cyan-300 transition-colors" />
              <div className="absolute inset-0 blur-lg bg-cyan-400/30 group-hover:bg-cyan-300/40 transition-colors"></div>
            </div>
            <h1 className="text-xl font-bold gradient-text">Gradus AI</h1>
          </Link>
          
          <div className="hidden md:flex items-center space-x-2">
            <NavLink to="/" icon={Home}>Home</NavLink>
            <NavLink to="/chat" icon={MessageSquare}>Chat</NavLink>
            <NavLink to="/content" icon={FileText}>Content</NavLink>
          </div>

          <div className="md:hidden flex items-center space-x-4">
            <Link to="/" className="text-white/70 hover:text-white p-2">
              <Home size={20} />
            </Link>
            <Link to="/chat" className="text-white/70 hover:text-white p-2">
              <MessageSquare size={20} />
            </Link>
            <Link to="/content" className="text-white/70 hover:text-white p-2">
              <FileText size={20} />
            </Link>
          </div>
        </div>
      </div>
    </nav>
  )
}

function App() {
  return (
    <Router>
      <div className="min-h-screen">
        <Navigation />
        <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/chat" element={<ChatPage />} />
            <Route path="/content" element={<ContentApproval />} />
          </Routes>
        </main>
      </div>
    </Router>
  )
}

export default App
