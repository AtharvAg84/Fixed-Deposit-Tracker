import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  preview: {
    // allowedHosts: ['fd-tracker-frontend.onrender.com']
  }
})

// export default defineConfig({
//   plugins: [react()],
//   preview: {
//     allowedHosts: ['fd-tracker-frontend.onrender.com']
//   }
// })