import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Lead Engine",
  description: "Construction lead intelligence for Bhiwadi, Khushkhera, Tapukara and Neemrana",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
