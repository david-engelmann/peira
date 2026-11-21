"use client";

import { useEffect, useState } from "react";
import {
  applyThemePreference,
  readThemePreference,
  themeStorageKey,
  type ThemePreference,
} from "@/lib/theme";

function ThemeSelect() {
  const [preference, setPreference] = useState<ThemePreference>("system");

  useEffect(() => {
    setPreference(readThemePreference(document.documentElement.getAttribute("data-theme")));
    const syncPreference = (event: StorageEvent) => {
      if (event.key !== themeStorageKey && event.key !== null) return;
      const next = readThemePreference(event.newValue);
      applyThemePreference(next);
      setPreference(next);
    };
    window.addEventListener("storage", syncPreference);
    return () => window.removeEventListener("storage", syncPreference);
  }, []);

  return (
    <label className="theme-select" title="Color theme">
      <svg viewBox="0 0 20 20" width="17" height="17" fill="none" aria-hidden="true">
        <circle cx="10" cy="10" r="7.5" stroke="currentColor" strokeWidth="1.5" />
        <path d="M10 2.5a7.5 7.5 0 0 1 0 15Z" fill="currentColor" />
      </svg>
      <select
        aria-label="Color theme"
        value={preference}
        onChange={(event) => {
          const next = readThemePreference(event.currentTarget.value);
          applyThemePreference(next);
          setPreference(next);
          try {
            if (next === "system") localStorage.removeItem(themeStorageKey);
            else localStorage.setItem(themeStorageKey, next);
          } catch {
            // The current page can still change theme when storage is unavailable.
          }
        }}
      >
        <option value="system">System</option>
        <option value="light">Light</option>
        <option value="dark">Dark</option>
      </select>
    </label>
  );
}

/**
 * The top bar, in the pattern of the Maidan landing bar
 * (web/landing/src/styles.css, .top and .top.scrolled).
 * Transparent over the first screen; once the page scrolls it
 * frosts, backdrop blur and saturate over a hairline bottom
 * edge, and it sticks while the scenes pass under it. The
 * links stand in page order, each a 44px target. The frost
 * transition is a color change at the entrance duration
 * (--dur-enter, 280ms), the motion cap, and the reduced
 * motion branch in the stylesheet removes it.
 */
export default function TopBar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 8);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  return (
    <header className={`masthead${scrolled ? " scrolled" : ""}`}>
      <a className="brand" href="#top" aria-label="peira, back to the top">
        <svg viewBox="0 0 64 64" width="26" height="26" aria-hidden="true">
          <rect width="64" height="64" rx="10" fill="#0A0C0F" />
          <rect x="14" y="34" width="9" height="16" fill="#EEF2F6" />
          <rect x="27" y="24" width="9" height="26" fill="#EEF2F6" />
          <rect x="40" y="14" width="9" height="36" fill="#2FBF71" />
        </svg>
        <span className="brand-name">peira</span>
      </a>
      <nav className="mastnav" aria-label="Page">
        <a href="#results">Overview</a>
        <a href="#findings">Analysis</a>
        <a href="#explorer">Explorer</a>
        <a className="mastnav-tail" href="#method">Method</a>
        <a className="mastnav-tail" href="/payload.json">Data</a>
      </nav>
      <details className="mastmore">
        <summary>More</summary>
        <div
          className="mastmore-panel"
          onClick={(e) => {
            const details = e.currentTarget.closest("details");
            if (details) details.removeAttribute("open");
          }}
        >
          <a href="#method">Method</a>
          <a href="/payload.json">Data</a>
        </div>
      </details>
      <ThemeSelect />
    </header>
  );
}
