// One codebase, two apps (step 12b): PORTAL=staff builds the staff app,
// anything else the public applicant portal. Route files named
// page.staff.tsx / layout.staff.tsx exist only in the staff build, and
// page.applicant.tsx / layout.applicant.tsx only in the applicant build.
// Plain page.tsx (login, set-password, "/") is in both. So the public server
// doesn't contain the staff screens at all, nor the server actions they use.
const portal = process.env.PORTAL === "staff" ? "staff" : "applicant";

/** @type {import('next').NextConfig} */
const nextConfig = {
  pageExtensions: [`${portal}.tsx`, `${portal}.ts`, "tsx", "ts"],
  // A self-contained server in .next/standalone for the production image (Dockerfile).
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    serverActions: {
      // Uploads go through a server action; the API refuses anything over 10 MB.
      bodySizeLimit: "11mb",
    },
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          // No other site may frame these pages (clickjacking).
          { key: "X-Frame-Options", value: "SAMEORIGIN" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "same-origin" },
        ],
      },
    ];
  },
};

export default nextConfig;
