import type { Metadata } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import "./globals.css";

const inter = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap"
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-mono",
  display: "swap"
});

export const metadata: Metadata = {
  title: "CEREBRO-QUANT // Sistema de Trading Agéntico Institucional",
  description: "Plataforma Cuantitativa Autónoma de Descubrimiento de Estrategias y Validación IS/OOS en Tiempo Real"
};

export default function RootLayout({
  children
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="es" className={`dark ${inter.variable} ${jetbrainsMono.variable}`}>
      <body className="h-screen w-screen overflow-hidden bg-[#030407] font-sans text-slate-200 antialiased">
        {children}
      </body>
    </html>
  );
}
