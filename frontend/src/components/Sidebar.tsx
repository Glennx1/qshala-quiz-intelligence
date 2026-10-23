'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  Home,
  BookOpen,
  Sparkles,
  FileText,
  UploadCloud,
  Settings,
  Layers,
} from 'lucide-react';

export default function Sidebar() {
  const pathname = usePathname();

  const navItems = [
    { label: 'Dashboard', href: '/', icon: Home },
    { label: 'Questions', href: '/knowledge-base', icon: BookOpen },
    { label: 'Create Quiz', href: '/generate', icon: Sparkles },
    { label: 'Generated Quizzes', href: '/quizzes', icon: FileText },
    { label: 'Uploads', href: '/uploads', icon: UploadCloud },
    { label: 'Settings', href: '/settings', icon: Settings },
  ];

  return (
    <aside className="fixed inset-y-0 left-0 z-30 flex w-52 flex-col border-r border-slate-200/80 bg-white">
      {/* Brand Header */}
      <div className="flex h-16 items-center px-5">
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="flex h-8 w-8 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm shadow-blue-500/20 group-hover:bg-blue-700 transition-colors">
            <Layers className="h-4.5 w-4.5" />
          </div>
          <span className="text-[14.5px] font-bold tracking-tight text-slate-900">
            QSHALA AI
          </span>
        </Link>
      </div>

      {/* Navigation Links */}
      <nav className="flex-1 space-y-1 px-2.5 py-4">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.href === '/'
              ? pathname === '/'
              : pathname === item.href || pathname.startsWith(`${item.href}/`);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] whitespace-nowrap transition-all ${
                isActive
                  ? 'bg-blue-50/90 text-blue-600 font-semibold'
                  : 'text-slate-600 hover:bg-slate-50 hover:text-slate-900 font-medium'
              }`}
            >
              <Icon
                className={`h-4 w-4 shrink-0 ${
                  isActive ? 'text-blue-600' : 'text-slate-400 group-hover:text-slate-600'
                }`}
              />
              <span className="truncate">{item.label}</span>
            </Link>
          );
        })}
      </nav>

      {/* Bottom Subtle Metadata */}
      <div className="border-t border-slate-100 p-4">
        <div className="text-[11.5px] leading-snug text-slate-400 font-medium">
          QShala Intelligent<br />
          <span className="text-slate-500 font-normal">Questions Repository</span>
        </div>
      </div>
    </aside>
  );
}
