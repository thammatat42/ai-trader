"""Plans, Subscriptions & Credits API endpoints."""

from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_control import grant_credits
from app.core.database import get_db_session
from app.core.dependencies import get_current_user, require_role
from app.core.exceptions import ConflictError, NotFoundError, ForbiddenError
from app.models.credit_balance import CreditBalance
from app.models.credit_transaction import CreditTransaction
from app.models.module import Module
from app.models.plan import Plan
from app.models.plan_module import PlanModule
from app.models.user import User
from app.models.user_subscription import UserSubscription
from app.schemas.common import MessageResponse
from app.schemas.plan import (
    AdminAdjustCreditsRequest,
    CreditBalanceResponse,
    CreditTransactionResponse,
    PlanDetailResponse,
    PlanModuleResponse,
    PlanResponse,
    ModuleResponse,
    PlanCreateRequest,
    PlanUpdateRequest,
    PlanModuleAssignRequest,
    ModuleUpdateRequest,
    SubscribeRequest,
    SubscriptionResponse,
    UserPlanSummary,
)

logger = structlog.get_logger("plans")

router = APIRouter(prefix="/plans", tags=["plans"])


# ── Public: List available plans ──────────────────────────────────────

@router.get("", response_model=list[PlanResponse])
async def list_plans(db: AsyncSession = Depends(get_db_session)):
    """List all active plans (public, no auth required)."""
    result = await db.execute(
        select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.sort_order)
    )
    return result.scalars().all()


@router.get("/{plan_code}", response_model=PlanDetailResponse)
async def get_plan_detail(plan_code: str, db: AsyncSession = Depends(get_db_session)):
    """Get plan details with module list (public)."""
    result = await db.execute(select(Plan).where(Plan.code == plan_code))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    # Get modules for this plan
    pm_result = await db.execute(
        select(PlanModule, Module)
        .join(Module, Module.id == PlanModule.module_id)
        .where(PlanModule.plan_id == plan.id)
        .order_by(Module.sort_order)
    )
    rows = pm_result.all()
    modules = []
    for pm, mod in rows:
        modules.append(PlanModuleResponse(
            module=ModuleResponse.model_validate(mod),
            access_level=pm.access_level,
            quota_limit=pm.quota_limit,
        ))

    return PlanDetailResponse(
        **{c.name: getattr(plan, c.name) for c in Plan.__table__.columns},
        modules=modules,
    )


@router.get("/modules/all", response_model=list[ModuleResponse])
async def list_modules(db: AsyncSession = Depends(get_db_session)):
    """List all system modules (public)."""
    result = await db.execute(select(Module).order_by(Module.sort_order))
    return result.scalars().all()


# ── User: Subscription ────────────────────────────────────────────────

subscriptions_router = APIRouter(prefix="/subscriptions", tags=["subscriptions"])


@subscriptions_router.get("/me", response_model=SubscriptionResponse | None)
async def get_my_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get current user's active subscription."""
    result = await db.execute(
        select(UserSubscription, Plan)
        .join(Plan, Plan.id == UserSubscription.plan_id)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
        )
        .order_by(UserSubscription.created_at.desc())
        .limit(1)
    )
    row = result.first()
    if not row:
        return None

    sub, plan = row
    return SubscriptionResponse(
        id=sub.id,
        user_id=sub.user_id,
        plan=PlanResponse.model_validate(plan),
        billing_cycle=sub.billing_cycle,
        status=sub.status,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        cancelled_at=sub.cancelled_at,
        is_trial=sub.is_trial,
        created_at=sub.created_at,
    )


