import type { Metadata } from "next";
import localFont from "next/font/local";
import { APP_BASE_URL, APP_PREVIEW_IMAGE, buildPortalMetadata } from "@/lib/portal-metadata";
import { DashboardShell } from "./layout-dashboard";
import GoogleMapsActionGuard from "@/components/google-maps/GoogleMapsActionGuard";
import "./globals.css";

const inter = localFont({
  src: "../node_modules/@fontsource-variable/inter/files/inter-latin-wght-normal.woff2",
  variable: "--font-inter",
  weight: "100 900",
  display: "swap",
});

export const metadata: Metadata = {
  ...buildPortalMetadata({
    title: "Fort Cordis",
    description: "Cardiologia veterinaria integrada, com portal seguro para tutores e clinicas parceiras.",
  }),
  metadataBase: new URL(APP_BASE_URL),
  applicationName: "Fort Cordis",
  icons: {
    icon: [
      {
        url: APP_PREVIEW_IMAGE,
        type: "image/png",
        sizes: "1563x1563",
      },
    ],
    apple: [
      {
        url: APP_PREVIEW_IMAGE,
        sizes: "1563x1563",
      },
    ],
    shortcut: [APP_PREVIEW_IMAGE],
  },
  other: {
    google: "notranslate",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="pt-BR" translate="no" className="notranslate" suppressHydrationWarning>
      <body
        className={`${inter.variable} font-sans antialiased notranslate`}
        translate="no"
        suppressHydrationWarning
      >
        <DashboardShell>{children}</DashboardShell>
        <GoogleMapsActionGuard />
      </body>
    </html>
  );
}
