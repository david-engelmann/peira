import { satteri } from '@astrojs/markdown-satteri';
import { defineConfig } from 'astro/config';

export default defineConfig({
  output: 'static',
  site: 'https://peiratrial.dev',
  // Preserve spaces between inline elements when compressing HTML.
  compressHTML: true,
  // Keep double hyphens and straight quotes verbatim in Markdown.
  markdown: { processor: satteri({ features: { smartPunctuation: false } }) },
});
