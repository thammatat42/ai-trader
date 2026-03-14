import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Login | AI Trader",
};

export default function LoginLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background">
      {children}
    </div>
  );
}
