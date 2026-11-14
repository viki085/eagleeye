import type { Metadata } from "next";
import { ClerkProvider } from "@clerk/nextjs";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

import { THEME_INIT_SCRIPT } from "@/lib/theme";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

/** Clerk's own screens (the "Manage account" modal) in the EagleEye palette; the CSS
 * variables in globals.css switch with the light/dark toggle. */
const CLERK_APPEARANCE = {
  variables: {
    colorPrimary: "var(--brand-gold)",
    colorPrimaryForeground: "#ffffff",
    colorBackground: "var(--clerk-surface)",
    colorForeground: "var(--clerk-text)",
    colorMutedForeground: "var(--clerk-muted-text)",
    colorInput: "var(--clerk-input)",
    colorInputForeground: "var(--clerk-text)",
    colorBorder: "var(--clerk-border)",
    colorRing: "var(--brand-gold)",
    borderRadius: "0.6rem",
    fontFamily: "var(--font-geist-sans)",
  },
};

export const metadata: Metadata = {
  title: "EagleEye",
  description: "Enterprise AI assistant — RAG, text-to-SQL, and cross-source analysis",
  icons: { icon: "/brand/eagleeye-icon-64.png", apple: "/brand/eagleeye-icon.png" },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <ClerkProvider appearance={CLERK_APPEARANCE}>
      {/* The init script sets the theme class before React hydrates. */}
      <html lang="en" suppressHydrationWarning>
        <head>
          <script dangerouslySetInnerHTML={{ __html: THEME_INIT_SCRIPT }} />
        </head>
        <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
          {children}
        </body>
      </html>
    </ClerkProvider>
  );
}