@subscriptions_router.post("/subscribe", response_model=SubscriptionResponse)
async def subscribe(
    body: SubscribeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Subscribe to a plan (or switch plans)."""
    # Find the plan
    result = await db.execute(select(Plan).where(Plan.code == body.plan_code, Plan.is_active.is_(True)))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    # Cancel existing active subscription
    existing = await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
        )
    )
    for old_sub in existing.scalars().all():
        old_sub.status = "cancelled"
        old_sub.cancelled_at = datetime.now(timezone.utc)

    # Create new subscription
    sub = UserSubscription(
        user_id=user.id,
        plan_id=plan.id,
        billing_cycle=body.billing_cycle,
        status="active",
    )
    db.add(sub)

    # Grant monthly AI credits
    if plan.ai_credits_monthly > 0:
        new_balance = await grant_credits(
            db, user.id, plan.ai_credits_monthly,
            tx_type="plan_grant",
            description=f"Monthly credits for {plan.name} plan",
        )
        logger.info("credits_granted", user_id=str(user.id), amount=plan.ai_credits_monthly, balance=new_balance)

    await db.commit()
    await db.refresh(sub)

    return SubscriptionResponse(
        id=sub.id,
        user_id=sub.user_id,
        plan=PlanResponse.model_validate(plan),
        billing_cycle=sub.billing_cycle,
        status=sub.status,
        started_at=sub.started_at,
        expires_at=sub.expires_at,
        cancelled_at=sub.cancelled_at,
        is_trial=sub.is_trial,
        created_at=sub.created_at,
    )


@subscriptions_router.post("/cancel", response_model=MessageResponse)
async def cancel_subscription(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Cancel current subscription (reverts to free tier access)."""
    result = await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
        )
    )
    subs = result.scalars().all()
    if not subs:
        raise NotFoundError("Active subscription")

    for sub in subs:
        sub.status = "cancelled"
        sub.cancelled_at = datetime.now(timezone.utc)
    await db.commit()
    return MessageResponse(message="Subscription cancelled")


# ── User: Plan Summary (for frontend sidebar / header) ────────────────

@subscriptions_router.get("/me/summary", response_model=UserPlanSummary)
async def get_plan_summary(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get compact plan summary with module access list + credit balance."""
    plan_code = None
    plan_name = None
    accessible_modules: list[str] = []

    # Admin gets everything
    if user.role == "admin":
        mod_result = await db.execute(select(Module.code))
        accessible_modules = [r[0] for r in mod_result.all()]
        plan_code = "admin"
        plan_name = "Administrator"
    else:
        # Get active plan
        sub_result = await db.execute(
            select(Plan)
            .join(UserSubscription, UserSubscription.plan_id == Plan.id)
            .where(
                UserSubscription.user_id == user.id,
                UserSubscription.status == "active",
            )
            .limit(1)
        )
        plan = sub_result.scalar_one_or_none()
        if plan:
            plan_code = plan.code
            plan_name = plan.name
            # Fetch module access
            pm_result = await db.execute(
                select(Module.code)
                .join(PlanModule, PlanModule.module_id == Module.id)
                .where(PlanModule.plan_id == plan.id)
            )
            accessible_modules = [r[0] for r in pm_result.all()]

    # Credits
    cb_result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user.id)
    )
    cb = cb_result.scalar_one_or_none()

    return UserPlanSummary(
        plan_code=plan_code,
        plan_name=plan_name,
        credits_balance=cb.balance if cb else 0,
        modules=accessible_modules,
    )


# ── User: Credits ─────────────────────────────────────────────────────

credits_router = APIRouter(prefix="/credits", tags=["credits"])


@credits_router.get("/me", response_model=CreditBalanceResponse)
async def get_my_credits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get current user's credit balance."""
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user.id)
    )
    cb = result.scalar_one_or_none()
    if not cb:
        return CreditBalanceResponse(balance=0, lifetime_earned=0, lifetime_used=0)
    return cb


