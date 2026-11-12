import type { Metadata } from "next";

export const APP_BASE_URL = "https://app.fortcordis.com.br";
export const APP_PREVIEW_IMAGE = "/brand/fortcordis-logo-oficial.png";

const APP_PREVIEW_ALT = "Logomarca Fort Cordis";

type PortalMetadataInput = {
  title: string;
  description: string;
  path?: string;
};

function resolvePortalUrl(path: string) {
  return new URL(path, APP_BASE_URL).toString();
}

export function buildPortalMetadata({
  title,
  description,
  path = "/",
}: PortalMetadataInput): Metadata {
  const pageUrl = resolvePortalUrl(path);

  return {
    title,
    description,
    alternates: {
      canonical: pageUrl,
    },
    openGraph: {
      type: "website",
      locale: "pt_BR",
      url: pageUrl,
      siteName: "Fort Cordis",
      title,
      description,
      images: [
        {
          url: APP_PREVIEW_IMAGE,
          width: 1563,
          height: 1563,
          alt: APP_PREVIEW_ALT,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [APP_PREVIEW_IMAGE],
    },
  };
}
