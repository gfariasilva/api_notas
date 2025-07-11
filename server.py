import base64
import json
import os

import requests
from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import pandas as pd
from datetime import datetime

# Instancia uma aplicação FastAPI
app = FastAPI(
    title="API - Analizador de notas de alunos",
    description="API desenvolvida utilizando FastAPI que integra a API do Gemini para recuperar campos de notas de alunos.",
    version="1.0.0",
)

# Adiciona CORS para o front conseguir acessar a API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Recupera variáveis relativas à integração com GEMINI do .env
CHAVE_API_GEMINI = os.environ.get("CHAVE_API_GEMINI")
ENDPOINT_GEMINI = os.environ.get("ENDPOINT_GEMINI")


@app.post("/notas/")
async def processar_documento(arquivo: UploadFile = File(...)):
    """
    Função destinada para envio de arquivo / processamento via Gemini dos mesmos

    Parâmetros:
        arquivo (UploadFile): Imagem do boletim de notas enviado via API.

    Retorno:
        JSON no seguinte formato:
        {
            "payload": [
                {
                    "nome": "José Ruela",
                    "media_frequencia": 97.28571428571429,
                    "media_notas": 82
                },
                {
                    "nome": "João Ninguém",
                    "media_frequencia": 0,
                    "media_notas": 0
                }
            ],
            "dados_brutos": [
                {
                    "nome_aluno": "José Ruela",
                    "frequencias": [
                        96,
                        95,
                        90,
                        100,
                        100,
                        100,
                        100
                    ],
                    "notas": [
                        85,
                        89,
                        89,
                        80,
                        60,
                        85,
                        86
                    ]
                },
                {
                    "nome_aluno": "João Ninguém",
                    "frequencias": [
                        0
                    ],
                    "notas": [
                        0
                    ]
                }
            ]
        }
    """
    try:
        # Recupera o arquivo na forma de bytes
        conteudo = await arquivo.read()
        # Converte o arquivo (bytes) para base64, para enviar para o Gemini
        arquivo_base64 = base64.b64encode(conteudo).decode("utf-8")

        # Monta o cabecalho da requisição, passando a chave da API
        headers = {
            "Content-Type": "application/json",
            "X-goog-api-key": CHAVE_API_GEMINI,
        }

        # Monta o payload para o Gemini
        payload = {
            "contents": [
                {
                    "parts": [
                        {
                            "inline_data": {
                                "mime_type": arquivo.content_type,
                                "data": arquivo_base64,
                            }
                        },
                        {
                            "text": """
                            Você está recebendo um documeto relativo à notas finais do semestre de uma faculdade.
                            Cada página do documento contém notas de dois estudantes, o que pode ser visto na primeira coluna "Nome do Aluno".
                            A primeira metade da página pra cima é do aluno X, e a segunda metade da página pra baixo é do aluno Y
                            Retorne para mim os seguintes dados formatados assim:
                            [
                                {
                                    "nome_aluno": nome,
                                    "frequencias": frequencias,
                                    "notas" : [nota, nota, nota, ...]
                                },
                                {
                                    "nome_aluno": nome,
                                    "frequencias": [frequencia, frequencia, frequencia, ...],
                                    "notas" : [nota, nota, nota, ...]
                                },
                            ]
                            O campo "nome_aluno" você deve resgatar da coluna "Nome do Aluno"
                            O campo "frequencias" você deve retornar todos os valores inteiros da coluna "% de Freq." (campos que contém '-', ou seja, que não são números, colocar como 100).
                            O campo "notas" me retorne todos os valores inteiros da coluna "AF" (5 colunas à direita da coluna "% de Freq." que você acabou de atualizar)
                            
                            Preste atenção na coluna "Resultado Final". Caso o resultado seja "EVADIDO", colocar os campos "frequencias" e "notas" como [0] (array com um único campo 0).

                            Faça isso para tanto o aluno X quanto o aluno Y de cada página, e não retorne nenhum texto adicional além do resultado passado no formato que especifiquei.
                        """
                        },
                    ]
                }
            ]
        }

        # Realiza a requisição, passando a imagem, prompt e headers para a API do Gemini
        resposta = requests.post(ENDPOINT_GEMINI, headers=headers, json=payload)

        # Retorna erro, caso haja algum
        if resposta.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={
                    "erro": "Erro ao processar imagem no Gemini",
                    "detalhe": resposta.text,
                },
            )

        # Retorna resultado do gemini
        resposta_json = resposta.json()
        # Dentro dos metadados que o Gemini retorna, obtém o real retorno do prompt
        campos = resposta_json["candidates"][0]["content"]["parts"][0]["text"]
        # O Gemini retorna os valores dentro de um markdown, por isso, substitui as partes que definem o markdown com strings vazias
        campos_formatados = json.loads(
            campos.replace("```json\n", "").replace("\n```", "")
        )

        # Cria o JSON de retorno com os campos devidamente formatados
        retorno = {"payload": [], "dados_brutos": campos_formatados}

        for aluno in campos_formatados:
            retorno["payload"].append(
                {
                    "nome": aluno["nome_aluno"],
                    "media_frequencia": round(sum(aluno["frequencias"]) / len(aluno["frequencias"]), 2) if sum(aluno["frequencias"]) else 0,
                    "media_notas": round(sum(aluno["notas"]) / len(aluno["notas"]), 2) if sum(aluno["frequencias"]) else 0,
                }
            )

        # Converte os dados do payload para um DataFrame
        df_resumo = pd.DataFrame(retorno["payload"])

        # Converte os dados brutos para DataFrame também
        df_detalhado = pd.DataFrame(retorno["dados_brutos"])

        # Cria um nome de arquivo com timestamp pra evitar sobrescrita
        nome_arquivo = f"notas_alunos_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"

        # Caminho onde o arquivo será salvo (raiz do projeto)
        caminho_arquivo = os.path.join("/app", nome_arquivo)

        # Escreve os dados no Excel, em duas abas
        with pd.ExcelWriter(caminho_arquivo, engine="openpyxl") as writer:
            df_resumo.to_excel(writer, sheet_name="Resumo", index=False)
            df_detalhado.to_excel(writer, sheet_name="Detalhado", index=False)

        print(f"Arquivo salvo em: {caminho_arquivo}")

        return retorno

    except Exception as e:
        return JSONResponse(status_code=500, content={"Erro": str(e)})
