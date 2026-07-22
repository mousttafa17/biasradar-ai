import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "BiasRadar Football",
    template: "%s · BiasRadar Football",
  },
  description:
    "Evidence-aware intelligence for football controversies and media narratives.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="h-full antialiased">
      <body
        className="min-h-full"
        style={
          {
            "--font-bias-sans":
              'Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif',
            "--font-bias-mono":
              '"SFMono-Regular", Consolas, "Liberation Mono", monospace',
          } as React.CSSProperties
        }
      >
        {children}
      </body>
    </html>
  );
}
