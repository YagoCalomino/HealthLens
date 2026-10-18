import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App.tsx";
import Hub from "./pages/Hub.tsx";
import VigilanciaPanel from "./pages/VigilanciaPanel.tsx";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000,
      gcTime: 10 * 60 * 1000,
      retry: 2,
    },
  },
});

// Suppress Recharts width(-1)/height(-1) initial-render warning.
// ResponsiveContainer inicia com {width:-1,height:-1} antes do ResizeObserver
// disparar; os gráficos renderizam corretamente após a primeira medição.
if (import.meta.env.DEV) {
  const _warn = console.warn.bind(console);
  console.warn = (...a: unknown[]) => {
    if (typeof a[0] === 'string' && a[0].startsWith('The width(')) return;
    _warn(...a);
  };
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Hub />} />
          <Route path="/mortalidade" element={<App />} />
          <Route path="/vigilancia" element={<VigilanciaPanel />} />
          <Route path="*" element={<Hub />} />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>
);

