"""Safety settings compartilhados das chamadas ao Gemini (F-06).

FONTE ÚNICA das 4 categorias de moderação. Tanto o assistente/chat
(routers/ai.py) quanto a extração de importação de fatura
(services/import_fatura/gemini.py) importam SAFETY_SETTINGS daqui — nunca
redefinem nem copiam a lista. Uma constante, um lugar (módulo neutro, sem
dependência de router ou service).

BLOCK_ONLY_HIGH, não o default do provedor (que a API pode mudar sozinha):
mantém a barreira de moderação sem recusar consulta financeira legítima — só
bloqueia conteúdo de severidade HIGH (ex.: "gastei R$ 4.000 em armas de fogo"
numa loja de caça e pesca passa). Validado em runtime e aprovado
(ver docs/AUDITORIA_SEGURANCA.md, F-06).
"""

from google.genai import types

SAFETY_SETTINGS = [
    types.SafetySetting(category="HARM_CATEGORY_HARASSMENT",        threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_HATE_SPEECH",        threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_SEXUALLY_EXPLICIT",  threshold="BLOCK_ONLY_HIGH"),
    types.SafetySetting(category="HARM_CATEGORY_DANGEROUS_CONTENT",  threshold="BLOCK_ONLY_HIGH"),
]
