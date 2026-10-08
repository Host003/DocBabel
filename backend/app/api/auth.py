from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.security import get_password_hash, verify_password, create_access_token
from app.models.models import User, UserRole
from app.schemas.schemas import (
    ChangePasswordRequest,
    LoginRequest,
    RegisterRequest,
    Token,
    UpdateEmailRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["认证"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    # check duplicates
    result = await db.execute(
        select(User).where((User.username == req.username) | (User.email == req.email))
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名或邮箱已存在")

    # If no active admin exists, the next registered user becomes admin as a recovery path.
    admin_result = await db.execute(
        select(User.id)
        .where(User.role == UserRole.admin, User.is_active.is_(True))
        .limit(1)
    )
    role = UserRole.admin if admin_result.scalar_one_or_none() is None else UserRole.user

    user = User(
        username=req.username,
        email=req.email,
        hashed_password=get_password_hash(req.password),
        role=role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=Token)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.username == req.username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="账户已被禁用")
    token = create_access_token(user.username)
    return Token(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(current_user: User = Depends(get_current_user)):
    return current_user


@router.put("/me/password", response_model=UserOut)
async def change_my_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """修改自己的密码。JWT 是无状态的，旧 token 在过期前依然有效 —
    若要强制退出其他设备，需要额外实现 token 黑名单，这里先接受这个边界。"""
    if not verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    current_user.hashed_password = get_password_hash(req.new_password)
    await db.commit()
    await db.refresh(current_user)
    return current_user


@router.put("/me/email", response_model=UserOut)
async def change_my_email(
    req: UpdateEmailRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not verify_password(req.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="当前密码不正确")
    if req.email == current_user.email:
        return current_user
    dup = (await db.execute(
        select(User.id).where(User.email == req.email).limit(1)
    )).scalar_one_or_none()
    if dup is not None:
        raise HTTPException(status_code=400, detail="该邮箱已被其他用户使用")
    current_user.email = req.email
    await db.commit()
    await db.refresh(current_user)
    return current_user
