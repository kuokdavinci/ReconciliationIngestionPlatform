"use client";

import { useEffect, useState } from "react";

interface Props {
  target?: string | null;
}

function remainingMs(target?: string | null) {
  if (!target) return null;
  const timestamp = new Date(target).getTime();
  if (Number.isNaN(timestamp)) return null;
  return Math.max(0, timestamp - Date.now());
}

function formatRemaining(value: number) {
  const totalSeconds = Math.ceil(value / 1000);
  if (totalSeconds <= 0) return "Retry available";
  if (totalSeconds < 60) return `Retry in ${totalSeconds}s`;

  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return seconds === 0
    ? `Retry in ${minutes}m`
    : `Retry in ${minutes}m ${seconds}s`;
}

export function RecoveryCountdown({ target }: Props) {
  const [clock, setClock] = useState(() => ({
    target,
    remaining: remainingMs(target),
  }));
  const remaining = clock.target === target ? clock.remaining : remainingMs(target);

  useEffect(() => {
    if (remainingMs(target) === null) return;

    const timer = window.setInterval(() => {
      const nextRemaining = remainingMs(target);
      setClock({ target, remaining: nextRemaining });
      if (nextRemaining === null || nextRemaining <= 0) window.clearInterval(timer);
    }, 1000);
    return () => window.clearInterval(timer);
  }, [target]);

  if (remaining === null) return <span>Retry schedule unavailable</span>;
  return <span>{formatRemaining(remaining)}</span>;
}
