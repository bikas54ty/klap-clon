/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: { ink: '#0b0b12', card: '#14141f', violet: '#7c3aed' },
    },
  },
  plugins: [],
}
