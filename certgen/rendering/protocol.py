"""The renderer contract: everything printed on a certificate in, PDF bytes out."""

from dataclasses import dataclass
from datetime import date
from typing import Protocol


@dataclass(frozen=True)
class RenderContext:
    recipient_name: str
    title: str
    achievement_line: str
    certificate_kind: str
    issued_on: date
    issuer_name: str
    signatory_name: str
    signatory_title: str
    serial: str
    verification_url: str


class CertificateRenderer(Protocol):
    def render(self, context: RenderContext) -> bytes: ...
