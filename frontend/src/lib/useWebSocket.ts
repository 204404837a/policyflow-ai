"use client";

import { useEffect, useRef, useState } from "react";
import type { WsMessage } from "./types";

/** Subscribe to /ws/cases/{id}; returns the latest status snapshot. */
export function useCaseSocket(caseId: string | null): WsMessage | null {
  const [message, setMessage] = useState<WsMessage | null>(null);
  const ref = useRef<WebSocket | null>(null);

  useEffect(() => {
    if (!caseId || typeof window === "undefined") return;
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${window.location.host}/ws/cases/${caseId}`);
    ref.current = ws;
    ws.onmessage = (ev) => {
      try {
        setMessage(JSON.parse(ev.data) as WsMessage);
      } catch {
        /* ignore malformed frames */
      }
    };
    return () => ws.close();
  }, [caseId]);

  return message;
}
