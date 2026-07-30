import unicodedata
from typing import Optional

from sqlmodel import Session, select

from app.models.category import CategoriaCustomizada
from app.schemas.category import CategoriaResponse

# O neutro do produto. Existe nos DOIS tipos em CATEGORIAS_PADRAO, então é
# sempre um fallback válido — e é o que a camada 1 da auto-categoria NUNCA
# aprende (default não é decisão; ver services/import_fatura/enriquecimento).
CATEGORIA_NEUTRA = "Outros"

# Categorias padrão do produto (Hivvo_Referencia §5). Compartilhadas entre o
# router de categorias e a sugestão por IA — única fonte, sem import entre routers.
CATEGORIAS_PADRAO: list[CategoriaResponse] = [
    CategoriaResponse(nome="Alimentação",  icone="🍔", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Moradia",      icone="🏠", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Transporte",   icone="🚗", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Saúde",        icone="💊", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Educação",     icone="📚", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Lazer",        icone="🎮", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Roupas",       icone="👕", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Assinaturas",  icone="📱", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Viagem",       icone="✈️",  tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Pets",         icone="🐾", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Outros",       icone="📦", tipo="despesa", is_padrao=True),
    CategoriaResponse(nome="Salário",      icone="💰", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Freelance",    icone="💻", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Investimentos",icone="📈", tipo="receita", is_padrao=True),
    # "Rendimentos" nasceu do import de EXTRATO (ACHADO 1: o "Rendimento
    # líquido" do resumo vira receita própria — PLANO_IMPORTACAO). Entra como
    # PADRÃO, e não como string solta na materialização, para (a) o picker do
    # frontend conhecê-la, (b) casar_categoria parar de rebaixá-la a "Outros" e
    # (c) a categorização em lote poder sugeri-la. Sem migration: a lista é
    # código.
    CategoriaResponse(nome="Rendimentos",  icone="💹", tipo="receita", is_padrao=True),
    CategoriaResponse(nome="Outros",       icone="📦", tipo="receita", is_padrao=True),
]


def nomes_categorias_do_usuario(
    session: Session, usuario_id: int, tipo: Optional[str] = None
) -> list[str]:
    """Categorias VÁLIDAS para o usuário: padrão + customizadas ativas.

    Fonte única do "universo de categorias que o cliente conhece" nas chamadas
    ao modelo — /ai/suggest-category (uma transação) e a categorização em LOTE
    do import de extrato (N linhas numa chamada). `tipo=None` traz os dois tipos
    (e então "Outros" aparece duas vezes, uma por tipo — irrelevante para o
    casamento; quem monta prompt deduplica).
    """
    nomes = [c.nome for c in CATEGORIAS_PADRAO if tipo is None or c.tipo == tipo]
    stmt = select(CategoriaCustomizada).where(
        CategoriaCustomizada.usuario_id == usuario_id,
        CategoriaCustomizada.ativa == True,  # noqa: E712
    )
    if tipo is not None:
        stmt = stmt.where(CategoriaCustomizada.tipo == tipo)
    for c in session.exec(stmt).all():
        if c.nome not in nomes:
            nomes.append(c.nome)
    return nomes


# --- Regras de lojista (camada 2 da auto-categoria) --------------------------
#
# Na fatura real o sinal mais forte NÃO é palavra-chave, é PREFIXO DE
# ADQUIRENTE: "IFD*40827151VICTORMA" parece lixo e é iFood. Estas tabelas são o
# que faz a auto-categoria funcionar na PRIMEIRA importação, quando o histórico
# do usuário (camada 1) ainda está vazio — o momento mais crítico do produto.
#
# Elas não precisam estar CERTAS, precisam ser um bom PRIOR: a camada 1
# personaliza por usuário, então quem discorda de uma entrada corrige uma vez e
# nunca mais a vê.


def _normalizar(bruto: str) -> str:
    """casefold + sem acento + só alfanumérico ("Pão de Açúcar" -> "paodeacucar").

    Mesma normalização de `import_extrato.persistencia.normalizar_banco` e de
    `import_extrato.enriquecimento._normalizar_nome` — unificar as três é uma
    limpeza à parte (mexeria em módulos fora deste diff).
    """
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFD", bruto) if unicodedata.category(c) != "Mn"
    )
    return "".join(ch for ch in sem_acento.casefold() if ch.isalnum())


# ADQUIRENTE: casa o token ANTES do primeiro "*" — a marca do intermediário que
# processou a compra, não do lojista. Só entra adquirente de VERTICAL CONHECIDA:
# MP* (MercadoPago), PAG*, CIELO* e afins são HORIZONTAIS (vendem qualquer
# coisa) e ficam de fora de propósito — regra ali seria adivinhação com cara de
# dado.
ADQUIRENTES: dict[str, str] = {
    "ifd": "Alimentação",       # iFood
    "ifood": "Alimentação",
    "kee": "Alimentação",       # Keeta
    "keeta": "Alimentação",
    "keetabr": "Alimentação",
    "99food": "Alimentação",
    "rappi": "Alimentação",
    "zig": "Lazer",             # ZIG (eventos/ingressos)
    "zigtickets": "Lazer",
    "uber": "Transporte",
    "microsoft": "Assinaturas",
    "google": "Assinaturas",
    "apple": "Assinaturas",
}

