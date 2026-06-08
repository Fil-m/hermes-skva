# SKVA gate_notifications — auto-generated
"""TZ gap closure"""
import sys, os, json, asyncio
from pathlib import Path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from skva_core import log

#!/usr/bin/env python3
"""
NotificationGateway — Telegram/Discord notifications for SKVA.
Sends completion, error, and phase update messages via webhook.
Uses environment variable SKVA_GATEWAY_URL for endpoint.
"""

import asyncio
import os
import json
import subprocess
import sys
from typing import Dict, Any, Optional
from datetime import datetime

from .utils import log  # assuming log exists in shared utils

__all__ = ["NotificationGateway"]


class NotificationGateway:
    """
    Gateway for sending notifications to Telegram or Discord
    using outgoing webhooks via curl (for compatibility and proxy support).
    """

    def __init__(self):
        self.webhook_url = os.environ.get("SKVA_GATEWAY_URL")
        if not self.webhook_url:
            log("SKVA_GATEWAY_URL не встановлено — сповіщення вимкнено.", "WARNING")
        self.default_service = "telegram"  # fallback

    async def send(self, message: str, service: str = "telegram") -> bool:
        """
        Send a raw message to the specified service.
        Returns True on success.
        """
        if not self.webhook_url:
            return False

        payload = self._build_payload(message, service)
        if not payload:
            log(f"Непідтримуваний сервіс: {service}", "ERROR")
            return False

        try:
            proc = await asyncio.create_subprocess_exec(
                "curl", "-s", "-S", "-X", "POST",
                "-H", "Content-Type: application/json",
                "-d", json.dumps(payload),
                self.webhook_url,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, stderr = await proc.communicate()

            if proc.returncode != 0:
                error_msg = stderr.decode().strip() or stdout.decode().strip()
                log(f"Помилка відправки повідомлення: {error_msg}", "ERROR")
                return False
            return True
        except Exception as e:
            log(f"Виняток при відправці повідомлення: {e}", "ERROR")
            return False

    async def send_phase_complete(self, phase: str, stats: Dict[str, Any]) -> bool:
        """
        Notify that a phase is complete with summary stats.
        """
        phase_names = {
            "analyze": "Аналіз",
            "design": "Дизайн",
            "implement": "Реалізація",
            "review": "Перевірка",
            "fix": "Виправлення",
            "deploy": "Розгортання",
        }
        phase_name = phase_names.get(phase, phase.title())

        total_time = stats.get("duration", 0)
        tokens = stats.get("total_tokens", 0)
        files = stats.get("files_written", 0)
        patches = stats.get("patches_applied", 0)

        message = (
            f"✅ **Фаза завершена**: {phase_name}\n"
            f"⏱ Час: {total_time:.1f} с | 📄 Файли: {files} | 🪄 Патчі: {patches} | "
            f"🔢 Токени: {tokens}"
        )
        return await self.send(message)

    async def send_project_done(self, url: str, stats: Dict[str, Any]) -> bool:
        """
        Notify that the entire project is complete.
        """
        total_duration = stats.get("total_duration", 0)
        total_tokens = stats.get("total_tokens", 0)
        total_cost = (total_tokens * 8) / 1_000_000  # rough estimate
        nodes = stats.get("nodes_completed", 0)

        message = (
            f"🎉 **Проект завершено!**\n\n"
            f"🔗 [Переглянути результати]({url})\n"
            f"⏱ Загальний час: {total_duration:.1f} с\n"
            f"🧠 Ноди оброблено: {nodes}\n"
            f"🔢 Загалом токенів: {total_tokens}\n"
            f"💰 Орієнтовна вартість: ${total_cost:.4f}\n\n"
            f"Дякуємо за використання SKVA Core Engine!"
        )
        return await self.send(message)

    async def send_error(self, phase: str, error: str) -> bool:
        """
        Send an error notification.
        """
        message = (
            f"❌ **Помилка в фазі**: {phase.upper()}\n\n"
            f"