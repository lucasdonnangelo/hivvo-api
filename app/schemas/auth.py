import datetime as dt
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class RegisterRequest(BaseModel):
    email: str
    nome_completo: str = Field(min_length=2)
    password: str

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.strip().lower()

    @field_validator("nome_completo", mode="before")
    @classmethod
    def strip_espacos(cls, v):
        # mode="before": as constraints (min_length) precisam ver o valor JÁ
        # aparado, senão "  " passaria por min_length=2 e gravaria nome em branco.
        # Mesmo contrato do UpdateMeRequest.
        return v.strip() if isinstance(v, str) else v

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
    # Ambos opcionais: o handler aplica só o que veio (exclude_unset). A UI do
    # Perfil manda apenas nome_completo; username segue editável para um cliente
    # futuro (o campo é interno, auto-gerado do e-mail — PLANO_PERFIL_CONFIG).
    nome_completo: Optional[str] = Field(default=None, min_length=2)
    username: Optional[str] = Field(default=None, min_length=2)

    @field_validator("nome_completo", "username", mode="before")
    @classmethod
    def strip_espacos(cls, v):
        # mode="before": as constraints (min_length) precisam ver o valor JÁ
        # aparado, senão "  " passaria por min_length=2 e gravaria nome em branco.
        return v.strip() if isinstance(v, str) else v

    @model_validator(mode="after")
    def ao_menos_um_campo(self):
        # Evita PUT no-op ({}) e barra o null explícito ({"nome_completo": null}),
        # que tem o campo "set" com valor None: aplicá-lo violaria o NOT NULL da
        # coluna e viraria 500. Aqui vira 422.
        if self.nome_completo is None and self.username is None:
            raise ValueError("Informe ao menos um campo: nome_completo ou username.")
        return self


class ChangePasswordRequest(BaseModel):
    senha_atual: str
    nova_senha: str = Field(min_length=8)


class DeleteMeRequest(BaseModel):
    # F-07: reautenticação — um cookie sozinho não pode excluir a conta.
    password: str


class ResetDataRequest(BaseModel):
    # "Começar do zero" é irreversível: reautenticação, mesmo padrão do delete_me.
    password: str


class ResetDataResponse(BaseModel):
    """Recibo do reset — quantas linhas saíram de cada tabela.

    Vem de graça: o rowcount já volta do próprio DELETE, sem SELECT extra.
    """

    parcelas: int
    transacoes: int
    pagamentos_fatura: int
    cartoes: int
    recorrencia_vigencias: int
    recorrencias: int
    chat_messages: int


class ForgotPasswordRequest(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def email_lowercase(cls, v: str) -> str:
        return v.strip().lower()


class ResetPasswordRequest(BaseModel):
    token: str
    nova_senha: str = Field(min_length=8)
