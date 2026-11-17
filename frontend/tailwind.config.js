/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      // BLUEKVM PANEL — minimalist dark palette. Flat, clean, no neon.
      colors: {
        transparent: 'transparent',
        current: 'currentColor',
        main: 'var(--bg-main)',
        sidebar: 'var(--bg-sidebar)',
        card: 'var(--bg-card)',
        border: 'var(--border-color)',
        text: {
          primary: 'var(--text-primary)',
          secondary: 'var(--text-secondary)',
          muted: 'var(--text-muted)',
        },
        accent: {
          white: 'var(--accent-white)',
        },
        // Used only for primary-button text (white button, black text).
        black: '#000000',
      },
      fontFamily: {
        sans: [
          'Inter',
          'ui-sans-serif',
          'system-ui',
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: [
          'JetBrains Mono',
          'ui-monospace',
          'SFMono-Regular',
          'Menlo',
          'Monaco',
          'Consolas',
          'monospace',
        ],
      },
      borderRadius: {
        DEFAULT: '8px',
        sm: '6px',
        md: '6px',
        lg: '8px',
      },
      boxShadow: {
        soft: '0 4px 6px rgba(0, 0, 0, 0.3)',
      },
    },
  },
  plugins: [],
};
