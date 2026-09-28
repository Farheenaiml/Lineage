/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        brand: "#3E503C",
        brandDark: "#26372A",
        ink: "#182421",
        muted: "#66716C",
        faint: "#8A948F",
        bg: "#F7F7F3",
        card: "#FFFFFF",
        soft: "#E8EEE6",
        border: "#DDE2DC",
        amber: "#F5E8C8",
        blue: "#E4ECF5",
        red: "#F3DFDC",
        success: "#5D765B",
      },
      fontFamily: {
        display: ["Georgia", "Times New Roman", "serif"],
        body: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["ui-monospace", "SFMono-Regular", "monospace"],
      },
      boxShadow: {
        soft: "0 8px 30px rgba(38,55,42,.06)",
        card: "0 2px 10px rgba(24,36,33,.04)",
      },
      borderRadius: {
        xl2: "20px",
      },
    },
  },
  plugins: [],
};
