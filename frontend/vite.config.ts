import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  // Relative Asset-Pfade statt absoluter: Unter Home-Assistant-Ingress läuft die
  // App nicht auf "/", sondern unter /api/hassio_ingress/<token>/. Ein absolutes
  // /assets/index-xyz.js würde der Browser gegen die HA-Wurzel auflösen — dort
  // liegt nichts, die Seite bliebe weiß. Aufgelöst werden die relativen Pfade
  // gegen das <base>-Tag, das das Backend in die index.html schreibt.
  base: './',
  plugins: [react()],
  server: {
    // Ohne feste Adresse bindet Vite unter macOS nur an IPv6 (::1) — dann
    // antwortet localhost:5173, http://127.0.0.1:5173 aber nicht.
    host: '127.0.0.1',
    port: 5173,
    // Lieber laut scheitern als still auf 5174 ausweichen: Ein Ausweichport
    // sieht aus, als wäre das Frontend gar nicht gestartet.
    strictPort: true,
    proxy: {
      // Alle /api-Aufrufe gehen an das FastAPI-Backend.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
})
