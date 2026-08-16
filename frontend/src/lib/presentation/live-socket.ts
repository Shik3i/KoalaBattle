export interface LiveSocket {
  onopen: (() => void) | null;
  onmessage: ((event: { data: string }) => void) | null;
  onerror: (() => void) | null;
  onclose: (() => void) | null;
  close(): void;
}

export interface LiveSocketOptions {
  url: string;
  onMessage(data: string): void;
  onConnected?(): void | Promise<void>;
  onStatus?(status: 'connected' | 'reconnecting'): void;
}

export interface LiveSocketRuntime {
  create(url: string): LiveSocket;
  set(callback: () => void, delayMs: number): unknown;
  clear(handle: unknown): void;
}

const browserRuntime: LiveSocketRuntime = {
  create: (url) => new WebSocket(url) as unknown as LiveSocket,
  set: (callback, delayMs) => setTimeout(callback, delayMs),
  clear: (handle) => clearTimeout(handle as ReturnType<typeof setTimeout>)
};

export function connectLiveSocket(
  options: LiveSocketOptions,
  runtime: LiveSocketRuntime = browserRuntime
): () => void {
  let socket: LiveSocket | null = null;
  let timer: unknown = null;
  let stopped = false;
  let attempt = 0;

  const schedule = (candidate?: LiveSocket) => {
    if (candidate && socket !== candidate) return;
    if (stopped || timer !== null) return;
    options.onStatus?.('reconnecting');
    const delay = Math.min(5_000, 500 * 2 ** Math.min(attempt, 4));
    attempt += 1;
    timer = runtime.set(() => {
      timer = null;
      open();
    }, delay);
  };

  const open = () => {
    if (stopped) return;
    const candidate = runtime.create(options.url);
    socket = candidate;
    candidate.onmessage = ({ data }) => options.onMessage(data);
    candidate.onerror = () => {
      candidate.close();
      schedule(candidate);
    };
    candidate.onclose = () => schedule(candidate);
    candidate.onopen = () => {
      if (socket !== candidate || stopped) return;
      attempt = 0;
      options.onStatus?.('connected');
      void Promise.resolve(options.onConnected?.()).catch(() => {
        candidate.close();
        schedule(candidate);
      });
    };
  };

  open();
  return () => {
    stopped = true;
    if (timer !== null) runtime.clear(timer);
    socket?.close();
  };
}
