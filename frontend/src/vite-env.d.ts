/// <reference types="vite/client" />

declare module '@novnc/novnc' {
  interface RFBOptions {
    shared?: boolean
    credentials?: { username?: string; password?: string; target?: string }
    wsProtocols?: string[]
  }

  export default class RFB extends EventTarget {
    constructor(target: HTMLElement, url: string, options?: RFBOptions)
    viewOnly: boolean
    scaleViewport: boolean
    resizeSession: boolean
    showDotCursor: boolean
    background: string
    focusOnClick: boolean
    clipViewport: boolean
    disconnect(): void
    sendCtrlAltDel(): void
    machineShutdown(): void
    machineReboot(): void
    machineReset(): void
  }
}
