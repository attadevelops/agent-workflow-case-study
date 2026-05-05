/**
 * Single shared 1Hz clock for SLA countdowns.
 *
 * Twenty-five rows each owning a setInterval would jitter and waste timers;
 * one hook with one timer, broadcast via React's render cycle, keeps every
 * countdown row aligned to the same tick.
 */

import { useEffect, useState } from "react";

export function useNow(intervalMs = 1000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs]);
  return now;
}
