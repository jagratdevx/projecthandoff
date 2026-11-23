/** @type {import('tailwindcss').Config} */
export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "Roboto",
          "Helvetica Neue",
          "sans-serif",
        ],
      },
      colors: {
        // Calm evergreen accent. Deliberately desaturated so it reads as a
        // product colour rather than a default template purple.
        brand: {
          50: "#eef7f4",
          100: "#d5ece5",
          200: "#acd9cc",
          300: "#7abfae",
          400: "#489f8b",
          500: "#2b836f",
          600: "#1d6b5a",
          700: "#185647",
          800: "#16463b",
          900: "#143a32",
          950: "#08211c",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(28, 25, 23, 0.04), 0 1px 3px rgba(28, 25, 23, 0.03)",
        "card-hover": "0 10px 30px -12px rgba(28, 25, 23, 0.18), 0 2px 6px rgba(28, 25, 23, 0.04)",
        header: "0 1px 0 rgba(28, 25, 23, 0.04)",
      },
    },
  },
  plugins: [],
};
