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
  PanelLeftClose,
  PanelLeftOpen,
} from 'lucide-react';
import { useSidebar } from '../context/SidebarContext';

export default function Sidebar() {
  const pathname = usePathname();
  const { isCollapsed, toggleSidebar } = useSidebar();

  const navItems = [
    { label: 'Dashboard', href: '/', icon: Home },
    { label: 'Questions', href: '/knowledge-base', icon: BookOpen },
    { label: 'Create Quiz', href: '/generate', icon: Sparkles },
    { label: 'Generated Quizzes', href: '/quizzes', icon: FileText },
    { label: 'Uploads', href: '/uploads', icon: UploadCloud },
    { label: 'Settings', href: '/settings', icon: Settings },
  ];

  return (
    <aside
      className={`fixed inset-y-0 left-0 z-30 flex flex-col border-r border-slate-200/80 bg-white transition-all duration-300 ease-in-out ${
        isCollapsed ? 'w-16' : 'w-52'
      }`}
    >
      {/* Brand Header */}
      <div className={`flex h-16 items-center ${isCollapsed ? 'justify-center px-2' : 'justify-between px-4'}`}>
        <Link
          href="/"
          className={`flex items-center gap-2.5 group overflow-hidden ${isCollapsed ? 'justify-center' : ''}`}
          title="QShala AI"
        >
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-blue-600 text-white shadow-sm shadow-blue-500/20 group-hover:bg-blue-700 transition-colors">
            <Layers className="h-4.5 w-4.5" />
          </div>
          {!isCollapsed && (
            <span className="text-[14.5px] font-bold tracking-tight text-slate-900 whitespace-nowrap transition-opacity duration-200">
              QSHALA AI
            </span>
          )}
        </Link>

        {/* Toggle Collapse Button in Header */}
        {!isCollapsed && (
          <button
            onClick={toggleSidebar}
            type="button"
            className="flex h-7 w-7 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title="Collapse sidebar (Ctrl+B)"
            aria-label="Collapse sidebar"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* Navigation Links */}
      <nav className={`flex-1 space-y-1 py-4 ${isCollapsed ? 'px-2' : 'px-2.5'}`}>
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
              title={isCollapsed ? item.label : undefined}
              className={`flex items-center rounded-lg transition-all ${
                isCollapsed
                  ? 'justify-center h-10 w-full px-0'
                  : 'gap-2.5 px-3 py-2 text-[13px] whitespace-nowrap'
              } ${
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
              {!isCollapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {/* Toggle Expand Button when Collapsed */}
      {isCollapsed && (
        <div className="flex justify-center pb-2">
          <button
            onClick={toggleSidebar}
            type="button"
            className="flex h-8 w-8 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-slate-700 transition-colors"
            title="Expand sidebar (Ctrl+B)"
            aria-label="Expand sidebar"
          >
            <PanelLeftOpen className="h-4.5 w-4.5" />
          </button>
        </div>
      )}

      {/* Bottom Subtle Metadata */}
      <div className={`border-t border-slate-100 ${isCollapsed ? 'p-2 text-center' : 'p-4'}`}>
        {isCollapsed ? (
          <div
            className="text-[10px] font-bold text-slate-400 py-1 cursor-default"
            title="QShala Intelligent Questions Repository"
          >
            QI
          </div>
        ) : (
          <div className="text-[11.5px] leading-snug text-slate-400 font-medium">
            QShala Intelligent<br />
            <span className="text-slate-500 font-normal">Questions Repository</span>
          </div>
        )}
      </div>
    </aside>
  );
}
