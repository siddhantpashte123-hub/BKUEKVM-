/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // BLUEKVM PANNEL — strict black + electric blue system
        black: '#000000',
        panel: '#080808',
        sidebar: '#050505',
        card: '#0D0D0D',
        input: '#111111',
        primary: '#0066FF',
        electric: '#008CFF',
        muted: '#A1A1AA',
        line: '#222222',
        success: '#22C55E',
        warning: '#F59E0B',
        danger: '#EF4444',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        glow: '0 0 0 1px rgba(0,102,255,0.35), 0 0 24px -6px rgba(0,140,255,0.45)',
        card: '0 1px 0 0 rgba(255,255,255,0.03) inset, 0 8px 24px -16px rgba(0,0,0,0.8)',
      },
      keyframes: {
        'fade-in': {
          '0%': { opacity: '0', transform: 'translateY(4px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
        pulseglow: {
          '0%, 100%': { opacity: '1' },
          '50%': { opacity: '0.45' },
        },
      },
      animation: {
        'fade-in': 'fade-in 0.25s ease-out',
        pulseglow: 'pulseglow 1.6s ease-in-out infinite',
      },
    },
  },
  plugins: [],
}
