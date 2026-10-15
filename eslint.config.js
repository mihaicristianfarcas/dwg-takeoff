// Lint for the web UI: plain ES modules in the browser, no build step.
import js from "@eslint/js";
import globals from "globals";

export default [
  js.configs.recommended,
  {
    files: ["src/dwg_takeoff/web/static/**/*.js"],
    languageOptions: { ecmaVersion: 2024, sourceType: "module", globals: globals.browser },
    rules: {
      "no-unused-vars": ["error", { args: "none", caughtErrors: "none" }],
      "no-empty": ["error", { allowEmptyCatch: true }],
    },
  },
];
