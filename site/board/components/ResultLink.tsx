import { useState } from "react";
import "./result-link.css";

export default function ResultLink({ href }: { href: string }) {
  const [status, setStatus] = useState("");

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(new URL(href, window.location.origin).href);
      setStatus("Link copied.");
    } catch {
      setStatus("Use the permalink’s context menu to copy the link.");
    }
  }

  return (
    <div className="result-link">
      <a href={href}>Result permalink</a>
      <button type="button" className="ghostbtn" onClick={copyLink}>Copy link</button>
      <span role="status">{status}</span>
    </div>
  );
}