# PALAVRA-CHAVE genérica: substring na descrição normalizada. Valem em qualquer
# fatura de qualquer banco — nenhuma marca aqui.
#
# Nota de formato: a fatura da Itaú TRUNCA a descrição em ~20 chars e cola as
# palavras ("PONTOQUENTEPAESEDO"), por isso alguns radicais são curtos e
# aparentemente incompletos ("paesedo"). É deliberado.
KEYWORDS_GENERICAS: list[tuple[str, str]] = [
    # Alimentação
    ("supermerc", "Alimentação"), ("hipermerc", "Alimentação"),
    ("mercearia", "Alimentação"), ("mercadinho", "Alimentação"),
    ("hortifru", "Alimentação"), ("sacolao", "Alimentação"),
    ("quitanda", "Alimentação"), ("acougue", "Alimentação"),
    ("padaria", "Alimentação"), ("paesedo", "Alimentação"),
    ("panificad", "Alimentação"), ("confeitar", "Alimentação"),
    ("doceria", "Alimentação"), ("lanchonet", "Alimentação"),
    ("lanches", "Alimentação"), ("restaurante", "Alimentação"),
    ("pizzaria", "Alimentação"), ("pizza", "Alimentação"),
    ("churrasc", "Alimentação"), ("espeto", "Alimentação"),
    ("rotisseria", "Alimentação"), ("laticinio", "Alimentação"),
    ("cafeteria", "Alimentação"), ("sorveteria", "Alimentação"),
    ("pescado", "Alimentação"), ("peixaria", "Alimentação"),
    ("comedoria", "Alimentação"), ("adega", "Alimentação"),
    ("emporio", "Alimentação"), ("delicatess", "Alimentação"),
    # Transporte ("posto" sozinho está em KEYWORDS_INICIO — ver lá)
    ("autoposto", "Transporte"),
    ("combustiv", "Transporte"), ("automotiv", "Transporte"),
    ("lavarapido", "Transporte"), ("estacionamento", "Transporte"),
    ("parking", "Transporte"), ("pedagio", "Transporte"),
    ("autopecas", "Transporte"), ("borracharia", "Transporte"),
    # Saúde ("academia" é decisão de produto: gasto de saúde, não de lazer).
    # "otica" NÃO entra: casa dentro de "exótica"/"robótica"/"caótica" — foi
    # pega pelo test_categoria_inventada_pelo_modelo_cai_em_outros do extrato,
    # que classificou "Criptomoedas Exóticas" como Saúde. Radical curto demais.
    ("drogaria", "Saúde"), ("farmacia", "Saúde"), ("hospital", "Saúde"),
    ("clinica", "Saúde"), ("laborator", "Saúde"), ("odonto", "Saúde"),
    ("academia", "Saúde"),
    # Lazer ("esportes" = loja de artigos esportivos -> Lazer, não Roupas)
    ("cinema", "Lazer"), ("ingresso", "Lazer"), ("loterias", "Lazer"),
    ("loteria", "Lazer"), ("esportes", "Lazer"),
    # Assinaturas
    ("netflix", "Assinaturas"), ("spotify", "Assinaturas"),
    ("microsoft", "Assinaturas"), ("adobe", "Assinaturas"),
    ("openai", "Assinaturas"), ("disney", "Assinaturas"),
    ("amazonprime", "Assinaturas"), ("icloud", "Assinaturas"),
    # Pets
    ("petshop", "Pets"), ("agropet", "Pets"), ("veterinar", "Pets"),
]

# REDES NOMEADAS: marcas brasileiras. Portáteis entre usuários, mas é a lista
# que só cresce (manutenção). Separada das genéricas para dar para medir quanto
# da cobertura vem de cada metade — na Itaú real, 71,3% sai só das genéricas e
# 92,6% com estas.
KEYWORDS_REDES: list[tuple[str, str]] = [
    ("paodeacuca", "Alimentação"), ("carrefour", "Alimentação"),
    ("atacadao", "Alimentação"), ("assai", "Alimentação"),
    ("sondasuper", "Alimentação"), ("sondajacana", "Alimentação"),
    ("obahortifru", "Alimentação"), ("preciatta", "Alimentação"),
    ("oxxo", "Alimentação"), ("mcdonalds", "Alimentação"),
    ("arcosdourados", "Alimentação"), ("burgerking", "Alimentação"),
    ("subway", "Alimentação"), ("starbucks", "Alimentação"),
    ("outback", "Alimentação"), ("habibs", "Alimentação"),
    ("drogasil", "Saúde"), ("drogaraia", "Saúde"), ("paguemenos", "Saúde"),
    ("siriolibanes", "Saúde"), ("einstein", "Saúde"), ("smartfit", "Saúde"),
    ("ipiranga", "Transporte"), ("petrobras", "Transporte"),
    ("shellbox", "Transporte"),
]

