from app.schemas.category import CategoriaResponse

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
    CategoriaResponse(nome="Outros",       icone="📦", tipo="receita", is_padrao=True),
]
