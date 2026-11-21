"use client";

import { useEffect, useRef } from "react";

// Parallel contours form a decorative field behind the benchmark. The plotted
// observations are drawn independently, inside the distribution figure.
const contours = Array.from({ length: 25 }, (_, i) => {
  const t = i / 24;
  return [
    `M -100 ${460 + t * 94}`,
    `C 124 ${508 + t * 82}, 238 ${362 + t * 86}, 460 ${435 + t * 70}`,
    `S 731 ${522 + t * 42}, 908 ${342 + t * 48}`,
    `S 1184 ${119 + t * 78}, 1550 ${80 + t * 76}`,
  ].join(" ");
});

export default function CoverField() {
  const field = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const node = field.current;
    const cover = node?.parentElement;
    if (!node || !cover) return;
    const motion = matchMedia("(prefers-reduced-motion: no-preference) and (hover: hover) and (pointer: fine)");
    const reset = () => {
      node.style.removeProperty("--field-x");
      node.style.removeProperty("--field-y");
    };
    const move = (event: PointerEvent) => {
      if (!motion.matches || event.pointerType === "touch") return;
      const box = cover.getBoundingClientRect();
      node.style.setProperty("--field-x", `${(event.clientX - box.left - box.width / 2) / box.width * 24}px`);
      node.style.setProperty("--field-y", `${(event.clientY - box.top - box.height / 2) / box.height * 16}px`);
    };
    cover.addEventListener("pointermove", move, { passive: true });
    cover.addEventListener("pointerleave", reset);
    motion.addEventListener("change", reset);
    return () => {
      cover.removeEventListener("pointermove", move);
      cover.removeEventListener("pointerleave", reset);
      motion.removeEventListener("change", reset);
    };
  }, []);

  return (
    <div className="cover-field" aria-hidden="true" ref={field}>
      <div className="field-plane">
        <svg viewBox="0 0 1440 580" preserveAspectRatio="none" focusable="false">
          <defs>
            <linearGradient id="contour-ink" gradientUnits="userSpaceOnUse" x1="0" x2="1440" y1="480" y2="100">
              <stop className="contour-cool" />
              <stop offset=".47" className="contour-blue" />
              <stop offset=".78" className="contour-violet" />
              <stop offset="1" className="contour-cool" />
            </linearGradient>
          </defs>
          <g fill="none" stroke="url(#contour-ink)" strokeWidth=".85">
            {contours.map(path => <path key={path} d={path} />)}
          </g>
        </svg>
      </div>
    </div>
  );
}
