import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Squat Coach - side-view squat analysis",
  description:
    "Upload a side-view barbell squat and get repetition-by-repetition feedback assessed against a strength-training reference text.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <header className="site">
          <div className="inner">
            <h1>
              <a href="/" style={{ color: "var(--text)" }}>
                Squat&nbsp;Coach
              </a>
            </h1>
            <span className="tag">side-view barbell squat analysis</span>
          </div>
        </header>
        {children}
      </body>
    </html>
  );
}
