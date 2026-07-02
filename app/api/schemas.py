"""Pydantic request models for the REST transport layer."""

from datetime import date
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ErrorBody(BaseModel):
    code: str
    message: str
    details: Optional[list[dict[str, Any]]] = None


class ErrorResponse(BaseModel):
    error: ErrorBody


class SessionData(BaseModel):
    user_id: int
    username: str
    full_name: str
    role: Literal["admin", "manager", "cashier"]
    store_id: int


class LoginData(BaseModel):
    access_token: str
    token_type: Literal["bearer"]
    expires_at: str
    session: SessionData


class LoginResponse(BaseModel):
    data: LoginData


class SessionResponse(BaseModel):
    data: SessionData


class DataResponse(BaseModel):
    data: Any


class PageMeta(BaseModel):
    page: int
    per_page: int
    total: int
    pages: int


class PaginatedResponse(BaseModel):
    data: list[Any]
    meta: PageMeta


class LoginRequest(ApiModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=256)
    store_id: Optional[int] = Field(default=None, gt=0)


class StoreSwitchRequest(ApiModel):
    store_id: int = Field(gt=0)


class UserCreateRequest(ApiModel):
    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8, max_length=256)
    full_name: str = Field(min_length=1, max_length=200)
    role: Literal["admin", "manager", "cashier"] = "cashier"
    home_store_id: Optional[int] = Field(default=None, gt=0)


class PasswordChangeRequest(ApiModel):
    new_password: str = Field(min_length=8, max_length=256)


class StoreCreateRequest(ApiModel):
    code: str = Field(min_length=1, max_length=30)
    name: str = Field(min_length=1, max_length=150)
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_user_id: Optional[int] = Field(default=None, gt=0)


class StoreUpdateRequest(ApiModel):
    code: Optional[str] = Field(default=None, min_length=1, max_length=30)
    name: Optional[str] = Field(default=None, min_length=1, max_length=150)
    address: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    manager_user_id: Optional[int] = Field(default=None, gt=0)


class ProductCreateRequest(ApiModel):
    sku: str = Field(min_length=1)
    name: str = Field(min_length=1)
    selling_price: float = Field(ge=0)
    category_id: Optional[int] = Field(default=None, gt=0)
    supplier_id: Optional[int] = Field(default=None, gt=0)
    barcode: Optional[str] = None
    cost_price: float = Field(default=0, ge=0)
    quantity_in_stock: int = Field(default=0, ge=0)
    reorder_level: int = Field(default=0, ge=0)
    description: Optional[str] = None
    store_id: Optional[int] = Field(default=None, gt=0)


class ProductUpdateRequest(ApiModel):
    category_id: Optional[int] = Field(default=None, gt=0)
    supplier_id: Optional[int] = Field(default=None, gt=0)
    sku: Optional[str] = Field(default=None, min_length=1)
    barcode: Optional[str] = None
    name: Optional[str] = Field(default=None, min_length=1)
    description: Optional[str] = None
    cost_price: Optional[float] = Field(default=None, ge=0)
    selling_price: Optional[float] = Field(default=None, ge=0)
    reorder_level: Optional[int] = Field(default=None, ge=0)
    is_active: Optional[bool] = None


class StockAdjustmentRequest(ApiModel):
    new_quantity: int = Field(ge=0)
    notes: Optional[str] = None
    store_id: Optional[int] = Field(default=None, gt=0)


class StockReceiveRequest(ApiModel):
    quantity: int = Field(gt=0)
    notes: Optional[str] = None
    store_id: Optional[int] = Field(default=None, gt=0)


