/**
 * Single polling hook for the entire app.
 *
 * Project contract:
 *   • Polling cadence: 2 seconds.
 *   • No SWR, no React Query; plain useEffect + setInterval.
 *   • Both views (Dashboard, Exception Queue) consume the same hook output;
 *     the data is fetched once per tick and shared via props.
 *
 * Returns appointments, exceptions, health (for the strategy display in the
 * top nav), error state, and a `refresh()` callback for after admin actions.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchAppointments,
  fetchExceptions,
  fetchHealth,
  HealthResponse,
} from "../api";
import type { AppointmentState } from "../types";

export interface PollingData {
  appointments: AppointmentState[];
  exceptions: AppointmentState[];
  health: HealthResponse | null;
  error: Error | null;
  loading: boolean;
  refresh: () => Promise<void>;
}

const DEFAULT_INTERVAL_MS = 2000;

export function usePollingData(intervalMs: number = DEFAULT_INTERVAL_MS): PollingData {
  const [appointments, setAppointments] = useState<AppointmentState[]>([]);
  const [exceptions, setExceptions] = useState<AppointmentState[]>([]);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [loading, setLoading] = useState(true);

  const cancelledRef = useRef(false);

  const refresh = useCallback(async () => {
    try {
      const [a, e, h] = await Promise.all([
        fetchAppointments(),
        fetchExceptions(),
        fetchHealth(),
      ]);
      if (cancelledRef.current) return;
      setAppointments(a);
      setExceptions(e);
      setHealth(h);
      setError(null);
    } catch (err) {
      if (cancelledRef.current) return;
      setError(err as Error);
    } finally {
      if (!cancelledRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    cancelledRef.current = false;
    refresh();
    const id = setInterval(refresh, intervalMs);
    return () => {
      cancelledRef.current = true;
      clearInterval(id);
    };
  }, [intervalMs, refresh]);

  return { appointments, exceptions, health, error, loading, refresh };
}
