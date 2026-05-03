/** @type {import('next').NextConfig} */
const nextConfig = {
  allowedDevOrigins: ['mirqab.atqen.co'],
  output: 'standalone',
  typescript: {
    ignoreBuildErrors: true,
  },
  images: {
    unoptimized: true,
  }
}

export default nextConfig
