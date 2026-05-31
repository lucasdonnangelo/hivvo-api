import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RegisterRequest(BaseModel):
    email: str
    username: str
    nome_completo: str
    password: str

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("password")
    @classmethod
    def password_min_length(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("Senha deve ter ao menos 8 caracteres")
        return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class UserResponse(BaseModel):
    id: int
    email: str
    username: str
    nome_completo: str
    criado_em: dt.datetime
    ativo: bool

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    username: str = Field(min_length=2)


class ChangePasswordRequest(BaseModel):
    senha_atual: str
    nova_senha: str = Field(min_length=8)


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    nova_senha: str = Field(min_length=8)
