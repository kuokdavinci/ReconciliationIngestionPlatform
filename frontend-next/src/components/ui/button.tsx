import { type ButtonHTMLAttributes } from "react";
import styles from "./button.module.css";

type Variant = "default" | "primary" | "secondary" | "tertiary";
type Shape = "default" | "pill";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  shape?: Shape;
}

export function Button({
  variant = "default",
  shape = "default",
  className,
  children,
  ...props
}: ButtonProps) {
  const cls = [
    styles.button,
    styles[variant],
    shape === "pill" ? styles.pill : "",
    className ?? "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <button className={cls} {...props}>
      {children}
    </button>
  );
}
