import { useEffect, useRef, useState } from "react";

export type SseConnectionState = "connecting" | "open" | "reconnecting" | "closed";

export interface UseEventSourceOptions {
  enabled?: boolean;
  onMessage: (event: MessageEvent<string>) => void;
  onReconnect?: () => void;
  reconnectDelayMs?: number;
}

const DEFAULT_RECONNECT_DELAY_MS = 2000;

export function useEventSource(url: string | null, options: UseEventSourceOptions): SseConnectionState {
  const [connectionState, setConnectionState] = useState<SseConnectionState>("connecting");
  const onMessageRef = useRef(options.onMessage);
  onMessageRef.current = options.onMessage;
  const onReconnectRef = useRef(options.onReconnect);
  onReconnectRef.current = options.onReconnect;

  useEffect(() => {
    if (!url || options.enabled === false) {
      setConnectionState("closed");
      return;
    }

    let cancelled = false;
    let source: EventSource | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    let hasOpenedOnce = false;

    const connect = () => {
      if (cancelled) return;
      setConnectionState(hasOpenedOnce ? "reconnecting" : "connecting");
      source = new EventSource(url);

      source.onopen = () => {
        if (cancelled) return;
        if (hasOpenedOnce) onReconnectRef.current?.();
        hasOpenedOnce = true;
        setConnectionState("open");
      };

      source.onmessage = (event) => {
        if (cancelled) return;
        onMessageRef.current(event);
      };

      source.onerror = () => {
        if (cancelled) return;
        source?.close();
        setConnectionState("reconnecting");
        reconnectTimer = setTimeout(connect, options.reconnectDelayMs ?? DEFAULT_RECONNECT_DELAY_MS);
      };
    };

    connect();

    return () => {
      cancelled = true;
      if (reconnectTimer) clearTimeout(reconnectTimer);
      source?.close();
      setConnectionState("closed");
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [url, options.enabled]);

  return connectionState;
}
