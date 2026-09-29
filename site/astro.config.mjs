import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  site: 'https://peiratrial.dev',
  // Keep double hyphens in CLI flags verbatim; smartypants would turn
  // `--flag` into an em dash, which public copy forbids.
  markdown: { smartypants: false },
});
