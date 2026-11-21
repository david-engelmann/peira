/** The masthead and social cards share the same lettering and proportions. */
export default function PeiraBrand({ symbol = "/icon.svg", ink = "currentColor", scale = 1 }: {
  symbol?: string;
  ink?: string;
  scale?: number;
}) {
  return (
    <span className="peira-signature" aria-hidden="true" style={{ display: "flex", alignItems: "center", gap: 9 * scale }}>
      <img src={symbol} width={38 * scale} height={38 * scale} alt="" />
      <svg width={118 * scale} height={27 * scale} viewBox="0 0 136 31" fill={ink} xmlns="http://www.w3.org/2000/svg">
        <g transform="translate(4 1) skewX(-7)" fillRule="evenodd">
          <path d="M0 0h15.5C23.4 0 27 3.9 27 10s-4.4 10.3-12.3 10.3H7v8H0zm7 6v8.4h7.8c3.3 0 5.1-1.5 5.1-4.2 0-2.8-1.8-4.2-5.1-4.2z" />
          <path d="M31 0h23l-1.7 6H38v5.1h13.7L50 16.8H38v5.4h16.3l-1.7 6.1H31z" />
          <path d="M59.8 0h7.1v28.3h-7.1z" />
          <path d="M73 0h15.4C96 0 100 3.4 100 9.6c0 4.9-2.7 8-7.1 9.3l8.1 9.4h-8.8l-7.1-8.6H80v8.6h-7zm7 6v7.8h8c3.2 0 4.8-1.4 4.8-4S91.1 6 88 6z" />
          <path transform="translate(6 0)" d="M112.3 0h8.4l6.8 28.3h-7.4l-1.2-5.6h-11.3l-3.1 5.6h-7.8zm3.5 7.2-5.2 10.1h7.3z" />
        </g>
      </svg>
    </span>
  );
}
