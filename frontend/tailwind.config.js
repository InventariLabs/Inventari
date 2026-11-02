/** @type {import('tailwindcss').Config} */
import animate from "tailwindcss-animate";

export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Plus Jakarta Sans", "system-ui", "-apple-system", "sans-serif"],
      },
      // shadow scale driven by the --shadow-* tokens so dark mode
      // can remap elevation (index.css .dark block).
      boxShadow: {
        sm: "var(--shadow-sm)",
        md: "var(--shadow-md)",
        lg: "var(--shadow-lg)",
        xl: "var(--shadow-xl)",
      },
      screens: {
        xs: "475px",
        "3xl": "1920px",
      },
      colors: {
        // === ACCENT (Success/Action - Emerald, CSS variable-driven) ===
        // === STATUS COLORS (CSS variable-driven for light shades, Tailwind defaults for 300+) ===
        red: {
          50: "rgb(var(--color-red-50) / <alpha-value>)",
          100: "rgb(var(--color-red-100) / <alpha-value>)",
          200: "rgb(var(--color-red-200) / <alpha-value>)",
        },
        amber: {
          50: "rgb(var(--color-amber-50) / <alpha-value>)",
          100: "rgb(var(--color-amber-100) / <alpha-value>)",
          200: "rgb(var(--color-amber-200) / <alpha-value>)",
        },
        blue: {
          50: "rgb(var(--color-blue-50) / <alpha-value>)",
          100: "rgb(var(--color-blue-100) / <alpha-value>)",
          200: "rgb(var(--color-blue-200) / <alpha-value>)",
        },
        // === SEMANTIC COLORS (Storage types — static, not theme-dependent) ===
        freezer: {
          light: "#dbeafe",
          DEFAULT: "#3b82f6",
          dark: "#1e40af",
        },
        fridge: {
          light: "#e0f2fe",
          DEFAULT: "#0ea5e9",
          dark: "#0369a1",
        },
        pantry: {
          light: "#fef3c7",
          DEFAULT: "#f59e0b",
          dark: "#d97706",
        },
        // === NEUTRALS (Zinc-based, CSS variable-driven) ===
        gray: {
          50: "rgb(var(--color-gray-50) / <alpha-value>)",
          100: "rgb(var(--color-gray-100) / <alpha-value>)",
          200: "rgb(var(--color-gray-200) / <alpha-value>)",
          300: "rgb(var(--color-gray-300) / <alpha-value>)",
          400: "rgb(var(--color-gray-400) / <alpha-value>)",
          500: "rgb(var(--color-gray-500) / <alpha-value>)",
          600: "rgb(var(--color-gray-600) / <alpha-value>)",
          700: "rgb(var(--color-gray-700) / <alpha-value>)",
          800: "rgb(var(--color-gray-800) / <alpha-value>)",
          900: "rgb(var(--color-gray-900) / <alpha-value>)",
          950: "rgb(var(--color-gray-950) / <alpha-value>)",
        },
        // The neutral segment of a composition bar (CompositionBar).
        bar: {
          ok: "rgb(var(--bar-ok) / <alpha-value>)",
          active: "rgb(var(--bar-active) / <alpha-value>)",
        },
        // === SURFACE TOKENS (semantic, theme-aware) ===
        surface: {
          DEFAULT: "rgb(var(--surface-bg) / <alpha-value>)",
          card: "rgb(var(--surface-card) / <alpha-value>)",
          raised: "rgb(var(--surface-raised) / <alpha-value>)",
          inset: "rgb(var(--surface-inset) / <alpha-value>)",
        },
        // === SHADCN SEMANTIC TOKENS (mapped from CSS variables) ===
        background: "rgb(var(--background) / <alpha-value>)",
        foreground: "rgb(var(--foreground) / <alpha-value>)",
        card: {
          DEFAULT: "rgb(var(--card) / <alpha-value>)",
          foreground: "rgb(var(--card-foreground) / <alpha-value>)",
        },
        popover: {
          DEFAULT: "rgb(var(--popover) / <alpha-value>)",
          foreground: "rgb(var(--popover-foreground) / <alpha-value>)",
        },
        primary: {
          DEFAULT: "rgb(var(--primary) / <alpha-value>)",
          foreground: "rgb(var(--primary-foreground) / <alpha-value>)",
          50: "rgb(var(--color-primary-50) / <alpha-value>)",
          100: "rgb(var(--color-primary-100) / <alpha-value>)",
          200: "rgb(var(--color-primary-200) / <alpha-value>)",
          300: "rgb(var(--color-primary-300) / <alpha-value>)",
          400: "rgb(var(--color-primary-400) / <alpha-value>)",
          500: "rgb(var(--color-primary-500) / <alpha-value>)",
          600: "rgb(var(--color-primary-600) / <alpha-value>)",
          700: "rgb(var(--color-primary-700) / <alpha-value>)",
          800: "rgb(var(--color-primary-800) / <alpha-value>)",
          900: "rgb(var(--color-primary-900) / <alpha-value>)",
          950: "rgb(var(--color-primary-950) / <alpha-value>)",
        },
        secondary: {
          DEFAULT: "rgb(var(--secondary) / <alpha-value>)",
          foreground: "rgb(var(--secondary-foreground) / <alpha-value>)",
        },
        muted: {
          DEFAULT: "rgb(var(--muted) / <alpha-value>)",
          foreground: "rgb(var(--muted-foreground) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          foreground: "rgb(var(--accent-foreground) / <alpha-value>)",
          50: "rgb(var(--color-accent-50) / <alpha-value>)",
          100: "rgb(var(--color-accent-100) / <alpha-value>)",
          200: "rgb(var(--color-accent-200) / <alpha-value>)",
          300: "rgb(var(--color-accent-300) / <alpha-value>)",
          400: "rgb(var(--color-accent-400) / <alpha-value>)",
          500: "rgb(var(--color-accent-500) / <alpha-value>)",
          600: "rgb(var(--color-accent-600) / <alpha-value>)",
          700: "rgb(var(--color-accent-700) / <alpha-value>)",
          800: "rgb(var(--color-accent-800) / <alpha-value>)",
          900: "rgb(var(--color-accent-900) / <alpha-value>)",
        },
        success: {
          50: "rgb(var(--color-success-50) / <alpha-value>)",
          100: "rgb(var(--color-success-100) / <alpha-value>)",
          200: "rgb(var(--color-success-200) / <alpha-value>)",
          300: "rgb(var(--color-success-300) / <alpha-value>)",
          400: "rgb(var(--color-success-400) / <alpha-value>)",
          500: "rgb(var(--color-success-500) / <alpha-value>)",
          600: "rgb(var(--color-success-600) / <alpha-value>)",
          700: "rgb(var(--color-success-700) / <alpha-value>)",
          800: "rgb(var(--color-success-800) / <alpha-value>)",
          900: "rgb(var(--color-success-900) / <alpha-value>)",
        },
        destructive: {
          DEFAULT: "rgb(var(--destructive) / <alpha-value>)",
          foreground: "rgb(var(--destructive-foreground) / <alpha-value>)",
        },
        input: "rgb(var(--input) / <alpha-value>)",
        ring: "rgb(var(--ring) / <alpha-value>)",
        // The hairline colour, reachable as a background too. It lived only
        // under `borderColor`, so every `bg-border` divider the guidelines
        // ask for — 16 of them, from ActionMenu to the approval stepper —
        // compiled to nothing and rendered transparent.
        border: "rgb(var(--border-default) / <alpha-value>)",
      },
      textColor: {
        on: {
          DEFAULT: "rgb(var(--text-primary) / <alpha-value>)",
          secondary: "rgb(var(--text-secondary) / <alpha-value>)",
          muted: "rgb(var(--text-muted) / <alpha-value>)",
          // Text on a status tint (`bg-red-50`, `bg-success-50`, …). Theme-aware
          // — see the STATUS FOREGROUNDS block in index.css.
          success: "rgb(var(--on-success) / <alpha-value>)",
          danger: "rgb(var(--on-danger) / <alpha-value>)",
          warning: "rgb(var(--on-warning) / <alpha-value>)",
          info: "rgb(var(--on-info) / <alpha-value>)",
          // Brand-coloured text on a card. Light mode has no value of its own
          // and falls back to the ramp's 700, so it follows a profile palette.
          primary:
            "rgb(var(--on-primary, var(--color-primary-700)) / <alpha-value>)",
        },
      },
      borderColor: {
        border: "rgb(var(--border-default) / <alpha-value>)",
        input: "rgb(var(--input) / <alpha-value>)",
      },
      ringColor: {
        ring: "rgb(var(--ring) / <alpha-value>)",
      },
      ringOffsetColor: {
        background: "rgb(var(--background) / <alpha-value>)",
      },
      animation: {
        "scan-line": "scan-line 2s ease-in-out infinite",
        "scan-line-smooth": "scan-line-smooth 3s ease-in-out infinite",
      },
      keyframes: {
        "scan-line": {
          "0%, 100%": { transform: "translateY(0)" },
          "50%": { transform: "translateY(250px)" },
        },
        "scan-line-smooth": {
          "0%, 100%": { transform: "translateY(0)", opacity: "0.4" },
          "50%": { transform: "translateY(280px)", opacity: "1" },
        },
      },
    },
  },
  plugins: [animate],
};
