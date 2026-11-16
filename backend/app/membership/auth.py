import hashlib
import logging
import secrets
import smtplib
import ssl
import time
from datetime import timedelta
from email.message import EmailMessage
from urllib.parse import urlencode
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.mysql import insert

from app.membership.config import settings
from app.membership.store import LoginSession, MailToken, RateBucket, User, db, lock_user, utcnow


router = APIRouter(prefix="/api/account", tags=["account"])
logger = logging.getLogger(__name__)
COOKIE = "clipnest_session"
SESSION_SECONDS = 14 * 86400
hasher = PasswordHasher()
DUMMY_HASH = hasher.hash(secrets.token_urlsafe(32))


class EmailInput(BaseModel):
    email: EmailStr


class Credentials(EmailInput):
    password: str = Field(min_length=1, max_length=128)


class TokenInput(BaseModel):
    token: str = Field(min_length=30, max_length=100)


class PasswordReset(TokenInput):
    password: str = Field(min_length=12, max_length=128)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def same_origin(request: Request) -> None:
    if request.headers.get("origin") != settings().membership_origin:
        raise HTTPException(403, "请求来源不受信任")


def account_write(request: Request) -> None:
    if not settings().enabled:
        raise HTTPException(503, "账号服务暂未开放")
    same_origin(request)


def throttle(request: Request, action: str, email: str, limit: int) -> None:
    minute = int(time.time()) // 60
    ip = request.client.host if request.client else "unknown"
    blocked = False
    with db().begin() as session:
        keys = [(f"ip:{ip}", limit * 4)]
        if email:
            keys.append((f"email:{email}", limit))
        for key, cap in keys:
            key_hash = digest(f"{minute}:{action}:{key}")
            stmt = insert(RateBucket).values(digest=key_hash, minute=minute, count=1)
            session.execute(stmt.on_duplicate_key_update(count=RateBucket.count + 1))
            bucket = session.get(RateBucket, key_hash)
            blocked = blocked or bucket.count > cap
    if blocked:
        raise HTTPException(429, "操作过于频繁，请稍后再试")


def signed_in_user(request: Request) -> User | None:
    token = request.cookies.get(COOKIE)
    if not settings().enabled or not token or len(token) > 100:
        return None
    with db()() as session:
        return session.scalar(select(User).join(LoginSession).where(
            LoginSession.digest == digest(token), LoginSession.expires_at > utcnow()
        ))


def require_user(request: Request, *, verified: bool = False) -> User:
    user = signed_in_user(request)
    if user is None:
        raise HTTPException(401, "请先登录")
    if verified and not user.verified:
        raise HTTPException(403, "请先验证邮箱")
    return user


def send_link(email: str, purpose: str, token: str) -> None:
    config = settings()
    link = f"{config.membership_origin}/#{urlencode({'account': purpose, 'token': token})}"
    label = "验证邮箱" if purpose == "verify" else "重置密码"
    message = EmailMessage()
    message["From"] = config.smtp_from
    message["To"] = email
    message["Subject"] = f"ClipNest · {label}"
    message.set_content(f"请在 30 分钟内打开以下链接完成{label}：\n{link}\n")
    try:
        if config.smtp_security == "tls":
            smtp = smtplib.SMTP_SSL(config.smtp_host, config.smtp_port, timeout=8, context=ssl.create_default_context())
        else:
            smtp = smtplib.SMTP(config.smtp_host, config.smtp_port, timeout=8)
        with smtp:
            if config.smtp_security == "starttls":
                smtp.starttls(context=ssl.create_default_context())
            if config.smtp_username:
                smtp.login(config.smtp_username, config.smtp_password.get_secret_value() if config.smtp_password else "")
            smtp.send_message(message)
    except (OSError, smtplib.SMTPException):
        logger.warning("ClipNest 账号邮件发送失败，类型=%s", purpose)


def require_mail() -> None:
    if not settings().smtp_host or not settings().smtp_from:
        raise HTTPException(503, "账号发信服务未配置")


def add_mail_token(session, user: User, purpose: str) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(MailToken(
        digest=digest(raw), user_id=user.id, purpose=purpose,
        expires_at=utcnow() + timedelta(minutes=30),
    ))
    return raw


