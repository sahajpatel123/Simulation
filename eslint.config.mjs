import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    ".next.nosync/**",
    "src/.next/**",
    "src/.next.nosync/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    "node_modules/**",
    "node_modules 2/**",
    ".claude/**",
    // Fallback source tree is not part of the active Next.js app.
    "Lovable/**",
    // Python backend + any venv (never lint third-party JS)
    "thecee-backend/**",
    "backend/app/**",
    ".venv/**",
    ".venv2/**",
    "**/venv/**",
    "**/__pycache__/**",
    "coverage/**",
  ]),
  // React Compiler rules from eslint-plugin-react-hooks: many false positives for
  // react-hook-form, syncing fetched data into local state, and canvas-heavy demos.
    {
    rules: {
      "react-hooks/refs": "off",
      "react-hooks/set-state-in-effect": "off",
      "react-hooks/purity": "off",
      "react-hooks/unsupported-syntax": "off",
      "react-hooks/incompatible-library": "off",
    },
  },
]);

export default eslintConfig;
