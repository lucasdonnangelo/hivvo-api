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
    # #6 — a tela de Configurações precisa do estado ATUAL para desenhar o
    # toggle. Sem isto, a única forma de a UI saber seria assumir o default,
    # e um toggle que mostra o valor errado é pior que nenhum toggle.
    notificar_vencimento: bool

    model_config = {"from_attributes": True}


class UpdateMeRequest(BaseModel):
    # Ambos opcionais: o handler aplica só o que veio (exclude_unset). A UI do
    # Perfil manda apenas nome_completo; username segue editável para um cliente
    # futuro (o campo é interno, auto-gerado do e-mail — PLANO_PERFIL_CONFIG).
    nome_completo: Optional[str] = Field(default=None, min_length=2)
    username: Optional[str] = Field(default=None, min_length=2)
    # #6 — o toggle de Configurações. Booleano puro: ligar/desligar, sem
    # "quantos dias" e sem "por cartão" (decisão de produto).
    notificar_vencimento: Optional[bool] = None

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
        #
        # ⚠️ CAMPO NOVO TEM QUE ENTRAR NESTA LISTA. Sem `notificar_vencimento`
        # aqui, o payload que a tela mais manda — `{"notificar_vencimento":
        # false}`, sozinho — tomaria 422 dizendo "informe ao menos um campo",
        # com o campo informado. O erro não aparece em teste de schema que só
        # exercita nome/username; aparece no primeiro clique no toggle.
        if (
            self.nome_completo is None
            and self.username is None
            and self.notificar_vencimento is None
        ):
            raise ValueError(
                "Informe ao menos um campo: nome_completo, username ou "
                "notificar_vencimento."
            )
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
    # Guards de idempotência: saem junto porque de pé travam em silêncio o que
    # guardam — o 409 do lote impediria REIMPORTAR os mesmos PDFs depois de
    # zerar, e a linha de notificação faria o aviso do dia ser pulado. Toda
    # tabela dessas que entra na purga precisa de uma chave AQUI: o Pydantic
    # descarta chave extra sem erro e o recibo mentiria para menos.
    import_fatura_lote: int
    import_extrato_lote: int
    notificacao_envio: int
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
