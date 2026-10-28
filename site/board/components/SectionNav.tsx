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
 *
 * At phone widths the bar also gets out of the reader's
 * way: it translates up out of view while the reader
 * scrolls down through content, and returns on any scroll
 * up, near the top of the page, while focus is inside it,
 * and for a beat after one of its own links is used, so an
 * anchor landing is never measured against a moving bar.
 * A sticky bar the reader cannot dismiss otherwise sits on
 * the top band of every chart they scroll to. The transform
 * changes no layout, so the spy, the landings, and the
 * desktop bar are untouched. On the phone the spy also
 * scrolls the strip itself, so the active link is never
 * the one cut off at the strip's edge.
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
      /* Phone: keep the active link inside the strip. The
       * strip is the only horizontal scroller, so following
       * the spy horizontally costs the page nothing. */
      if (id && window.matchMedia("(max-width: 760px)").matches) {
        const a = links.get(id);
        const inner = nav.querySelector<HTMLElement>(".section-nav-inner");
        if (a && inner) {
          const target = Math.max(0, a.offsetLeft - inner.offsetLeft - 8);
          if (Math.abs(inner.scrollLeft - target) > 4) {
            const reduce = window.matchMedia(
              "(prefers-reduced-motion: reduce)",
            ).matches;
            inner.scrollTo({
              left: target,
              behavior: reduce ? "auto" : "smooth",
            });
          }
        }
      }
    };
    /* The strip's end state, for the overflow cue in the
     * stylesheet: the cue shows while more strip is off the
     * right edge and clears once the reader has scrolled the
     * strip itself to its end (cycle 7, C7-R01). */
    const inner = nav.querySelector<HTMLElement>(".section-nav-inner");
    const markEnd = () => {
      if (!inner) return;
      nav.classList.toggle(
        "nav-at-end",
        inner.scrollLeft + inner.clientWidth >= inner.scrollWidth - 2,
      );
    };
    if (inner) {
      inner.addEventListener("scroll", markEnd, { passive: true });
      markEnd();
    }
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
    return () => {
      observer.disconnect();
      if (inner) inner.removeEventListener("scroll", markEnd);
    };
  }, []);

  /* Phone only: the bar steps aside while the reader
   * scrolls down, per the note at the top of this file.
   * Class toggles on the nav element itself, so no React
   * render rides the scroll events. */
  useEffect(() => {
    const nav = navRef.current;
    if (!nav) return;
    const mq = window.matchMedia("(max-width: 760px)");
    let refY = window.scrollY;
    let anchorAt = 0;
    let focusInside = false;
    const show = () => nav.classList.remove("nav-hidden");
    const onScroll = () => {
      const y = window.scrollY;
      /* Displacement is measured from the last point where a
       * threshold tripped, so a slow scroll in small steps
       * still accumulates toward the reveal and hide points
       * instead of resetting on every event. */
      const dy = y - refY;
      if (!mq.matches || focusInside) {
        refY = y;
        show();
        return;
      }
      if (Date.now() - anchorAt < 1200) {
        /* An anchor jump is still landing: never measure its
         * displacement against the pre-tap position, and take
         * the landing position as the reference for what
         * follows (cycle 7, RT-08). */
        show();
        refY = y;
        return;
      }
      if (y < 120 || dy < -4) {
        show();
        refY = y;
      } else if (dy > 6 && y > 240) {
        nav.classList.add("nav-hidden");
        refY = y;
      }
    };
    const onClick = (e: Event) => {
      const a = (e.target as HTMLElement).closest("a");
      if (a) {
        anchorAt = Date.now();
        show();
        /* A pointer or touch activation leaves the link focused
         * on Android Chrome for the rest of the session, and the
         * focus guard would then pin the bar open over every
         * section the reader scrolls to. Drop the focus for
         * pointer activations (detail above 0); a keyboard
         * activation reports detail 0 and keeps its focus, which
         * is the case the guard exists for (cycle 7, RT-06). */
        if ((e as MouseEvent).detail > 0) a.blur();
      }
    };
    const onFocusIn = () => {
      focusInside = true;
      show();
    };
    const onFocusOut = (e: FocusEvent) => {
      /* The guard clears only when focus actually leaves the
       * bar, so moving between its links cannot drop it
       * (cycle 7, RT-06). */
      if (!nav.contains(e.relatedTarget as Node | null)) {
        focusInside = false;
      }
    };
    window.addEventListener("scroll", onScroll, { passive: true });
    nav.addEventListener("click", onClick);
    nav.addEventListener("focusin", onFocusIn);
    nav.addEventListener("focusout", onFocusOut);
    return () => {
      window.removeEventListener("scroll", onScroll);
      nav.removeEventListener("click", onClick);
      nav.removeEventListener("focusin", onFocusIn);
      nav.removeEventListener("focusout", onFocusOut);
    };
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
