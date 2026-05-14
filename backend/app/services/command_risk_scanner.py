import re

from ..core.config import settings


class CommandRiskScanner:
    """Conservative static risk scan before any experiment command is executed."""

    dangerous_patterns = [
        (re.compile(r"\brm\s+-rf\b", re.IGNORECASE), "recursive force delete"),
        (re.compile(r"\bRemove-Item\b.*\b-Recurse\b", re.IGNORECASE), "PowerShell recursive delete"),
        (re.compile(r"\bdel\s+/.+\s", re.IGNORECASE), "Windows bulk delete"),
        (re.compile(r"\bformat\b", re.IGNORECASE), "disk format command"),
        (re.compile(r"\bshutdown\b|\breboot\b", re.IGNORECASE), "machine shutdown/reboot"),
        (re.compile(r"\bsudo\b|\brunas\b", re.IGNORECASE), "privilege escalation"),
        (re.compile(r"\bStart-Process\b|\bInvoke-Expression\b", re.IGNORECASE), "process spawning or dynamic execution"),
        (re.compile(r"\bnohup\b|\bStart-Job\b", re.IGNORECASE), "background process"),
        (re.compile(r"\bC:\\Windows\b|/etc/|/usr/bin/|/System/", re.IGNORECASE), "system directory access"),
        (re.compile(r"\.env|id_rsa|PRIVATE KEY|authorized_keys", re.IGNORECASE), "secret or credential file access"),
    ]
    network_patterns = [
        (re.compile(r"\bcurl\b|\bwget\b|Invoke-WebRequest|requests\.", re.IGNORECASE), "network access"),
        (re.compile(r"\bpip\s+install\b|\bnpm\s+install\b|\bpnpm\s+install\b|\byarn\s+add\b|\bconda\s+install\b", re.IGNORECASE), "package installation"),
    ]

    def scan(self, plan: dict) -> dict:
        reasons: list[str] = []
        level = "safe"
        payload = self._joined_payload(plan)

        for pattern, reason in self.dangerous_patterns:
            if pattern.search(payload):
                reasons.append(reason)
                level = "dangerous"

        for pattern, reason in self.network_patterns:
            if pattern.search(payload):
                reasons.append(reason)
                if reason == "network access" and settings.experiment_allow_network:
                    continue
                if reason == "package installation" and settings.experiment_allow_package_install:
                    continue
                if level != "dangerous":
                    level = "needs_review"

        if plan.get("env_vars"):
            reasons.append("custom environment variables")
            if level == "safe":
                level = "needs_review"

        if not plan.get("commands"):
            reasons.append("no executable command")
            if level == "safe":
                level = "needs_review"

        return {"risk_level": level, "risk_reasons": sorted(set(reasons))}

    def _joined_payload(self, plan: dict) -> str:
        parts: list[str] = []
        for command in plan.get("commands", []):
            if isinstance(command, dict):
                parts.append(str(command.get("command", "")))
            else:
                parts.append(str(command))
        for file_item in plan.get("files", []):
            if isinstance(file_item, dict):
                parts.append(str(file_item.get("path", "")))
                parts.append(str(file_item.get("content", ""))[:2000])
        return "\n".join(parts)


command_risk_scanner = CommandRiskScanner()

