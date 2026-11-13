import type { Metadata } from "next";

/**
 * The doorway for an address the board does not hold. Until
 * iteration 11 the framework default stood here, a bare 404 with
 * no name of its own and no way onward but the browser's back
 * control. This page names itself, states where the board stands,
 * and carries the reader there, in the board's own grammar. The
 * borrowed property is Maidan's error discipline, state stated as
 * words and a route onward on every surface.
 */

export const metadata: Metadata = {
  title: "Page not found · Peira decision robustness board",
};

export default function NotFound() {
  return (
    <main className="notfound">
      <p className="eyebrow">
        <span className="eno">404</span> · Not found
      </p>
      <h1 className="notfound-title">Nothing at this address</h1>
      <p className="notfound-lede">
        The board stands at one address, and every result&rsquo;s
        reading lives on it. This address is not one of them.
      </p>
      <p className="notfound-action">
        <a href="/">Back to the board</a>
      </p>
    </main>
  );
}
