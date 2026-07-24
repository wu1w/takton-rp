/* 细线 SVG 图标集（SF Symbols 气质，无 emoji） */
import React from "react";

type P = { size?: number; strokeWidth?: number };

function base(p: P, children: React.ReactNode) {
  const s = p.size ?? 22;
  return (
    <svg
      width={s}
      height={s}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={p.strokeWidth ?? 1.7}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {children}
    </svg>
  );
}

export const IconChat = (p: P) =>
  base(p, <path d="M20 12.5c0 4-3.8 7-8.5 7-1 0-2-.1-2.8-.4L4 20.5l1.2-3.5C4 15.8 3 14.3 3 12.5 3 8.5 6.8 5.5 11.5 5.5S20 8.5 20 12.5z" />);

export const IconSparkle = (p: P) =>
  base(p, <>
    <path d="M12 3.5l1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8 1.8-5z" />
    <path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7.7-2z" />
  </>);

export const IconGrid = (p: P) =>
  base(p, <>
    <rect x="4" y="4" width="7" height="7" rx="2" />
    <rect x="13" y="4" width="7" height="7" rx="2" />
    <rect x="4" y="13" width="7" height="7" rx="2" />
    <rect x="13" y="13" width="7" height="7" rx="2" />
  </>);

export const IconSliders = (p: P) =>
  base(p, <>
    <path d="M4 7h16M4 12h16M4 17h16" />
    <circle cx="15" cy="7" r="2.2" fill="currentColor" stroke="none" />
    <circle cx="9" cy="12" r="2.2" fill="currentColor" stroke="none" />
    <circle cx="17" cy="17" r="2.2" fill="currentColor" stroke="none" />
  </>);

export const IconPerson = (p: P) =>
  base(p, <>
    <circle cx="12" cy="8" r="4" />
    <path d="M4.5 20c1.4-3.4 4.2-5 7.5-5s6.1 1.6 7.5 5" />
  </>);

export const IconShield = (p: P) =>
  base(p, <>
    <path d="M12 3l7 3v5.2c0 4.3-3 7.6-7 9.8-4-2.2-7-5.5-7-9.8V6l7-3z" />
    <path d="M9 12l2 2 4-4" />
  </>);

export const IconBookmark = (p: P) =>
  base(p, <path d="M7 4h10a1 1 0 011 1v15l-6-4-6 4V5a1 1 0 011-1z" />);

export const IconHeart = (p: P) =>
  base(p, <path d="M12 20s-7.2-4.4-9.2-8.6C1.2 8 3.4 4.8 6.6 4.8c2 0 3.6 1 5.4 3 1.8-2 3.4-3 5.4-3 3.2 0 5.4 3.2 3.8 6.6C19.2 15.6 12 20 12 20z" />);

export const IconCheck = (p: P) =>
  base(p, <path d="M5 12.5l4.5 4.5L19 7.5" />);

export const IconAlert = (p: P) =>
  base(p, <>
    <path d="M12 8v5M12 16.5v.5" />
    <circle cx="12" cy="12" r="9" />
  </>);

export const IconCloud = (p: P) =>
  base(p, <path d="M7 18h9.5a4 4 0 0 0 .6-7.96A5.6 5.6 0 0 0 6 8.4 3.9 3.9 0 0 0 7 18z" />);

export const IconDoc = (p: P) =>
  base(p, <>
    <rect x="4" y="5" width="16" height="14" rx="2.5" />
    <path d="M8 9.5h8M8 13h5" />
  </>);

export const IconClock = (p: P) =>
  base(p, <>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 7.5V12l3.2 2" />
  </>);

export const IconPlane = (p: P) =>
  base(p, <path d="M21 4L3.5 11.2l5.8 2.3M21 4l-2.8 15-6.9-5.3M21 4L9.3 13.5v4.2l2.8-3.5" />);

export const IconWeChat = (p: P) =>
  base(p, <>
    <path d="M9.5 4C5.9 4 3 6.5 3 9.6c0 1.8 1 3.4 2.5 4.4L4.8 16l2.5-1.3c.7.2 1.4.3 2.2.3" />
    <path d="M14.5 9c3.6 0 6.5 2.5 6.5 5.6 0 1.8-1 3.4-2.5 4.4l.7 2-2.5-1.3c-.7.2-1.4.3-2.2.3-3.6 0-6.5-2.5-6.5-5.6S10.9 9 14.5 9z" />
  </>);

export const IconSpeaker = (p: P) =>
  base(p, <>
    <path d="M4 10v4h3.5L12 18V6l-4.5 4H4z" />
    <path d="M15.5 9.5a4 4 0 0 1 0 5M18 7.5a7.5 7.5 0 0 1 0 9" />
  </>);

export const IconFolder = (p: P) =>
  base(p, <path d="M3.5 7.5A2.5 2.5 0 0 1 6 5h4l2 2.5h6A2.5 2.5 0 0 1 20.5 10v7A2.5 2.5 0 0 1 18 19.5H6A2.5 2.5 0 0 1 3.5 17v-9.5z" />);

export const IconDownload = (p: P) =>
  base(p, <>
    <path d="M12 4v10M8 10.5l4 4 4-4" />
    <path d="M5 19h14" />
  </>);

export const IconCpu = (p: P) =>
  base(p, <>
    <rect x="5" y="5" width="14" height="14" rx="3" />
    <path d="M9 12h6M12 9v6" />
  </>);

export const IconSend = (p: P) =>
  base({ ...p, strokeWidth: 2.6 }, <path d="M12 19V5M5 12l7-7 7 7" />);
