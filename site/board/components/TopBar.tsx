"use client";

import { useEffect, useState } from "react";

/**
 * The top bar, in the pattern of the Maidan landing bar
 * (web/landing/src/styles.css, .top and .top.scrolled).
 * Transparent over the first screen; once the page scrolls it
 * frosts, backdrop blur and saturate over a hairline bottom
 * edge, and it sticks while the scenes pass under it. The
 * links stand in page order, each a 44px target. The frost
 * transition is a color change at 300ms, inside the motion
 * budget, and the reduced motion branch in the stylesheet
 * removes it.
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
          <rect width="64" height="64" rx="12" fill="#0A0C0F" />
          <rect x="14" y="34" width="9" height="16" fill="#E9EEF3" />
          <rect x="27" y="24" width="9" height="26" fill="#E9EEF3" />
          <rect x="40" y="14" width="9" height="36" fill="#2FBF71" />
        </svg>
        <span className="brand-name">peira</span>
      </a>
      <nav className="mastnav" aria-label="Page">
        <a href="#results">Results</a>
        <a href="#explorer">Explorer</a>
        <a href="#findings">Findings</a>
        <a href="#method">Method</a>
        <a href="/payload.json">Payload</a>
      </nav>
    </header>
  );
}
