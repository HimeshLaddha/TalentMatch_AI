import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./src/pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        background: "var(--background)",
        foreground: "var(--foreground)",
        tm: {
          border: "var(--tm-border)",
          surface: "var(--tm-surface)",
          text: "var(--tm-text)",
          muted: "var(--tm-muted)",
          accent: "var(--tm-accent)",
          success: "var(--tm-success)",
          warning: "var(--tm-warning)",
        }
      },
    },
  },
  plugins: [],
};
export default config;
