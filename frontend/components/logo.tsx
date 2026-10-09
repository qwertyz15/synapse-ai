import { useId } from "react";

/** The Synapse mark: one axon branching into three terminals, each firing across a cleft. */
export function SynapseLogo({ className }: { className?: string }) {
  const gradient = useId();
  return (
    <svg viewBox="0 0 64 64" fill="none" aria-hidden className={className}>
      <defs>
        <linearGradient id={gradient} x1="0" y1="0" x2="64" y2="64" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#7c3aed" />
          <stop offset=".55" stopColor="#4f46e5" />
          <stop offset="1" stopColor="#0891b2" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="15" fill={`url(#${gradient})`} />
      <g stroke="#fff" strokeLinecap="round" strokeLinejoin="round">
        <path d="M6 32H18" strokeWidth="3.5" />
        <path d="M12 32L8 25M12 32L8 39" strokeWidth="2" />
        <path d="M18 32C23 32 23 20 27.5 20M18 32H29.5M18 32C23 32 23 44 27.5 44" strokeWidth="2.6" />
        <path
          d="M35.5 15.3A7 7 0 0 1 35.5 24.7M37.5 27.3A7 7 0 0 1 37.5 36.7M35.5 39.3A7 7 0 0 1 35.5 48.7"
          strokeWidth="2.6"
        />
        <path d="M37.8 20C44 20 44 32 48 32M39.8 32H58M37.8 44C44 44 44 32 48 32" strokeWidth="2.2" />
        <path d="M53 32L57 25M53 32L57 39" strokeWidth="1.8" />
      </g>
      <g fill="#fff">
        <circle cx="30.5" cy="20" r="3.6" />
        <circle cx="33" cy="32" r="3.6" />
        <circle cx="30.5" cy="44" r="3.6" />
      </g>
      <g fill="#67e8f9">
        <circle cx="35.2" cy="18.3" r=".9" />
        <circle cx="35.4" cy="21.6" r=".9" />
        <circle cx="37.7" cy="30.4" r=".9" />
        <circle cx="37.9" cy="33.7" r=".9" />
        <circle cx="35.2" cy="42.3" r=".9" />
        <circle cx="35.4" cy="45.6" r=".9" />
      </g>
    </svg>
  );
}
