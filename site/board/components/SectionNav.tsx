"use client";

import { useEffect, useRef } from "react";

/**
 * The sticky section bar (design system section 2.1). Eight
 * short labels, the design's ceiling, in the order the page
 * runs. Plain anchors, so every link works with JavaScript
 * off; the scrollspy is a progressive enhancement that marks
 * the section in view with an ink rule and aria-current. The
 * active styling never changes a box size (the rule is drawn
 * by a bottom border carried in both states), so the spy
 * cannot shift the layout it measures.
 */
export const NAV_ITEMS: Array<{ id: string; label: string }> = [
  { id: "ranking", label: "Ranking" },
  { id: "malformed", label: "Malformed" },
  { id: "families", label: "Families" },
  { id: "cost", label: "Cost" },
  { id: "calibration", label: "Calibration" },
  { id: "models", label: "Models" },
  { id: "compare", label: "Compare" },
  { id: "method", label: "Method" },
];

export default function SectionNav() {
  const navRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const links = new Map<string, HTMLAnchorElement>();
    nav.querySelectorAll<HTMLAnchorElement>("[data-nav-target]").forEach(
      (a) => {
        const t = a.getAttribute("data-nav-target");
        if (t) links.set(t, a);
      },
    );
    const setActive = (id: string | null) => {
      links.forEach((a, key) => {
        if (key === id) {
          a.classList.add("active");
          a.setAttribute("aria-current", "true");
        } else {
          a.classList.remove("active");
          a.removeAttribute("aria-current");
        }
      });
    };
    const visible = new Set<string>();
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) visible.add(entry.target.id);
          else visible.delete(entry.target.id);
        }
        const current = NAV_ITEMS.map((i) => i.id).find((id) =>
          visible.has(id),
        );
        if (current) setActive(current);
      },
      { rootMargin: "-12% 0px -70% 0px", threshold: 0 },
    );
    for (const item of NAV_ITEMS) {
      const el = document.getElementById(item.id);
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <nav className="section-nav" aria-label="Board sections" ref={navRef}>
      <div className="section-nav-inner">
        {NAV_ITEMS.map((item) => (
          <a
            key={item.id}
            className="section-nav-link"
            href={`#${item.id}`}
            data-nav-target={item.id}
          >
            {item.label}
          </a>
        ))}
      </div>
    </nav>
  );
}
