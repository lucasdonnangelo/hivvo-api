import datetime as dt
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

# Mensagem ÚNICA para create (validator) e update (router, que mescla com o
# cartão atual) — o front mostra o detail/msg direto ao usuário.
MSG_VENCIMENTO_ANTES_DO_FECHAMENTO = (
    "Quando o vencimento é no mesmo mês do fechamento, o dia de vencimento "
    "precisa ser maior que o do fechamento. Se vence no mês seguinte, escolha "
    "'Mês seguinte ao fechamento'."
)


def fechamento_vencimento_coerentes(
    dia_fechamento: Optional[int],
    dia_vencimento: Optional[int],
    mes_offset_vencimento: Optional[int],
) -> bool:
    """offset 0 ("mesmo mês") exige vencimento DEPOIS do fechamento — a fatura
    não pode vencer antes de fechar. offset >= 1 ("mês seguinte"): qualquer par
    de dias é válido (o mês virou entre fechar e vencer). Dias ausentes (débito
    não tem fatura; crédito sem datas ainda é aceito) não acionam a regra.
    """
    if mes_offset_vencimento != 0:
        return True
    if dia_fechamento is None or dia_vencimento is None:
        return True
    return dia_vencimento > dia_fechamento


class CartaoCreate(BaseModel):
    nome: str = Field(..., max_length=200)  # F-22
    tipo: str = Field(..., max_length=20)
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: int = 1

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: str) -> str:
        if v not in ("Crédito", "Débito", "Ambos"):
            raise ValueError("tipo deve ser 'Crédito', 'Débito' ou 'Ambos'")
        return v

    @field_validator("dia_vencimento", "dia_fechamento", mode="before")
    @classmethod
    def dia_valido(cls, v):
        if v is not None and not (1 <= int(v) <= 31):
            raise ValueError("dia deve estar entre 1 e 31")
        return v

    @field_validator("mes_offset_vencimento", mode="before")
    @classmethod
    def offset_nao_negativo(cls, v):
        # Débito não tem fatura: o frontend manda null nos 4 campos de fatura.
        # limite/dias são Optional e engolem o null; mes_offset é int não-anulável,
        # então um null explícito dava 422 ("Input should be a valid integer") e
        # travava a criação de cartão de débito. Coagir None → default 1 (inócuo,
        # débito nunca usa offset) mantém a coluna int não-anulável do DB e alinha o
        # campo aos irmãos, sem afrouxar validação (negativo continua rejeitado).
        if v is None:
            return 1
        if int(v) < 0:
            raise ValueError("mes_offset_vencimento deve ser >= 0")
        return v

    @model_validator(mode="after")
    def vencimento_depois_do_fechamento(self) -> "CartaoCreate":
        if not fechamento_vencimento_coerentes(
            self.dia_fechamento, self.dia_vencimento, self.mes_offset_vencimento
        ):
            raise ValueError(MSG_VENCIMENTO_ANTES_DO_FECHAMENTO)
        return self


# CartaoUpdate NÃO tem o model_validator acima de propósito: o update é PARCIAL
# (um campo da regra pode vir sozinho) — a mescla com os valores atuais do cartão
# e a validação do RESULTADO acontecem no router (update_card), e só quando o
# update toca algum campo da regra.
class CartaoUpdate(BaseModel):
    nome: Optional[str] = Field(None, max_length=200)  # F-22
    tipo: Optional[str] = Field(None, max_length=20)
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: Optional[int] = None
    ativo: Optional[bool] = None

    @field_validator("tipo")
    @classmethod
    def tipo_valido(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("Crédito", "Débito", "Ambos"):
            raise ValueError("tipo deve ser 'Crédito', 'Débito' ou 'Ambos'")
        return v

    @field_validator("dia_vencimento", "dia_fechamento", mode="before")
    @classmethod
    def dia_valido(cls, v):
        if v is not None and not (1 <= int(v) <= 31):
            raise ValueError("dia deve estar entre 1 e 31")
        return v

    @field_validator("mes_offset_vencimento")
    @classmethod
    def offset_nao_negativo(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v < 0:
            raise ValueError("mes_offset_vencimento deve ser >= 0")
        return v


class CartaoResponse(BaseModel):
    id: int
    usuario_id: int
    nome: str
    tipo: str
    limite: Optional[Decimal] = None
    dia_vencimento: Optional[int] = None
    dia_fechamento: Optional[int] = None
    mes_offset_vencimento: int
    ativo: bool
    criado_em: dt.date

    model_config = {"from_attributes": True}


class CartaoComFaturaResponse(CartaoResponse):
    fatura_aberta_total: Optional[Decimal] = None
    fatura_aberta_mes: Optional[int] = None
    fatura_aberta_ano: Optional[int] = None
    fatura_aberta_vencimento: Optional[dt.date] = None
    # True quando o cartão tem compra lançada (parcela não cancelada ou avulsa
    # de cartão) em qualquer competência → o frontend desabilita os campos de
    # data (dia_fechamento/dia_vencimento) no form de edição, pois o backend os
    # bloqueia (alterá-los corromperia o fatura_mes já materializado).
    tem_lancamentos: bool = False
