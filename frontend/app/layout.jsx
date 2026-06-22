import "./globals.css";

export const metadata = {
  title: "Data Analysis Agent",
  description: "UI gateway for a data analysis agent service",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
