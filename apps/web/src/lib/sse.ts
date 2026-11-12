export interface SseEvent {
  id: string;
  event: string;
  data: unknown;
}

/** Reads an SSE byte stream (from fetch) and invokes onEvent per frame. */
export async function consumeSse(
  body: ReadableStream<Uint8Array>,
  onEvent: (evt: SseEvent) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep: number;
      while ((sep = buffer.indexOf("\n\n")) !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        const evt = parseFrame(frame);
        if (evt !== null) onEvent(evt);
      }
    }
  } finally {
    reader.releaseLock();
  }
}

function parseFrame(frame: string): SseEvent | null {
  let id = "";
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith(":")) continue; // heartbeat comment
    if (line.startsWith("id:")) id = line.slice(3).trim();
    else if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (dataLines.length === 0) return null;
  try {
    return { id, event, data: JSON.parse(dataLines.join("\n")) };
  } catch {
    return null;
  }
}
