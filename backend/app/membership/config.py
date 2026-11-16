from functools import lru_cache
from urllib.parse import urlsplit

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url

from app.config import BACKEND_DIR


class MembershipSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="VDS_", env_file=BACKEND_DIR / ".env", extra="ignore",
        env_ignore_empty=True, hide_input_in_errors=True,
    )

    membership_db_url: SecretStr | None = None
    membership_origin: str = "http://127.0.0.1:5173"
    membership_checkout_enabled: bool = False
    stripe_mode: str = "disabled"
    stripe_secret_key: SecretStr | None = None
    stripe_publishable_key: str = ""
    stripe_webhook_secret: SecretStr | None = None
    stripe_month_price_id: str = ""
    stripe_year_price_id: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_from: str = ""
    smtp_username: str = ""
    smtp_password: SecretStr | None = None

    @property
    def enabled(self) -> bool:
        return self.membership_db_url is not None

    @property
    def loopback(self) -> bool:
        return urlsplit(self.membership_origin).hostname in {"127.0.0.1", "localhost", "::1"}

    @property
    def secure_cookie(self) -> bool:
        return self.membership_origin.startswith("https://")

    @model_validator(mode="after")
    def validate_config(self):
        self.membership_origin = self.membership_origin.rstrip("/")
        origin = urlsplit(self.membership_origin)
        if (
            origin.scheme not in {"http", "https"} or not origin.hostname
            or origin.username or origin.path or origin.query or origin.fragment
            or (not self.secure_cookie and not self.loopback)
        ):
            raise ValueError("会员站点需配置完整的 HTTPS Origin，本机可使用 HTTP")
        if self.stripe_mode not in {"disabled", "mock", "sandbox", "live"}:
            raise ValueError("VDS_STRIPE_MODE 不受支持")
        if self.smtp_security not in {"starttls", "tls", "plain"}:
            raise ValueError("VDS_SMTP_SECURITY 不受支持")
        if self.smtp_host and self.smtp_security == "plain" and self.smtp_host not in {
            "127.0.0.1", "localhost", "::1"
        }:
            raise ValueError("明文 SMTP 仅支持回环地址")
        if self.enabled:
            database = make_url(self.membership_db_url.get_secret_value())
            if database.drivername != "mysql+pymysql" or not database.database:
                raise ValueError("会员数据库需使用 mysql+pymysql URL，并指定库名")
        elif self.stripe_mode != "disabled" or self.membership_checkout_enabled:
            raise ValueError("请先配置会员数据库")
        if self.stripe_mode == "mock":
            if (
                not self.loopback
                or database.host not in {"127.0.0.1", "localhost", "::1"}
                or database.database != "clipnest_test"
                or self.smtp_host not in {"127.0.0.1", "localhost", "::1"}
            ):
                raise ValueError("模拟收银台仅支持本机站点、本机 SMTP 和 clipnest_test")
        if self.stripe_mode in {"sandbox", "live"}:
            key = self.stripe_secret_key.get_secret_value() if self.stripe_secret_key else ""
            prefix = "sk_live_" if self.stripe_mode == "live" else "sk_test_"
            if not key.startswith(prefix):
                raise ValueError("Stripe API 密钥与当前环境不匹配")
            if any(not price.startswith("price_") for price in (
                self.stripe_month_price_id, self.stripe_year_price_id
            )) or self.stripe_month_price_id == self.stripe_year_price_id:
                raise ValueError("请分别配置月卡和年卡的 Stripe Price ID")
        if self.stripe_mode != "disabled":
            secret = self.stripe_webhook_secret.get_secret_value() if self.stripe_webhook_secret else ""
            if not secret.startswith("whsec_"):
                raise ValueError("请配置 Stripe Webhook 签名密钥")
        if self.stripe_mode == "live" and (not self.secure_cookie or self.loopback):
            raise ValueError("Stripe 正式环境需要公网 HTTPS Origin")
        if self.membership_checkout_enabled and (
            self.stripe_mode == "disabled" or not self.smtp_host or not self.smtp_from
        ):
            raise ValueError("开放购买前请配置 Stripe 和发信服务")
        return self


@lru_cache
def settings() -> MembershipSettings:
    return MembershipSettings()