@router.post("/register")
def register(payload: Credentials, request: Request):
    account_write(request)
    require_mail()
    email = payload.email.casefold()
    throttle(request, "register", email, 3)
    if len(payload.password) < 12:
        raise HTTPException(422, "密码至少需要 12 个字符")
    password_hash = hasher.hash(payload.password)
    with db().begin() as session:
        stmt = insert(User).values(id=str(uuid4()), email=email, password_hash=password_hash, verified=False)
        session.execute(stmt.on_duplicate_key_update(id=User.id))
        user = session.scalar(select(User).where(User.email == email).with_for_update())
        token = add_mail_token(session, user, "verify") if not user.verified else None
    if token:
        send_link(email, "verify", token)
    return {"ok": True}


@router.post("/login")
def login(payload: Credentials, request: Request, response: Response):
    account_write(request)
    email = payload.email.casefold()
    throttle(request, "login", email, 10)
    with db()() as session:
        candidate = session.scalar(select(User).where(User.email == email))
    try:
        hasher.verify(candidate.password_hash if candidate else DUMMY_HASH, payload.password)
    except VerifyMismatchError:
        raise HTTPException(401, "邮箱或密码错误") from None
    if not candidate:
        raise HTTPException(401, "邮箱或密码错误")
    token = secrets.token_urlsafe(32)
    with db().begin() as session:
        user = lock_user(session, candidate.id)
        if not user or user.password_hash != candidate.password_hash:
            raise HTTPException(401, "请重新登录")
        if hasher.check_needs_rehash(candidate.password_hash):
            user.password_hash = hasher.hash(payload.password)
        old = request.cookies.get(COOKIE)
        if old:
            session.execute(delete(LoginSession).where(LoginSession.digest == digest(old)))
        session.add(LoginSession(
            digest=digest(token), user_id=user.id, expires_at=utcnow() + timedelta(seconds=SESSION_SECONDS)
        ))
    response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True,
                        secure=settings().secure_cookie, samesite="lax", path="/api")
    return {"ok": True}


@router.post("/logout")
def logout(request: Request, response: Response):
    account_write(request)
    token = request.cookies.get(COOKIE)
    if token:
        with db().begin() as session:
            session.execute(delete(LoginSession).where(LoginSession.digest == digest(token)))
    response.delete_cookie(COOKIE, path="/api", secure=settings().secure_cookie, httponly=True)
    return {"ok": True}


def issue_link(request: Request, email: str, purpose: str):
    account_write(request)
    require_mail()
    email = email.casefold()
    throttle(request, purpose, email, 3)
    with db().begin() as session:
        user = session.scalar(select(User).where(User.email == email).with_for_update())
        token = add_mail_token(session, user, purpose) if user and (purpose == "reset" or not user.verified) else None
    if token:
        send_link(email, purpose, token)
    return {"ok": True}


@router.post("/verification-email")
def resend(payload: EmailInput, request: Request):
    return issue_link(request, payload.email, "verify")


@router.post("/password-reset-email")
def forgot(payload: EmailInput, request: Request):
    return issue_link(request, payload.email, "reset")


def consume(raw: str, purpose: str, password: str, password_hash: str | None = None) -> None:
    with db().begin() as session:
        token = session.get(MailToken, digest(raw))
        user = lock_user(session, token.user_id) if token else None
        if user:
            token = session.scalar(select(MailToken).where(
                MailToken.digest == digest(raw)
            ).with_for_update().execution_options(populate_existing=True))
        if not user or not token or token.purpose != purpose or token.expires_at <= utcnow():
            raise HTTPException(400, "链接已失效，请重新发送邮件")
        if purpose == "verify":
            try:
                hasher.verify(user.password_hash, password)
            except VerifyMismatchError:
                raise HTTPException(401, "注册密码错误，请重试或通过邮件重置密码") from None
            user.verified = True
        else:
            user.password_hash = password_hash
            user.verified = True
            session.execute(delete(LoginSession).where(LoginSession.user_id == user.id))
        session.execute(delete(MailToken).where(MailToken.user_id == user.id, MailToken.purpose == purpose))


@router.post("/verify")
def verify(payload: PasswordReset, request: Request):
    account_write(request)
    throttle(request, "consume-verify", "", 30)
    consume(payload.token, "verify", payload.password)
    return {"ok": True}


@router.post("/password-reset")
def reset(payload: PasswordReset, request: Request):
    account_write(request)
    throttle(request, "consume-reset", "", 30)
    consume(payload.token, "reset", payload.password, hasher.hash(payload.password))
    return {"ok": True}
