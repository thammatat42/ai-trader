"""Module access control – check plan-based permissions and credit availability."""

from datetime import datetime, timezone

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.core.dependencies import get_current_user
from app.core.exceptions import ForbiddenError
from app.models.credit_balance import CreditBalance
from app.models.credit_transaction import CreditTransaction
from app.models.module import Module
from app.models.plan import Plan
from app.models.plan_module import PlanModule
from app.models.user import User
from app.models.user_subscription import UserSubscription


async def _get_user_plan(db: AsyncSession, user: User) -> Plan | None:
    """Return the user's active plan (or None for admins / no subscription)."""
    result = await db.execute(
        select(Plan)
        .join(UserSubscription, UserSubscription.plan_id == Plan.id)
        .where(
            UserSubscription.user_id == user.id,
            UserSubscription.status == "active",
        )
        .order_by(UserSubscription.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _get_plan_module(
    db: AsyncSession, plan_id, module_code: str
) -> PlanModule | None:
    result = await db.execute(
        select(PlanModule)
        .join(Module, Module.id == PlanModule.module_id)
        .where(PlanModule.plan_id == plan_id, Module.code == module_code)
    )
    return result.scalar_one_or_none()


def require_module(module_code: str):
    """Dependency: ensure current user's plan includes the given module."""

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        # Admins bypass module checks
        if user.role == "admin":
            return user

        plan = await _get_user_plan(db, user)
        if not plan:
            raise ForbiddenError(
                f"No active subscription. Please subscribe to access this feature."
            )

        pm = await _get_plan_module(db, plan.id, module_code)
        if not pm:
            raise ForbiddenError(
                f"Your {plan.name} plan does not include this feature. Please upgrade."
            )
        return user

    return _check


async def get_user_credits(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db_session),
) -> int:
    """Return current credit balance for the user."""
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user.id)
    )
    cb = result.scalar_one_or_none()
    return cb.balance if cb else 0


def require_credits(amount: int = 1):
    """Dependency: ensure user has enough AI credits."""

    async def _check(
        user: User = Depends(get_current_user),
        db: AsyncSession = Depends(get_db_session),
    ) -> User:
        if user.role == "admin":
            return user

        result = await db.execute(
            select(CreditBalance).where(CreditBalance.user_id == user.id)
        )
        cb = result.scalar_one_or_none()
        balance = cb.balance if cb else 0

        if balance < amount:
            raise ForbiddenError(
                f"Insufficient AI credits ({balance} available, {amount} required). "
                "Please upgrade your plan or purchase more credits."
            )
        return user

    return _check


async def deduct_credits(
    db: AsyncSession,
    user_id,
    amount: int,
    description: str | None = None,
    reference_id: str | None = None,
) -> int:
    """Deduct credits from a user's balance. Returns new balance."""
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user_id)
    )
    cb = result.scalar_one_or_none()
    if not cb:
        return 0

    cb.balance = max(0, cb.balance - amount)
    cb.lifetime_used += amount
    cb.updated_at = datetime.now(timezone.utc)

    tx = CreditTransaction(
        user_id=user_id,
        amount=-amount,
        balance_after=cb.balance,
        tx_type="ai_usage",
        description=description,
        reference_id=reference_id,
    )
    db.add(tx)
    await db.flush()
    return cb.balance


async def grant_credits(
    db: AsyncSession,
    user_id,
    amount: int,
    tx_type: str = "plan_grant",
    description: str | None = None,
) -> int:
    """Add credits to a user's balance. Returns new balance."""
    result = await db.execute(
        select(CreditBalance).where(CreditBalance.user_id == user_id)
    )
    cb = result.scalar_one_or_none()
    if not cb:
        cb = CreditBalance(user_id=user_id, balance=0, lifetime_earned=0, lifetime_used=0)
        db.add(cb)
        await db.flush()

    cb.balance += amount
    cb.lifetime_earned += amount
    cb.updated_at = datetime.now(timezone.utc)

    tx = CreditTransaction(
        user_id=user_id,
        amount=amount,
        balance_after=cb.balance,
        tx_type=tx_type,
        description=description,
    )
    db.add(tx)
    await db.flush()
    return cb.balance
