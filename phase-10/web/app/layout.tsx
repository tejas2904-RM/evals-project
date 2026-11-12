import type { Metadata } from "next";
import { Geist, Geist_Mono, Instrument_Serif } from "next/font/google";
import { Nav } from "@/components/Nav";
import { ParticleNetwork } from "@/components/ParticleNetwork";
import { ApiStatusBar } from "@/components/ui";
import "./globals.css";

const geist = Geist({ subsets: ["latin"], variable: "--font-geist", display: "swap" });
const geistMono = Geist_Mono({ subsets: ["latin"], variable: "--font-geist-mono", display: "swap" });
const instrument = Instrument_Serif({
  subsets: ["latin"],
  weight: "400",
  variable: "--font-instrument",
  display: "swap",
});

export const metadata: Metadata = {
  title: "EvalPilot: is your AI chatbot safe to ship?",
  description: "Evals, security probes and code review for LLM chatbots, mapped to the OWASP Top 10 for LLM Applications.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${geist.variable} ${geistMono.variable} ${instrument.variable}`}>
      <body className="min-h-screen">
        <ParticleNetwork />
        <div className="relative z-10">
          <a
            href="#main"
            className="sr-only focus:not-sr-only focus:absolute focus:left-3 focus:top-3 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
          >
            Skip to content
          </a>
          <Nav />
          <ApiStatusBar />
          <main id="main" className="mx-auto max-w-[1100px] px-5 pb-16 pt-6">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
