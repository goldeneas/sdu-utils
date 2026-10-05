"""Invio notifiche tramite NTFY (https://ntfy.sh)."""
from __future__ import annotations

import os

import requests

from .config import Config
from .models import FlightOption


class Notifier:
    def __init__(self, server, topic, token=None):
        self.server = (server or "ntfy.sh").strip().rstrip("/")
        self.topic = (topic or "").strip()
        self.token = token

    @property
    def available(self) -> bool:
        return bool(self.topic)

    def send(self, title: str, message: str, priority: str = "default"):
        if not self.available:
            return
        headers = {"Title": title, "Priority": priority}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        try:
            requests.post(
                f"https://{self.server}/{self.topic}",
                data=message.encode("utf-8"),
                headers=headers,
                timeout=10,
            )
        except requests.RequestException as exc:
            print(f"[ntfy] invio fallito: {exc}")

    def notify_new_best(self, opt: FlightOption, previous):
        if previous is None:
            msg = f"Nuovo best deal trovato: {opt.summary}"
        else:
            msg = f"Best deal migliorato: €{previous:.2f} → {opt.summary}"
        self.send("Flight Scanner · nuovo best deal", msg)

    def notify_summary(self, results, max_price: float):
        if results:
            best = results[0]
            msg = (
                f"Trovati {len(results)} voli ≤ €{max_price:.0f}. "
                f"Migliore: {best.summary}"
            )
        else:
            msg = f"Nessun volo ≤ €{max_price:.0f} trovato in questa esecuzione."
        self.send("Flight Scanner · riepilogo", msg)


def resolve_ntfy(cfg: Config) -> Notifier | None:
    n = cfg.ntfy
    if not n.enabled:
        return None
    server = os.getenv("NTFY_SERVER") or n.server
    topic = (n.topic or "").strip() or os.getenv("NTFY_TOPIC", "").strip()
    token = os.getenv("NTFY_TOKEN", "").strip()
    notifier = Notifier(server, topic, token or None)
    return notifier if notifier.available else None
