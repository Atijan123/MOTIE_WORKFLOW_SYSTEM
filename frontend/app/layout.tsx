import type { Metadata, Viewport } from "next";
import localFont from "next/font/local";

import { RegisterServiceWorker } from "@/components/RegisterServiceWorker";

import "./globals.css";

// The fonts are files in app/fonts/ (both under the SIL Open Font Licence,
// app/fonts/LICENCE.md), not downloaded from Google when the app is built:
// the office server must be able to build with no internet (step 13h).
// Each is a "variable" font: one file holds every weight.
const sans = localFont({
  src: "./fonts/IBMPlexSans-latin.woff2",
  weight: "400 600",
  variable: "--font-sans",
  display: "swap",
});
const serif = localFont({
  src: "./fonts/SourceSerif4-latin.woff2",
  weight: "600",
  variable: "--font-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: { default: "MOTIE ETLS Services", template: "%s · MOTIE ETLS Services" },
  description: "Ministry of Trade, Industry, Regional Integration and Employment, The Gambia",
  // Installing (step 12h): the icon on phones and Macs, and the manifest (app/manifest.ts).
  icons: { icon: "/icons/icon-192.png", apple: "/icons/icon-180.png" },
  appleWebApp: { capable: true, title: "ETLS", statusBarStyle: "default" },
};

export const viewport: Viewport = { width: "device-width", initialScale: 1, themeColor: "#13283a" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        {children}
        <RegisterServiceWorker />
      </body>
    </html>
  );
}
