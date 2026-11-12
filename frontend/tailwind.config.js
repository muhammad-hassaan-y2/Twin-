/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        paypal: {
          blue: '#0070ba',
          dark: '#003087',
          light: '#0079C1',
          accent: '#253B80',
        }
      }
    },
  },
  plugins: [],
}
