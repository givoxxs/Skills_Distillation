"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
import { Bi } from "./bi";
import { Icon } from "./icon";
import { useLang } from "./language-provider";
import { useTheme } from "./theme-provider";
import { skillList } from "@/lib/mock-data";

export function Sidebar() {
  const pathname = usePathname();
  const [skillsOpen, setSkillsOpen] = useState(true);
  const { theme, setTheme } = useTheme();
  const { lang, toggle } = useLang();

  const isActive = (p: string) => pathname === p;
  const isSkillActive = (skill: string) => pathname === "/skills/" + skill;
  const skillsHighlighted = pathname?.startsWith("/skills");

  return (
    <aside className="sidebar">
      <div className="sidebar-brand">
        <div className="brand-mark">S</div>
        <div className="brand-name">
          Skill Distillation Lab
          <span className="sub">
            <Bi vi="Đồ án tốt nghiệp · 2026" en="Bachelor's thesis · 2026" />
          </span>
        </div>
      </div>

      <nav className="nav" aria-label="Primary navigation">
        <div className="nav-section">
          <Bi vi="Điều hướng" en="Navigation" />
        </div>

        <Link
          className={"nav-item" + (isActive("/") ? " active" : "")}
          href="/"
          aria-current={isActive("/") ? "page" : undefined}
        >
          <Icon name="home" />
          <Bi vi="Tổng quan" en="Overview" />
        </Link>

        <button
          className={"nav-item" + (skillsHighlighted ? " active" : "")}
          style={{
            textAlign: "left",
            width: "100%",
            background: "transparent",
            border: "1px solid transparent",
          }}
          onClick={() => setSkillsOpen((o) => !o)}
        >
          <Icon name="layers" />
          <Bi vi="Các skill" en="Skills" />
          <span
            style={{ marginLeft: "auto", display: "inline-flex", color: "var(--fg-faint)" }}
          >
            <Icon name={skillsOpen ? "chev-d" : "chev-r"} size={14} />
          </span>
        </button>

        {skillsOpen && (
          <div className="nav-sub">
            {skillList.map((s) => (
              <Link
                key={s}
                className={"nav-item" + (isSkillActive(s) ? " active" : "")}
                href={`/skills/${s}`}
                aria-current={isSkillActive(s) ? "page" : undefined}
              >
                <span className="mono" style={{ fontSize: 12 }}>
                  {s}
                </span>
              </Link>
            ))}
          </div>
        )}

        <Link
          className={"nav-item" + (isActive("/run") ? " active" : "")}
          href="/run"
          aria-current={isActive("/run") ? "page" : undefined}
        >
          <Icon name="play" />
          <Bi vi="Chạy thử" en="Live run" />
        </Link>

        <Link
          className={"nav-item" + (isActive("/compare") ? " active" : "")}
          href="/compare"
          aria-current={isActive("/compare") ? "page" : undefined}
        >
          <Icon name="diff" />
          <Bi vi="So sánh" en="Compare" />
        </Link>

        <Link
          className={"nav-item" + (isActive("/about") ? " active" : "")}
          href="/about"
          aria-current={isActive("/about") ? "page" : undefined}
        >
          <Icon name="info" />
          <Bi vi="Giới thiệu" en="About" />
        </Link>
      </nav>

      <div className="sidebar-footer" style={{ flexDirection: "column", gap: 8, alignItems: "stretch" }}>
        {/* Language toggle */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}>
            <Bi vi="Ngôn ngữ" en="Language" />
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={toggle}
            aria-label="Toggle language"
            title="Toggle VN / EN"
            style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
          >
            {lang === "vi" ? "VN · EN" : "EN · VN"}
          </button>
        </div>
        {/* Theme toggle */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            gap: 12,
          }}
        >
          <span style={{ fontSize: 12, color: "var(--fg-subtle)" }}>
            {theme === "dark" ? (
              <Bi vi="Chế độ tối" en="Dark mode" />
            ) : (
              <Bi vi="Chế độ sáng" en="Light mode" />
            )}
          </span>
          <button
            type="button"
            className="btn btn-ghost btn-icon"
            aria-label="Toggle theme"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            title="Toggle dark / light"
          >
            <Icon name={theme === "dark" ? "sun" : "moon"} size={16} />
          </button>
        </div>
      </div>
    </aside>
  );
}
