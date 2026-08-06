import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";

ReactDOM.createRoot(document.getElementById("root")).render(<App />);

// Service Worker für den Offline-Modus: cached die App-Hülle, damit das
// Dashboard auch ohne Verbindung öffnet. Läuft nur über HTTPS/localhost.
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}
