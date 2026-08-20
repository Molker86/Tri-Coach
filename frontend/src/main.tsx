import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App'
import { AuthProvider } from './auth/AuthContext'
import { BASE_PATH } from './basePath'
import { beobachteSystemfarbe } from './theme'
import './styles.css'

// Solange „System" gewählt ist, folgt die App der Systemeinstellung — auch
// wenn das Telefon abends von selbst umschaltet. Hier und nicht in einem
// `useEffect`: Der Beobachter lebt so lange wie die Seite, und im StrictMode
// liefe er sonst zweimal an.
beobachteSystemfarbe()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter basename={BASE_PATH || '/'}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
