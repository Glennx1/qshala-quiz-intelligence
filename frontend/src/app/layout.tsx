import type { Metadata } from 'next';
import { Plus_Jakarta_Sans } from 'next/font/google';
import './globals.css';
import Sidebar from '../components/Sidebar';
import Topbar from '../components/Topbar';

const plusJakartaSans = Plus_Jakarta_Sans({
  subsets: ['latin'],
  weight: ['400', '500', '600', '700'],
  variable: '--font-plus-jakarta',
  display: 'swap',
});

export const metadata: Metadata = {
  title: 'QShala AI — Quiz Intelligence Platform',
  description: 'Create engaging quizzes using your trusted QShala knowledge base.',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className={`h-full bg-slate-50 text-slate-900 antialiased ${plusJakartaSans.variable}`}>
      <body className={`min-h-full flex bg-slate-50 font-sans ${plusJakartaSans.className}`}>
        <Sidebar />
        <div className="flex-1 pl-60 flex flex-col min-w-0">
          <Topbar />
          <main className="flex-1">{children}</main>
        </div>
      </body>
    </html>
  );
}
