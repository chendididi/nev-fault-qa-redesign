import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "新能源汽车维修 RAG 系统",
  description: "多模态新能源汽车维修问答与诊断平台",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
