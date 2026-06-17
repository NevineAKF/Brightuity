import React from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { SessionProvider } from './context/SessionContext.jsx'
import Login     from './pages/Login.jsx'
import Dashboard from './pages/Dashboard.jsx'
import BandRoom  from './pages/BandRoom.jsx'
import Review    from './pages/Review.jsx'

export default function App() {
  return (
    <SessionProvider>
      <BrowserRouter>
        <Routes>
          <Route path="/"           element={<Navigate to="/login" replace />} />
          <Route path="/login"      element={<Login />} />
          <Route path="/dashboard"  element={<Dashboard />} />
          <Route path="/room/:id"   element={<BandRoom />} />
          <Route path="/review/:id" element={<Review />} />
        </Routes>
      </BrowserRouter>
    </SessionProvider>
  )
}
