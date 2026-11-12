/** @type {import('next').NextConfig} */
// No servidor (stage/producao), defina API_BACKEND_URL (ex.: http://127.0.0.1:8000)
const withBundleAnalyzer = require("@next/bundle-analyzer")({
  enabled: process.env.ANALYZE === "true",
});
const path = require("path")
const apiBackend = process.env.API_BACKEND_URL || 'http://127.0.0.1:8000'
const whatsappStageBackend = process.env.WHATSAPP_STAGE_BACKEND_URL
const appContentSecurityPolicy = [
  "default-src 'self'",
  "base-uri 'self'",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "img-src 'self' data: blob: https:",
  "media-src 'self' blob: https:",
  "font-src 'self' data: https:",
  "frame-src 'self' blob:",
  "style-src 'self' 'unsafe-inline' https:",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' https:",
  "connect-src 'self' https: wss: ws:",
].join('; ')

const nextConfig = {
  devIndicators: false,
  outputFileTracingRoot: path.resolve(__dirname),
  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          {
            key: 'Content-Security-Policy',
            value: appContentSecurityPolicy,
          },
          {
            key: 'X-Frame-Options',
            value: 'DENY',
          },
          {
            key: 'X-Content-Type-Options',
            value: 'nosniff',
          },
        ],
      },
    ]
  },
  async rewrites() {
    const rewrites = [
      {
        source: '/api/v1/:path*',
        destination: `${apiBackend}/api/v1/:path*`,
      },
    ]

    if (whatsappStageBackend) {
      rewrites.push(
        {
          source: '/whatsapp',
          destination: `${whatsappStageBackend}/health`,
        },
        {
          source: '/whatsapp/:path*',
          destination: `${whatsappStageBackend}/:path*`,
        }
      )
    }

    return rewrites
  },
}

module.exports = withBundleAnalyzer(nextConfig)
