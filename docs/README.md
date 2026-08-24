# docs/ — fonte única dos documentos do Hivvo

O Hivvo vive em dois repositórios (`hivvo-api` e `hivvo-web`) que compartilham
documentos de produto e de plano. **Esta pasta é a fonte canônica deles.**

## A regra

> **Edite sempre no `hivvo-api` e rode o sync. Nunca copie à mão.**

Cópia manual foi exatamente o que fez os docs divergirem: em 15/07/2026 três
compartilhados estavam com versões diferentes nos dois repos, e num deles
(`PLANO_PERFIL_CONFIG.md`) a cópia do web era **mais nova no mtime mas mais
velha no conteúdo** — uma cópia manual havia sobrescrito a versão corrigida com
a antiga. O mtime não protege ninguém; o script protege.

```bash
python scripts/sync-docs.py            # copia os compartilhados → hivvo-web/docs
python scripts/sync-docs.py --check    # não escreve; sai 1 se algo divergir
```

Destino padrão: `../hivvo-web/docs` (os repos são irmãos). Para outro caminho,
use `--dest ../caminho/docs` ou a variável `HIVVO_WEB_DOCS`.

## Docs COMPARTILHADOS (canônicos aqui, copiados para o hivvo-web)

Edite aqui. A cópia no `hivvo-web/docs` é gerada — qualquer edição feita lá é
perdida no próximo sync.

| Doc | Assunto |
|---|---|
| `DECISAO_A_PAGAR_SALDO.md` | Decisão de produto: "a pagar" vs saldo |
| `Hivvo_Referencia.md` | Referência do produto: visão, brand, telas, arquitetura dos dois repos |
| `PLANO_3D_PAGAMENTO_FATURA.md` | Plano: pagamento de fatura |
| `PLANO_DASHBOARD_DOIS_BLOCOS.md` | Plano: dashboard em dois blocos |
| `PLANO_IMPORTACAO.md` | Plano: importação de dados |
| `PLANO_PERFIL_CONFIG.md` | Plano: separação Perfil vs Configurações |
| `PLANO_PROJECAO.md` | Plano: projeção |
| `PLANO_RESUMO.md` | Plano: tela de Resumo / análise |

A lista de verdade — a que o script obedece — é a constante `SHARED` em
[`scripts/sync-docs.py`](../scripts/sync-docs.py). Para tornar um doc
compartilhado, adicione-o lá **e** nesta tabela.

## Docs ESPECÍFICOS deste repo (não sincronizados)

Não há nenhum. Todos os documentos que existiam só aqui eram **operacionais** e
saíram deste repositório em 24/08/2026 — ver a seção seguinte.

## Documentação operacional (fora deste repositório)

O projeto mantém, num **repositório privado separado**, a documentação que
descreve a operação do sistema: auditorias internas de segurança e de
arquitetura, o backlog priorizado, os diários de sessão, os planos de execução e
a configuração de deploy.

**Ela é privada porque descreve um sistema em produção.** Não é rascunho nem
material incompleto: é o tipo de documento cujo valor para quem opera é o mesmo
que o valor para quem quisesse atacar. Estes repositórios de código são
públicos; aquele não é.

O que fica aqui é o que descreve o **produto e as decisões de desenho** — a
referência, as decisões de produto e os planos de funcionalidade listados acima.
Nada do que saiu é necessário para entender, construir ou rodar este código.

Este `README.md` também é específico de repo: o `hivvo-web/docs/README.md` é um
aviso curto apontando para cá, e por isso nenhum dos dois entra no sync.
