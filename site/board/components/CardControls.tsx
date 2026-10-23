"use client";

/**
 * Expand all and collapse all for the model index (design
 * 2.2). A progressive enhancement only: the cards are native
 * details elements, so every card opens and closes without
 * JavaScript, and these buttons simply set the open property
 * on all of them at once.
 */
export default function CardControls() {
  const setAll = (open: boolean) => {
    document
      .querySelectorAll<HTMLDetailsElement>(
        '[data-section="models"] details.model-item',
      )
      .forEach((d) => {
        d.open = open;
      });
  };
  return (
    <div className="card-controls">
      <button type="button" onClick={() => setAll(true)}>
        Expand all
      </button>
      <button type="button" onClick={() => setAll(false)}>
        Collapse all
      </button>
    </div>
  );
}