# PALAVRA-CHAVE ANCORADA NO INÍCIO. Radical valioso demais para descartar e
# curto demais para casar no meio: "posto" identifica posto de combustível
# ("PostoDe", "POSTO SHELL") e casa dentro de "IMPOSTOS E ENCARGOS" — que é
# linha REAL de fatura — se não for ancorado. Só entra aqui o que precisa da
# âncora; a lista não deve crescer por conforto.
KEYWORDS_INICIO: list[tuple[str, str]] = [
    ("posto", "Transporte"),
]

_KEYWORDS = [(_normalizar(chave), alvo) for chave, alvo in KEYWORDS_GENERICAS + KEYWORDS_REDES]
_KEYWORDS_INICIO = [(_normalizar(chave), alvo) for chave, alvo in KEYWORDS_INICIO]


def validar_nome_categoria(nome: str, nomes: list[str]) -> Optional[str]:
    """O nome exato de `nomes` (preservando a grafia dele), ou None.

    Um lugar só para "esta categoria existe para este usuário, neste tipo?".
    Usado pelo alvo de toda regra e pela camada 1 — é o que faz o filtro de
    TIPO sair de graça: regra de despesa não sobrevive numa lista de receita.
    """
    for candidato in nomes:
        if nome.casefold() == candidato.casefold():
            return candidato
    return None


def casar_categoria_detalhado(entrada: str, nomes: list[str]) -> tuple[str, Optional[str]]:
    """(categoria, rótulo do passe que casou) — o motor; `casar_categoria` é a casca.

    Ordem: exato -> ADQUIRENTE -> substring -> KEYWORD -> "Outros". Ela não é
    arbitrária, é o que torna a extensão SEGURA para quem já chamava esta função:

    - `exato` continua primeiro: categoria CUSTOMIZADA do usuário chamada
      "Padaria" nunca é sequestrada por uma regra.
    - `adquirente` entra antes do substring porque só dispara quando a entrada
      contém "*" E o token antes dele está numa tabela fechada. Nome de
      categoria não tem "*" — logo o passe é inalcançável a partir de uma
      resposta do modelo ou de um nome vindo do cliente, que são as três
      chamadas que já existiam.
    - `keyword` fica DEPOIS do substring: são palavras portuguesas comuns
      ("padaria", "posto") e na frente sequestrariam a categoria customizada do
      usuário. Atrás, elas só resgatam o que iria para "Outros" — a mudança é
      ESTRITAMENTE ADITIVA (só transforma "Outros" em outra coisa, nunca o
      contrário), que é o que faz a não-regressão do extrato ser demonstrável.

    Todo alvo de regra passa por `validar_nome_categoria`: regra que aponta para
    categoria que o usuário não tem simplesmente não vale.

    `entrada` tem DUAS naturezas: um NOME de categoria (a resposta do modelo em
    /ai/suggest-category e no lote do extrato; a string do cliente no commit) ou
    uma DESCRIÇÃO de lojista crua (a camada 2 da auto-categoria). A ordem acima
    é o que deixa as duas conviverem numa função só.
    """
    limpo = entrada.strip().strip(".\"'")
    for nome in nomes:
        if limpo.casefold() == nome.casefold():
            return nome, "exato"

    if "*" in entrada:
        token = _normalizar(entrada.split("*", 1)[0])
        alvo = ADQUIRENTES.get(token)
        if alvo is not None:
            valido = validar_nome_categoria(alvo, nomes)
            if valido is not None:
                return valido, f"adquirente:{token}"

    for nome in nomes:
        if nome.casefold() in entrada.casefold():
            return nome, "substring"

    normalizada = _normalizar(entrada)
    for chave, alvo in _KEYWORDS:
        if chave in normalizada:
            valido = validar_nome_categoria(alvo, nomes)
            if valido is not None:
                return valido, f"keyword:{chave}"

    for chave, alvo in _KEYWORDS_INICIO:
        if normalizada.startswith(chave):
            valido = validar_nome_categoria(alvo, nomes)
            if valido is not None:
                return valido, f"inicio:{chave}"

    return CATEGORIA_NEUTRA, None


def casar_categoria(resposta: str, nomes: list[str]) -> str:
    """Garante que a sugestão é uma categoria que o cliente conhece.

    Guarda-corpo de TODA sugestão por IA e de toda categoria vinda do cliente: o
    picker do frontend nunca recebe nome inventado e o banco nunca recebe string
    arbitrária. Casca fina sobre `casar_categoria_detalhado` — um motor, sem
    segunda implementação.
    """
    return casar_categoria_detalhado(resposta, nomes)[0]
