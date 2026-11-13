import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Work at /sdu-utils/cv-maker/ and on custom Pages domains alike.
  base: "./",
  plugins: [react()],
});
