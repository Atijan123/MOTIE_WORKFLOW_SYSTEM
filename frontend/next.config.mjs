/** @type {import('next').NextConfig} */
const nextConfig = {
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
