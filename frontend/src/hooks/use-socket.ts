"use client";

import { useEffect, useRef } from "react";
import { getSocket, disconnectSocket } from "@/lib/socket";

export function useSocket(): WebSocket | null {
  const socketRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    const socket = getSocket();
    socketRef.current = socket;

    return () => {
      disconnectSocket();
      socketRef.current = null;
    };
  }, []);

  return socketRef.current;
}
