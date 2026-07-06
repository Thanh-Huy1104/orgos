import React from "react";

export function Heading({
  level = 1,
  className = "",
  children,
}: {
  level?: 1 | 2 | 3;
  className?: string;
  children: React.ReactNode;
}) {
  const Tag = `h${level}` as keyof React.JSX.IntrinsicElements;
  const sizes: Record<number, string> = {
    1: "text-2xl font-bold tracking-tight",
    2: "text-xl font-semibold",
    3: "text-base font-semibold",
  };
  return <Tag className={`${sizes[level]} ${className}`} style={{ color: "var(--text-primary)" }}>{children}</Tag>;
}

export function Button({
  variant = "primary",
  size = "md",
  className = "",
  children,
  ...props
}: {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  size?: "sm" | "md";
  className?: string;
  children: React.ReactNode;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const base = "inline-flex items-center justify-center font-medium transition-all duration-150 cursor-pointer border-none rounded-lg";
  const sizes: Record<string, string> = {
    sm: "text-xs px-3 py-1.5",
    md: "text-sm px-4 py-2",
  };
  const variants: Record<string, string> = {
    primary: "bg-[var(--accent)] text-white hover:brightness-110",
    secondary: "bg-[var(--bg-secondary)] text-[var(--text-primary)] border border-[var(--border)] hover:bg-[var(--bg-hover)]",
    danger: "bg-[var(--red)] text-white hover:brightness-110",
    ghost: "text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-secondary)]",
  };
  return (
    <button className={`${base} ${sizes[size]} ${variants[variant]} ${className}`} {...props}>
      {children}
    </button>
  );
}

export function Card({
  hover = false,
  className = "",
  children,
  ...props
}: {
  hover?: boolean;
  className?: string;
  children: React.ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
  const hoverClass = hover ? "cursor-pointer transition-shadow hover:shadow-sm hover:border-[var(--accent)]" : "";
  return (
    <div
      className={`bg-white border border-[var(--border)] rounded-xl p-4 ${hoverClass} ${className}`}
      {...props}
    >
      {children}
    </div>
  );
}

export function Badge({
  variant = "gray",
  className = "",
  children,
}: {
  variant?: "green" | "red" | "yellow" | "blue" | "gray";
  className?: string;
  children: React.ReactNode;
}) {
  const colors: Record<string, string> = {
    green: "bg-[var(--green-bg)] text-[var(--green)]",
    red: "bg-[var(--red-bg)] text-[var(--red)]",
    yellow: "bg-[var(--yellow-bg)] text-[var(--yellow)]",
    blue: "bg-[var(--blue-bg)] text-[var(--blue)]",
    gray: "bg-[var(--bg-secondary)] text-[var(--text-secondary)]",
  };
  return (
    <span className={`text-[11px] font-medium px-2 py-0.5 rounded-md ${colors[variant]} ${className}`}>
      {children}
    </span>
  );
}

export function Input({
  label,
  className = "",
  ...props
}: {
  label: string;
  className?: string;
} & React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <label className="block" style={{ color: "var(--text-secondary)", fontSize: 13 }}>
      {label}
      <input
        className={`mt-1 block w-full input ${className}`}
        {...props}
      />
    </label>
  );
}
