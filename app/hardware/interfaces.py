"""Peripheral contracts shared by null, mock, and future real drivers."""

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any

from app.hardware.profiles import PrinterProfile


@dataclass(frozen=True)
class DeviceStatus:
    device_type: str
    enabled: bool
    available: bool
    adapter: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ReceiptPrinter(ABC):
    @abstractmethod
    def status(self) -> DeviceStatus:
        raise NotImplementedError

    @abstractmethod
    def print_text(self, text: str, profile: PrinterProfile, job_name: str) -> None:
        raise NotImplementedError

    def pulse_drawer(self) -> None:
        raise NotImplementedError


class CashDrawer(ABC):
    @abstractmethod
    def status(self) -> DeviceStatus:
        raise NotImplementedError

    @abstractmethod
    def open(self) -> None:
        raise NotImplementedError


class BarcodeScanner(ABC):
    @abstractmethod
    def status(self) -> DeviceStatus:
        raise NotImplementedError

    @abstractmethod
    def normalize(self, raw_value: str) -> str:
        raise NotImplementedError


class CustomerDisplay(ABC):
    @abstractmethod
    def status(self) -> DeviceStatus:
        raise NotImplementedError

    @abstractmethod
    def show_welcome(self, message: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def show_item(self, name: str, quantity: int, price: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def show_total(self, subtotal: float, total: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def show_payment(self, message: str, total: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def clear(self) -> None:
        raise NotImplementedError
