// The web app manifest (step 12h): what the browser needs to offer "Install
// app" for the staff app. Served at /manifest.webmanifest and linked from
// every page by Next.js. Each build describes itself (lib/portal.ts).
import type { MetadataRoute } from "next";

import { PORTAL } from "@/lib/portal";

export default function manifest(): MetadataRoute.Manifest {
  const staff = PORTAL === "staff";
  return {
    name: staff ? "MOTIE ETLS Staff" : "MOTIE ETLS Services",
    short_name: staff ? "ETLS Staff" : "ETLS",
    description: "Ministry of Trade, Industry, Regional Integration and Employment, The Gambia",
    start_url: staff ? "/staff" : "/applications",
    scope: "/",
    display: "standalone",
    background_color: "#f7f5ef",
    theme_color: "#13283a",
    icons: [
      { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
      // The letter sits inside the middle 60%, so round icon masks don't cut it.
      { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
    ],
  };
}
