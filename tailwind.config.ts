import type { Config } from "tailwindcss";

const config: Config = {
  darkMode: "class",
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        abyss: "#030407",
        panel: "#0a0b10",
        panelElevated: "#0e1017",
        borderFine: "#1f222d",
        neonGreen: "#4ade80",
        neonCyan: "#22d3ee",
        mustard: "#eab308"
      },
      fontFamily: {
        sans: ["var(--font-sans)", "Inter", "system-ui", "sans-serif"],
        mono: ["var(--font-mono)", "JetBrains Mono", "Fira Code", "monospace"]
      }
    }
  },
  plugins: []
};

export default config;
