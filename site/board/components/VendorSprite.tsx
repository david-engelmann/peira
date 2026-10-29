import { LOGO_PATHS, type LogoSlug } from "@/lib/logoPaths";

/**
 * The vendor mark sprite: every maker's path defined once
 * per page as a symbol, and every chip on the board
 * references its symbol with <use> instead of repeating the
 * path data inline at each chip. Twenty-one marks serve
 * hundreds of chips; inlining the path at every chip cost
 * the page more transfer than everything else this cycle
 * added combined (PF-02). Each symbol's path keeps
 * fill="currentColor", which resolves in the referencing
 * chip's context, so a chip still paints in its own family
 * color. Rendered once by the root layout, so it serves the
 * board and the standalone model pages alike.
 */
export default function VendorSprite() {
  return (
    <svg
      aria-hidden="true"
      focusable="false"
      style={{
        position: "absolute",
        width: 0,
        height: 0,
        overflow: "hidden",
      }}
    >
      <defs>
        {(Object.keys(LOGO_PATHS) as LogoSlug[]).map((slug) => (
          <symbol key={slug} id={`vlogo-${slug}`} viewBox="0 0 24 24">
            <path d={LOGO_PATHS[slug]} fill="currentColor" />
          </symbol>
        ))}
      </defs>
    </svg>
  );
}
