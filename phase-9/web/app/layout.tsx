import type { Metadata } from "next";
import { Inter, Space_Grotesk } from "next/font/google";
import { Nav } from "@/components/Nav";
import { ApiStatusBar } from "@/components/ui";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const grotesk = Space_Grotesk({ subsets: ["latin"], variable: "--font-space-grotesk", display: "swap" });

export const metadata: Metadata = {
  title: "EvalPilot: is your AI chatbot safe to ship?",
  description: "Evals, security probes and code review for LLM chatbots, mapped to the OWASP Top 10 for LLM Applications.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${grotesk.variable}`}>
      <body className="min-h-screen">
        <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
          Skip to content
        </a>
        <Nav />
        <ApiStatusBar />
        <main id="main" className="mx-auto max-w-[1100px] px-5 pb-16 pt-6">
          {children}
        </main>
      </body>
    </html>
  );
}
