"""Plan & subscription schemas."""
import uuid
from datetime import datetime
from pydantic import BaseModel


class ModuleResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    category: str
    icon: str | None
    sort_order: int
    is_active: bool
    model_config = {"from_attributes": True}


class PlanModuleResponse(BaseModel):
    module: ModuleResponse
    access_level: str
    quota_limit: int | None
    model_config = {"from_attributes": True}


class PlanResponse(BaseModel):
    id: uuid.UUID
    code: str
    name: str
    description: str | None
    price_monthly: float
    price_yearly: float
    currency: str
    ai_credits_monthly: int
    max_api_keys: int
    max_platforms: int
    max_trades_per_day: int
    features_json: dict | None
    sort_order: int
    is_active: bool
    is_default: bool
    model_config = {"from_attributes": True}


class PlanDetailResponse(PlanResponse):
    modules: list[PlanModuleResponse] = []


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    plan: PlanResponse
    billing_cycle: str
    status: str
    started_at: datetime
    expires_at: datetime | None
    cancelled_at: datetime | None
    is_trial: bool
    created_at: datetime
    model_config = {"from_attributes": True}


class SubscribeRequest(BaseModel):
    plan_code: str
    billing_cycle: str = "monthly"


class CreditBalanceResponse(BaseModel):
    balance: int
    lifetime_earned: int
    lifetime_used: int
    updated_at: datetime | None = None
    model_config = {"from_attributes": True}


class CreditTransactionResponse(BaseModel):
    id: uuid.UUID
    amount: int
    balance_after: int
    tx_type: str
    description: str | None
    reference_id: str | None
    created_at: datetime
    model_config = {"from_attributes": True}


class AdminAdjustCreditsRequest(BaseModel):
    user_id: uuid.UUID
    amount: int
    reason: str


# ── Admin Plan CRUD ───────────────────────────────────────────────────

class PlanCreateRequest(BaseModel):
    code: str
    name: str
    description: str | None = None
    price_monthly: float = 0
    price_yearly: float = 0
    currency: str = "USD"
    ai_credits_monthly: int = 0
    max_api_keys: int = 1
    max_platforms: int = 1
    max_trades_per_day: int = 5
    features_json: dict | None = None
    sort_order: int = 0
    is_active: bool = True
    is_default: bool = False


class PlanUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    price_monthly: float | None = None
    price_yearly: float | None = None
    currency: str | None = None
    ai_credits_monthly: int | None = None
    max_api_keys: int | None = None
    max_platforms: int | None = None
    max_trades_per_day: int | None = None
    features_json: dict | None = None
    sort_order: int | None = None
    is_active: bool | None = None
    is_default: bool | None = None


class PlanModuleAssignRequest(BaseModel):
    module_code: str
    access_level: str = "full"
    quota_limit: int | None = None


class ModuleUpdateRequest(BaseModel):
    name: str | None = None
    description: str | None = None
    category: str | None = None
    icon: str | None = None
    sort_order: int | None = None
    is_active: bool | None = None


class UserPlanSummary(BaseModel):
    """Minimal plan info returned with user profile / auth."""
    plan_code: str | None
    plan_name: str | None
    credits_balance: int
    modules: list[str]  # list of module codes the user can access