@credits_router.get("/me/transactions", response_model=list[CreditTransactionResponse])
async def get_my_credit_transactions(
    limit: int = Query(default=50, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
):
    """Get user's credit transaction history."""
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ── Admin: Manage credits ─────────────────────────────────────────────

@credits_router.post("/admin/adjust", response_model=CreditBalanceResponse)
async def admin_adjust_credits(
    body: AdminAdjustCreditsRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin adjusts a user's credit balance (positive or negative)."""
    # Verify target user exists
    user_result = await db.execute(select(User).where(User.id == body.user_id))
    target = user_result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    if body.amount > 0:
        new_balance = await grant_credits(
            db, body.user_id, body.amount,
            tx_type="admin_adjust",
            description=f"Admin adjustment: {body.reason}",
        )
    else:
        # Deduct
        from app.core.access_control import deduct_credits
        new_balance = await deduct_credits(
            db, body.user_id, abs(body.amount),
            description=f"Admin adjustment: {body.reason}",
        )

    await db.commit()
    # Re-fetch
    cb_result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == body.user_id)
    )
    cb = cb_result.scalar_one_or_none()
    if not cb:
        return CreditBalanceResponse(balance=0, lifetime_earned=0, lifetime_used=0)
    return cb


@credits_router.get("/admin/{user_id}/transactions", response_model=list[CreditTransactionResponse])
async def admin_get_user_transactions(
    user_id: str,
    limit: int = Query(default=50, le=200),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin views a user's credit transactions."""
    result = await db.execute(
        select(CreditTransaction)
        .where(CreditTransaction.user_id == user_id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


# ── Admin: Manage subscriptions ───────────────────────────────────────

@subscriptions_router.post("/admin/assign", response_model=MessageResponse)
async def admin_assign_plan(
    body: SubscribeRequest,
    user_id: str = Query(...),
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin assigns a plan to a user."""
    # Verify user
    user_result = await db.execute(select(User).where(User.id == user_id))
    target = user_result.scalar_one_or_none()
    if not target:
        raise NotFoundError("User")

    # Find plan
    plan_result = await db.execute(select(Plan).where(Plan.code == body.plan_code))
    plan = plan_result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    # Cancel existing
    existing = await db.execute(
        select(UserSubscription).where(
            UserSubscription.user_id == target.id,
            UserSubscription.status == "active",
        )
    )
    for old_sub in existing.scalars().all():
        old_sub.status = "cancelled"
        old_sub.cancelled_at = datetime.now(timezone.utc)

    # Create new
    sub = UserSubscription(
        user_id=target.id,
        plan_id=plan.id,
        billing_cycle=body.billing_cycle,
        status="active",
    )
    db.add(sub)

    # Grant credits
    if plan.ai_credits_monthly > 0:
        await grant_credits(
            db, target.id, plan.ai_credits_monthly,
            tx_type="plan_grant",
            description=f"Admin assigned {plan.name} plan",
        )

    await db.commit()
    logger.info("admin_assign_plan", admin=str(admin.id), user=str(target.id), plan=plan.code)
    return MessageResponse(message=f"Assigned {plan.name} plan to user")


# ── Admin: Plan CRUD ──────────────────────────────────────────────────

admin_plans_router = APIRouter(prefix="/admin/plans", tags=["admin-plans"])


@admin_plans_router.get("", response_model=list[PlanResponse])
async def admin_list_all_plans(
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin lists ALL plans (including inactive)."""
    result = await db.execute(select(Plan).order_by(Plan.sort_order))
    return result.scalars().all()


@admin_plans_router.post("", response_model=PlanResponse, status_code=201)
async def admin_create_plan(
    body: PlanCreateRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin creates a new plan."""
    existing = await db.execute(select(Plan).where(Plan.code == body.code))
    if existing.scalar_one_or_none():
        raise ConflictError("Plan with this code already exists")

    plan = Plan(**body.model_dump())
    db.add(plan)
    await db.commit()
    await db.refresh(plan)
    logger.info("plan_created", plan=plan.code, admin=str(admin.id))
    return plan


@admin_plans_router.put("/{plan_id}", response_model=PlanResponse)
async def admin_update_plan(
    plan_id: str,
    body: PlanUpdateRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin updates a plan's details."""
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(plan, key, value)

    await db.commit()
    await db.refresh(plan)
    logger.info("plan_updated", plan=plan.code, admin=str(admin.id))
    return plan


@admin_plans_router.delete("/{plan_id}", response_model=MessageResponse)
async def admin_delete_plan(
    plan_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin soft-deletes (deactivates) a plan."""
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    plan.is_active = False
    await db.commit()
    logger.info("plan_deactivated", plan=plan.code, admin=str(admin.id))
    return MessageResponse(message=f"Plan '{plan.name}' deactivated")


# ── Admin: Plan ↔ Module management ──────────────────────────────────

@admin_plans_router.get("/{plan_id}/modules", response_model=list[PlanModuleResponse])
async def admin_get_plan_modules(
    plan_id: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin gets all modules for a plan."""
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    pm_result = await db.execute(
        select(PlanModule, Module)
        .join(Module, Module.id == PlanModule.module_id)
        .where(PlanModule.plan_id == plan.id)
        .order_by(Module.sort_order)
    )
    rows = pm_result.all()
    modules = []
    for pm, mod in rows:
        modules.append(PlanModuleResponse(
            module=ModuleResponse.model_validate(mod),
            access_level=pm.access_level,
            quota_limit=pm.quota_limit,
        ))
    return modules


@admin_plans_router.post("/{plan_id}/modules", response_model=MessageResponse)
async def admin_add_plan_module(
    plan_id: str,
    body: PlanModuleAssignRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin adds a module to a plan."""
    result = await db.execute(select(Plan).where(Plan.id == plan_id))
    plan = result.scalar_one_or_none()
    if not plan:
        raise NotFoundError("Plan")

    mod_result = await db.execute(select(Module).where(Module.code == body.module_code))
    mod = mod_result.scalar_one_or_none()
    if not mod:
        raise NotFoundError("Module")

    # Check if already assigned
    existing = await db.execute(
        select(PlanModule).where(
            PlanModule.plan_id == plan.id,
            PlanModule.module_id == mod.id,
        )
    )
    if existing.scalar_one_or_none():
        raise ConflictError("Module already assigned to this plan")

    pm = PlanModule(
        plan_id=plan.id,
        module_id=mod.id,
        access_level=body.access_level,
        quota_limit=body.quota_limit,
    )
    db.add(pm)
    await db.commit()
    logger.info("plan_module_added", plan=plan.code, module=mod.code, admin=str(admin.id))
    return MessageResponse(message=f"Module '{mod.name}' added to plan '{plan.name}'")


@admin_plans_router.delete("/{plan_id}/modules/{module_code}", response_model=MessageResponse)
async def admin_remove_plan_module(
    plan_id: str,
    module_code: str,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin removes a module from a plan."""
    mod_result = await db.execute(select(Module).where(Module.code == module_code))
    mod = mod_result.scalar_one_or_none()
    if not mod:
        raise NotFoundError("Module")

    pm_result = await db.execute(
        select(PlanModule).where(
            PlanModule.plan_id == plan_id,
            PlanModule.module_id == mod.id,
        )
    )
    pm = pm_result.scalar_one_or_none()
    if not pm:
        raise NotFoundError("Plan-Module assignment")

    await db.delete(pm)
    await db.commit()
    logger.info("plan_module_removed", plan_id=plan_id, module=module_code, admin=str(admin.id))
    return MessageResponse(message=f"Module '{mod.name}' removed from plan")


# ── Admin: Module management ─────────────────────────────────────────

@admin_plans_router.put("/modules/{module_id}", response_model=ModuleResponse)
async def admin_update_module(
    module_id: str,
    body: ModuleUpdateRequest,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db_session),
):
    """Admin updates a module's details."""
    result = await db.execute(select(Module).where(Module.id == module_id))
    mod = result.scalar_one_or_none()
    if not mod:
        raise NotFoundError("Module")

    update_data = body.model_dump(exclude_none=True)
    for key, value in update_data.items():
        setattr(mod, key, value)

    await db.commit()
    await db.refresh(mod)
    logger.info("module_updated", module=mod.code, admin=str(admin.id))
    return mod
