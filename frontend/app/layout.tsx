import type { Metadata, Viewport } from "next";
import { IBM_Plex_Sans, Source_Serif_4 } from "next/font/google";

import "./globals.css";

// next/font downloads the fonts once, at build time, and serves them from
// this site: no request to Google from the user's browser, and only the
// weights listed here. Text shows in a fallback font until they arrive.
const sans = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600"], variable: "--font-sans", display: "swap" });
const serif = Source_Serif_4({ subsets: ["latin"], weight: ["600"], variable: "--font-serif", display: "swap" });

export const metadata: Metadata = {
  title: { default: "MOTIE ETLS Services", template: "%s · MOTIE ETLS Services" },
  description: "Ministry of Trade, Industry, Regional Integration and Employment, The Gambia",
};

export const viewport: Viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>{children}</body>
    </html>
  );
}
