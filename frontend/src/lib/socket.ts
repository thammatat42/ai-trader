let socket: WebSocket | null = null;

export function getSocket(): WebSocket {
  if (!socket || socket.readyState === WebSocket.CLOSED) {
    const wsUrl = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
    const token = typeof window !== "undefined" ? localStorage.getItem("access_token") : null;
    const url = token ? `${wsUrl}/api/v1/ws?token=${token}` : `${wsUrl}/api/v1/ws`;

    socket = new WebSocket(url);
  }
  return socket;
}

export function disconnectSocket() {
  if (socket) {
    socket.close();
    socket = null;
  }
}
