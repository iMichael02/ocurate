// One connection per Session. Same interface for the real WebSocket and the mock:
//   conn.send(obj)          send a protocol message
//   conn.onMessage = fn     called with each parsed message from the service
//   conn.onClose = fn       called with the close code
//   conn.close()

import { CONFIG } from "./config.js";
import { MockService } from "./mock-service.js";

export function openConnection({ token, passage }) {
  return CONFIG.useMock ? new MockConnection(passage) : new WsConnection(token);
}

class WsConnection {
  constructor(token) {
    this.onMessage = () => {};
    this.onClose = () => {};
    this.ready = new Promise((resolve, reject) => {
      this.ws = new WebSocket(CONFIG.serviceWsUrl);
      this.ws.onopen = () => {
        // First message: protocol version + token (version is checked first).
        this.send({ type: "hello", version: CONFIG.protocolVersion, token });
        resolve();
      };
      this.ws.onerror = () => reject(new Error("Could not reach the gaze-analysis service"));
    });
    this.ws.onmessage = (e) => this.onMessage(JSON.parse(e.data));
    this.ws.onclose = (e) => this.onClose(e.code);
  }
  send(msg) {
    if (this.ws.readyState === WebSocket.OPEN) this.ws.send(JSON.stringify(msg));
  }
  close() {
    this.ws.close(1000);
  }
}

class MockConnection {
  constructor(passage) {
    this.onMessage = () => {};
    this.onClose = () => {};
    this.service = new MockService(passage, (msg) => this.onMessage(msg), (code) => this.onClose(code));
    this.ready = Promise.resolve().then(() =>
      this.send({ type: "hello", version: CONFIG.protocolVersion, token: "mock-token" })
    );
  }
  send(msg) {
    // Round-trip through JSON so the mock sees exactly what the real socket would.
    this.service.receive(JSON.parse(JSON.stringify(msg)));
  }
  close() {
    this.service.close();
  }
  // Mock only: lets the mouse stand in for gaze during reading.
  setPointer(x, y) {
    this.service.pointer = { x, y };
  }
}
