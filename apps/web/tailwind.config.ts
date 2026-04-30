import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./app/**/*.{ts,tsx}", "./components/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#2d2a26",
        panel: "#f0eee8",
        line: "#e3e1db",
        accent: "#8b8680",
        warning: "#c65746"
      }
    }
  },
  plugins: [],
};

export default config;
