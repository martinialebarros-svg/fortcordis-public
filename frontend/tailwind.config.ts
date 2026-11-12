import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      colors: {
        cordis: {
          50: "#fff1f2",
          100: "#ffe4e6",
          200: "#fecdd3",
          500: "#e11d48",
          600: "#be123c",
          700: "#9f1239",
          900: "#4c0519",
        },
        vital: {
          50: "#ecfdf5",
          100: "#ccfbf1",
          200: "#99f6e4",
          500: "#14b8a6",
          600: "#0d9488",
          700: "#0f766e",
          900: "#134e4a",
        },
        ink: {
          50: "#f6f7f7",
          100: "#e5e9e7",
          200: "#cbd5d1",
          400: "#71817b",
          500: "#596861",
          600: "#44524c",
          700: "#303d38",
          900: "#17201d",
        },
        shell: "#f5f8f6",
        primary: {
          50: "#eff6ff",
          100: "#dbeafe",
          500: "#3b82f6",
          600: "#2563eb",
          700: "#1d4ed8",
          900: "#1e3a8a",
        }
      },
      boxShadow: {
        "fort-card": "0 1px 2px rgba(23, 32, 29, 0.06), 0 18px 34px rgba(23, 32, 29, 0.08)",
        "fort-soft": "0 10px 24px rgba(159, 18, 57, 0.12)",
        "fort-sidebar": "12px 0 30px rgba(23, 32, 29, 0.06)",
      },
    },
  },
  plugins: [],
};
export default config;
