import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import './index.css'
import Shell from './components/Shell'
import Home from './pages/Home'
import BriefPage from './pages/BriefPage'
import About from './pages/About'
import ScenarioPage from './pages/ScenarioPage'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <Routes>
        <Route element={<Shell />}>
          <Route path="/" element={<Home />} />
          <Route path="/b/:key" element={<BriefPage />} />
          <Route path="/what-if/:key" element={<ScenarioPage />} />
          <Route path="/about" element={<About />} />
        </Route>
      </Routes>
    </BrowserRouter>
  </StrictMode>,
)
