import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ThemeProvider } from "next-themes";

import { AppProvider } from "@/components/app-provider";
import { AppSidebar } from "@/components/sidebar/app-sidebar";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Synapse",
  description: "Chat with LangGraph agents over your documents and the web",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#ffffff" },
    { media: "(prefers-color-scheme: dark)", color: "#212121" },
  ],
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="h-full overflow-hidden">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <TooltipProvider>
            <AppProvider>
              <div className="flex h-dvh">
                <AppSidebar />
                <main className="relative flex min-w-0 flex-1 flex-col">{children}</main>
              </div>
              <Toaster position="top-center" />
            </AppProvider>
          </TooltipProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