class SaleLineRequest(ApiModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


PaymentMethod = Literal["CASH", "CARD", "TRANSFER", "WALLET", "CREDIT", "MIXED"]


class PaymentAllocationRequest(ApiModel):
    payment_method: Literal["CASH", "CARD", "TRANSFER", "WALLET", "CREDIT"]
    amount: float = Field(gt=0)


class SaleCreateRequest(ApiModel):
    items: list[SaleLineRequest] = Field(min_length=1)
    payment_method: PaymentMethod = "CASH"
    amount_paid: Optional[float] = Field(default=None, ge=0)
    discount_type: Optional[Literal["PERCENTAGE", "FIXED"]] = None
    discount_value: float = Field(default=0, ge=0)
    tax_rate: Optional[float] = Field(default=None, ge=0)
    store_id: Optional[int] = Field(default=None, gt=0)
    register_name: Optional[str] = None
    customer_id: Optional[int] = Field(default=None, gt=0)
    redeem_points: int = Field(default=0, ge=0)
    payments: Optional[list[PaymentAllocationRequest]] = None


class ReturnLineRequest(ApiModel):
    sale_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0)


class ReturnCreateRequest(ApiModel):
    items: list[ReturnLineRequest] = Field(min_length=1)
    reason: str = Field(min_length=1)


class RefundRequest(ApiModel):
    reason: str = Field(default="Full sale refund", min_length=1)


class SupplierRequest(ApiModel):
    name: str = Field(min_length=1)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class SupplierUpdateRequest(ApiModel):
    name: Optional[str] = Field(default=None, min_length=1)
    phone: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None


class PurchaseLineRequest(ApiModel):
    product_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_cost: float = Field(ge=0)


class PurchaseOrderCreateRequest(ApiModel):
    supplier_id: int = Field(gt=0)
    reference_number: str = Field(min_length=1)
    line_items: list[PurchaseLineRequest] = Field(min_length=1)
    expected_delivery_date: Optional[date] = None
    notes: Optional[str] = None
    store_id: Optional[int] = Field(default=None, gt=0)


class ReceiveLineRequest(ApiModel):
    purchase_order_item_id: int = Field(gt=0)
    quantity: int = Field(gt=0)
    unit_cost: Optional[float] = Field(default=None, ge=0)


class ReceivePurchaseRequest(ApiModel):
    line_items: list[ReceiveLineRequest] = Field(min_length=1)
    notes: Optional[str] = None


class TransferLineRequest(ApiModel):
    product_id: Optional[int] = Field(default=None, gt=0)
    transfer_item_id: Optional[int] = Field(default=None, gt=0)
    quantity: int = Field(gt=0)


class TransferCreateRequest(ApiModel):
    reference_number: str = Field(min_length=1)
    source_store_id: int = Field(gt=0)
    destination_store_id: int = Field(gt=0)
    line_items: list[TransferLineRequest] = Field(min_length=1)
    notes: Optional[str] = None


class TransferActivityRequest(ApiModel):
    line_items: list[TransferLineRequest] = Field(min_length=1)
    notes: Optional[str] = None


class NotesRequest(ApiModel):
    notes: Optional[str] = None


class CustomerCreateRequest(ApiModel):
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    business_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    tax_number: Optional[str] = None
    notes: Optional[str] = None
    group_id: Optional[int] = Field(default=None, gt=0)


class CustomerUpdateRequest(ApiModel):
    first_name: Optional[str] = Field(default=None, min_length=1)
    last_name: Optional[str] = Field(default=None, min_length=1)
    business_name: Optional[str] = None
    phone_number: Optional[str] = None
    email: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None
    date_of_birth: Optional[date] = None
    gender: Optional[str] = None
    tax_number: Optional[str] = None
    notes: Optional[str] = None
    group_id: Optional[int] = Field(default=None, gt=0)


class CustomerGroupRequest(ApiModel):
    name: str = Field(min_length=1)
    default_discount: float = Field(default=0, ge=0, le=100)
    pricing_priority: int = Field(default=0, ge=0)
    description: Optional[str] = None


class AmountRequest(ApiModel):
    amount: float = Field(gt=0)
    notes: Optional[str] = None


class AdjustmentRequest(ApiModel):
    amount_delta: float
    notes: Optional[str] = None


class LoyaltyAdjustmentRequest(ApiModel):
    points: int
    notes: Optional[str] = None


class CreditTermsRequest(ApiModel):
    credit_limit: float = Field(ge=0)
    due_date: Optional[date] = None
