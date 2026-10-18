// jsdom has no ResizeObserver; MapView and NotificationChoropleth observe their
// container size on mount. Tests that need resize behaviour still stub their own.
if (!('ResizeObserver' in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
