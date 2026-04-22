from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    full_name: str | None = None

    @field_validator("password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: str
    full_name: str | None
    tier: str

    # Press Office fields
    handle: str | None = None
    reduced_motion: bool = False
    email_notices: bool = True
    weekly_brief: bool = False
    default_units: str = "inr"
    default_reader_count: int = 10000
    default_scenario: str = "base"
    default_aov: float = 1000.0
    keep_past_results: bool = True

    model_config = {"from_attributes": True}


class UserUpdate(BaseModel):
    """
    PATCH payload for the authenticated user's Press Office settings.
    All fields optional — only the ones provided are written.
    """

    full_name: str | None = None
    email: EmailStr | None = None
    handle: str | None = Field(default=None, max_length=64)

    reduced_motion: bool | None = None
    email_notices: bool | None = None
    weekly_brief: bool | None = None
    default_units: str | None = Field(default=None, pattern=r"^(inr|usd|eur)$")

    default_reader_count: int | None = Field(default=None, ge=1000, le=10000)
    default_scenario: str | None = Field(
        default=None, pattern=r"^(base|recession|viral|competitor)$"
    )
    default_aov: float | None = Field(default=None, ge=0)
    keep_past_results: bool | None = None


class PasswordChange(BaseModel):
    current_password: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def password_strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters")
        return v


class AccountDelete(BaseModel):
    password: str


class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class MessageResponse(BaseModel):
    message: str
